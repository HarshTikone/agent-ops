"""Full-session integration tests (Day 3 requirement) — real Postgres, real
persistence, no mocked repository layer.

Two complementary tests:

- `test_full_session_through_the_real_api_including_approval`: goes through
  the actual FastAPI app via `TestClient`, real Gemini, real tools, real DB
  — proves the HTTP wiring (create session -> message -> approval pause ->
  approve -> done) is correct end to end, matching what live verification
  during design already confirmed manually.
- `test_forced_transient_failure_retries_and_persists_correctly`: calls
  `session_runner` directly with a scripted LLM and a substituted flaky
  tool. `CalculatorTool`'s own failure modes are all permanent by design
  (ADR-011: bad input doesn't become good input on retry) — there's no way
  to force a genuinely *transient* failure through any of the three real
  tools without a fragile network trick, so this test substitutes one
  in-memory flaky tool for exactly that purpose. The retry DECISION logic
  itself is already covered at the graph level (test_graph_decide_next.py);
  what's new here is proving the persisted trace_events/session status end
  up correct when it happens.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import repository as repo
from app.db import get_checkpointer
from app.graph.build import build_graph
from app.graph.state import initial_state
from app.llm.base import LLMResponse, ToolCallRequest
from app.main import app
from app.session_runner import _apply_result
from app.tools.errors import ToolError
from app.tools.registry import build_tool_registry, to_langchain_tools


class _ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)

    def generate(self, messages, tools=None) -> LLMResponse:
        if not self._responses:
            raise AssertionError("llm.generate() called more times than scripted")
        return self._responses.pop(0)


def test_list_sessions_endpoint_returns_most_recent_first(db_pool) -> None:
    client = TestClient(app)
    older = client.post("/sessions").json()
    newer = client.post("/sessions").json()
    try:
        listed = client.get("/sessions").json()
        ids_in_order = [s["id"] for s in listed]
        assert ids_in_order.index(newer["id"]) < ids_in_order.index(older["id"])
        assert all(
            s["pending_action"] is None for s in listed if s["status"] != "awaiting_approval"
        )
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id IN (%s, %s)", (older["id"], newer["id"]))


def test_full_session_through_the_real_api_including_approval(db_pool) -> None:
    client = TestClient(app)

    created = client.post("/sessions")
    assert created.status_code == 201
    session_id = created.json()["id"]
    assert created.json()["status"] == "created"

    try:
        sent = client.post(
            f"/sessions/{session_id}/messages",
            json={
                "content": "Save a note with key 'topic' and content 'agent ops', using the notes tool."
            },
        )
        assert sent.status_code == 200
        assert sent.json()["status"] == "awaiting_approval"
        embedded_pending = sent.json()["pending_action"]
        assert embedded_pending is not None
        assert embedded_pending["tool_name"] == "notes_store"
        assert embedded_pending["status"] == "pending"

        # a second message to an already-running session is a clear 409
        rejected_second_message = client.post(
            f"/sessions/{session_id}/messages", json={"content": "anything"}
        )
        assert rejected_second_message.status_code == 409

        trace_before = client.get(f"/sessions/{session_id}/trace").json()
        assert any(e["node"] == "delegate" for e in trace_before)
        assert not any(e["node"] == "tool_call" for e in trace_before)  # not run yet

        with db_pool.connection() as conn:
            pending = conn.execute(
                "SELECT id, status FROM pending_actions WHERE session_id = %s", (session_id,)
            ).fetchone()
        assert pending["status"] == "pending"

        approved = client.post(f"/approvals/{pending['id']}/approve")
        assert approved.status_code == 200
        # approve now returns the SESSION (ADR-018), not the bare decided
        # pending_action — its own status came back "executed" separately
        # (checked via the DB below), since the two are different things.
        assert approved.json()["status"] == "done"
        assert approved.json()["pending_action"] is None
        assert approved.json()["final_answer"]

        with db_pool.connection() as conn:
            decided = conn.execute(
                "SELECT status FROM pending_actions WHERE id = %s", (pending["id"],)
            ).fetchone()
        assert decided["status"] == "executed"

        # approving again must be a clear 409, not a silent double-apply
        double_approve = client.post(f"/approvals/{pending['id']}/approve")
        assert double_approve.status_code == 409

        final_session = client.get(f"/sessions/{session_id}").json()
        assert final_session["status"] == "done"
        assert final_session["final_answer"]

        trace_after = client.get(f"/sessions/{session_id}/trace").json()
        nodes = [e["node"] for e in trace_after]
        assert "approval_gate" in nodes
        assert "tool_call" in nodes
        assert "finalize" in nodes

        assert repo.read_note(db_pool, session_id, key="topic") == "agent ops"
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        # sessions -> messages/trace_events/pending_actions/session_memory
        # cascade on delete, but the checkpointer's own tables are keyed by
        # thread_id, not a foreign key into `sessions` — orphaned otherwise
        # (a real gap for production too, see ADR-014's "what we gave up").
        get_checkpointer().delete_thread(str(session_id))


class _FlakyCalculator:
    """Fails transiently exactly once, then behaves like the real
    calculator would for `2 + 2`."""

    name = "calculator"
    description = "flaky calculator for testing the retry path"
    args_schema = None

    def __init__(self) -> None:
        self.calls = 0

    def run(self, **kwargs) -> str:
        self.calls += 1
        if self.calls == 1:
            raise ToolError("simulated transient network blip", transient=True)
        return "4"


def test_forced_transient_failure_retries_and_persists_correctly(db_pool) -> None:
    session = repo.create_session(db_pool)
    session_id = session["id"]

    try:
        flaky = _FlakyCalculator()
        tools = build_tool_registry(tavily_api_key="", db_pool=db_pool, session_id=session_id)
        tools["calculator"] = flaky
        langchain_tools = to_langchain_tools(tools)

        llm = _ScriptedLLM(
            [
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCallRequest(id="c1", name="calculator", arguments={"expression": "2+2"})
                    ],
                    provider="gemini",
                ),
                LLMResponse(content="the answer is 4", tool_calls=[], provider="gemini"),
            ]
        )
        graph = build_graph(llm, tools, langchain_tools, checkpointer=get_checkpointer())
        config = {"configurable": {"thread_id": str(session_id)}}

        repo.start_session(db_pool, session_id, task="compute 2+2")
        result = graph.invoke(initial_state("compute 2+2"), config=config)
        _apply_result(db_pool, session_id, result)

        assert flaky.calls == 2  # failed once, retried once, succeeded

        final_session = repo.get_session(db_pool, session_id)
        assert final_session["status"] == "done"
        assert final_session["final_answer"] == "the answer is 4"

        events = repo.list_trace_events(db_pool, session_id)
        details_by_node = [(e["node"], e["detail"]) for e in events]
        assert any(
            node == "tool_call" and "FAILED (transient)" in detail
            for node, detail in details_by_node
        )
        assert any(node == "decide_next" and "retry" in detail for node, detail in details_by_node)
        assert any(node == "tool_call" and detail == "OK: 4" for node, detail in details_by_node)
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        get_checkpointer().delete_thread(str(session_id))
