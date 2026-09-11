"""Tests for the shared usable-answer definition.

The markup cases are not hypothetical: `_SESSION_A675_ANSWER` is the verbatim
`final_answer` of a production session that the previous QA pass recorded as
verified, because it asserted on `status == "done"` and never looked at the
text. That string is the regression this module exists to prevent.
"""

from __future__ import annotations

import pytest

from app.answer_quality import (
    MIN_ANSWER_CHARS,
    is_usable,
    scrub_tool_markup,
    validate_answer,
)

_SESSION_A675_ANSWER = (
    "<tool_call>\n"
    "<function=notes_store>\n"
    "<parameter=key>\nqa_recheck_20260906\n</parameter>\n"
    "<parameter=action>\nread\n</parameter>\n"
    "</function>\n"
    "</tool_call>\n"
)

_GOOD_ANSWER = (
    "The note 'qa_recheck_20260906' was saved and read back with the value 'rls-fix-verified'."
)


class TestRejectsUnusableAnswers:
    def test_none_is_rejected(self) -> None:
        assert validate_answer(None) == "answer is null"

    def test_empty_string_is_rejected(self) -> None:
        # The exact shape of 3 of 18 production `done` sessions.
        assert validate_answer("") == "answer is empty"

    @pytest.mark.parametrize("blank", ["   ", "\n", "\t\n  ", "\r\n"])
    def test_whitespace_only_is_rejected(self, blank: str) -> None:
        assert validate_answer(blank) == "answer is empty"

    def test_production_markup_leak_is_rejected(self) -> None:
        assert validate_answer(_SESSION_A675_ANSWER) == "answer contains raw tool-call markup"

    @pytest.mark.parametrize(
        "markup",
        [
            "<tool_call>",
            "</tool_call>",
            "<function=calculator>",
            "<parameter=expression>",
            "<|tool_call|>",
            "<|tool_calls|>",
        ],
    )
    def test_each_markup_shape_is_rejected(self, markup: str) -> None:
        assert validate_answer(markup) == "answer contains raw tool-call markup"

    def test_markup_appended_to_real_prose_is_still_rejected(self) -> None:
        """Mostly-prose answers still leak protocol — they are not a pass."""
        polluted = f"{_GOOD_ANSWER}\n\n<tool_call><function=notes_store></function></tool_call>"
        assert validate_answer(polluted) == "answer contains raw tool-call markup"

    def test_markup_is_matched_case_insensitively(self) -> None:
        assert validate_answer("<TOOL_CALL>") == "answer contains raw tool-call markup"

    def test_too_short_is_rejected(self) -> None:
        reason = validate_answer("ok")
        assert reason is not None and "shorter than" in reason

    def test_bare_number_is_rejected(self) -> None:
        """A calculator result alone is a tool output, not an answer."""
        assert validate_answer("1289.4") is not None


class TestAcceptsUsableAnswers:
    def test_ordinary_answer_passes(self) -> None:
        assert validate_answer(_GOOD_ANSWER) is None
        assert is_usable(_GOOD_ANSWER) is True

    def test_leading_and_trailing_whitespace_is_tolerated(self) -> None:
        assert validate_answer(f"\n\n  {_GOOD_ANSWER}  \n") is None

    def test_answer_at_exactly_the_minimum_length_passes(self) -> None:
        assert validate_answer("x" * MIN_ANSWER_CHARS) is None

    def test_angle_brackets_that_are_not_tool_markup_pass(self) -> None:
        """Prose about comparisons and HTML must not trip the markup rule."""
        assert validate_answer("The result is <20 and the tag was <div>, per the docs.") is None


class TestScrubToolMarkup:
    def test_scrubbed_markup_no_longer_fails_validation(self) -> None:
        scrubbed = scrub_tool_markup(_SESSION_A675_ANSWER)
        assert validate_answer(scrubbed) is None

    def test_scrubbing_preserves_surrounding_text(self) -> None:
        scrubbed = scrub_tool_markup("before <tool_call> after")
        assert "before" in scrubbed and "after" in scrubbed

    def test_clean_text_is_unchanged(self) -> None:
        assert scrub_tool_markup(_GOOD_ANSWER) == _GOOD_ANSWER
