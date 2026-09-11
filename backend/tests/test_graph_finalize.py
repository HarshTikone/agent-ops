"""Tests for `finalize_node`'s answer validation and cross-provider retry.

The invariant under test, stated once: **finalize never reports `done` without
an answer that passed `validate_answer`, and never stamps `level="success"` on
an answer it rejected.** Before this node was fixed, production held three
`done` sessions with an empty answer and one that shipped raw tool-call markup
to a user — every one of them traced as a success.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.graph.nodes import make_finalize_node
from app.graph.state import GraphState, initial_state
from app.llm.base import LLMResponse

_MARKUP = (
    "<tool_call>\n<function=notes_store>\n<parameter=key>k</parameter>\n</function>\n</tool_call>"
)
_GOOD = "The note was saved and read back with the value 'rls-fix-verified'."


class ScriptedProvider:
    """A provider that returns a fixed sequence of contents, then repeats the last."""

    def __init__(self, *contents: str, name: str = "scripted") -> None:
        self.name = name
        self._contents = list(contents) or [""]
        self.calls = 0

    def generate(
        self, messages: list[BaseMessage], tools: list[BaseTool] | None = None
    ) -> LLMResponse:
        content = self._contents[min(self.calls, len(self._contents) - 1)]
        self.calls += 1
        return LLMResponse(content=content, tool_calls=[], provider=self.name)


def state_with_results(*results: tuple[str, str]) -> GraphState:
    """Graph state carrying a completed step per (tool_name, output) pair."""
    state = initial_state("Save a note and read it back")
    messages: list[BaseMessage] = [HumanMessage(content=state["task"])]
    for index, (tool_name, output) in enumerate(results):
        call_id = f"call_{index}"
        messages.append(AIMessage(content="", tool_calls=[]))
        messages.append(ToolMessage(content=output, tool_call_id=call_id, name=tool_name))
    state["messages"] = messages
    return state


def finalize_events(result: dict) -> list[dict]:
    return [event for event in result["trace"] if event["node"] == "finalize"]


class TestAcceptsUsableAnswers:
    def test_usable_answer_is_reported_done(self) -> None:
        node = make_finalize_node(ScriptedProvider(_GOOD, name="gemini"))
        result = node(state_with_results(("notes_store", "OK: saved")))

        assert result["status"] == "done"
        assert result["final_answer"] == _GOOD

    def test_success_event_records_the_answering_provider(self) -> None:
        node = make_finalize_node(ScriptedProvider(_GOOD, name="gemini"))
        events = finalize_events(node(state_with_results(("notes_store", "OK: saved"))))

        assert len(events) == 1
        assert events[0]["level"] == "success"
        assert events[0]["provider"] == "gemini"

    def test_retry_provider_is_not_called_when_the_first_answer_is_good(self) -> None:
        retry = ScriptedProvider(_GOOD, name="openrouter")
        node = make_finalize_node(ScriptedProvider(_GOOD, name="gemini"), retry)
        node(state_with_results(("calculator", "OK: 1289.4")))

        assert retry.calls == 0


class TestRejectsAndRetries:
    def test_empty_answer_falls_through_to_the_other_provider(self) -> None:
        """The exact production failure: gemini 200s with no text."""
        node = make_finalize_node(
            ScriptedProvider("", name="gemini"),
            ScriptedProvider(_GOOD, name="openrouter"),
        )
        result = node(state_with_results(("calculator", "OK: 1289.4")))

        assert result["status"] == "done"
        assert result["final_answer"] == _GOOD

    def test_markup_answer_falls_through_to_the_other_provider(self) -> None:
        node = make_finalize_node(
            ScriptedProvider(_MARKUP, name="gemini"),
            ScriptedProvider(_GOOD, name="openrouter"),
        )
        result = node(state_with_results(("notes_store", "OK: saved")))

        assert result["status"] == "done"
        assert result["final_answer"] == _GOOD

    def test_rejection_is_recorded_even_when_the_retry_succeeds(self) -> None:
        """A near-miss must stay visible — that is the whole point of a trace."""
        node = make_finalize_node(
            ScriptedProvider("", name="gemini"),
            ScriptedProvider(_GOOD, name="openrouter"),
        )
        events = finalize_events(node(state_with_results(("calculator", "OK: 1289.4"))))

        assert [event["level"] for event in events] == ["warning", "success"]
        assert "REJECTED" in events[0]["detail"]
        assert "answer is empty" in events[0]["detail"]
        assert events[0]["provider"] == "gemini"
        assert events[1]["provider"] == "openrouter"

    def test_trace_sequences_stay_unique_and_monotonic(self) -> None:
        """Two events from one node must not collide — they insert by sequence."""
        node = make_finalize_node(
            ScriptedProvider("", name="gemini"),
            ScriptedProvider(_GOOD, name="openrouter"),
        )
        result = node(state_with_results(("calculator", "OK: 1289.4")))
        sequences = [event["sequence"] for event in result["trace"]]

        assert sequences == sorted(sequences)
        assert len(sequences) == len(set(sequences))

    def test_retry_is_attempted_exactly_once(self) -> None:
        retry = ScriptedProvider("", name="openrouter")
        node = make_finalize_node(ScriptedProvider("", name="gemini"), retry)
        node(state_with_results(("calculator", "OK: 1289.4")))

        assert retry.calls == 1


class TestDegradesWhenNoProviderAnswers:
    def _degraded(self) -> dict:
        node = make_finalize_node(
            ScriptedProvider("", name="gemini"),
            ScriptedProvider(_MARKUP, name="openrouter"),
        )
        return node(state_with_results(("calculator", "OK: 1289.4"), ("notes_store", "OK: saved")))

    def test_status_is_degraded_never_done(self) -> None:
        assert self._degraded()["status"] == "degraded"

    def test_fallback_answer_reports_the_tool_results(self) -> None:
        answer = self._degraded()["final_answer"]

        assert "calculator" in answer and "1289.4" in answer
        assert "notes_store" in answer and "OK: saved" in answer

    def test_fallback_answer_itself_passes_validation(self) -> None:
        from app.answer_quality import validate_answer

        assert validate_answer(self._degraded()["final_answer"]) is None

    def test_final_event_is_an_error_not_a_success(self) -> None:
        events = finalize_events(self._degraded())

        assert events[-1]["level"] == "error"
        assert "degraded" in events[-1]["detail"]
        assert not any(event["level"] == "success" for event in events)

    def test_degrades_without_a_retry_provider_configured(self) -> None:
        node = make_finalize_node(ScriptedProvider("", name="gemini"))
        result = node(state_with_results(("calculator", "OK: 1289.4")))

        assert result["status"] == "degraded"

    def test_tool_output_containing_markup_cannot_poison_the_fallback(self) -> None:
        from app.answer_quality import validate_answer

        node = make_finalize_node(ScriptedProvider("", name="gemini"))
        result = node(state_with_results(("notes_store", f"OK: saved {_MARKUP}")))

        assert result["status"] == "degraded"
        assert validate_answer(result["final_answer"]) is None

    def test_run_with_no_tool_results_still_degrades_with_a_valid_answer(self) -> None:
        from app.answer_quality import validate_answer

        node = make_finalize_node(ScriptedProvider("", name="gemini"))
        result = node(state_with_results())

        assert result["status"] == "degraded"
        assert validate_answer(result["final_answer"]) is None
