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

import logging
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import repository as repo
from app import session_runner
from app.db import create_checkpointer, get_checkpointer, get_db_pool
from app.graph.build import build_graph
from app.graph.state import initial_state
from app.llm.base import LLMResponse, ToolCallRequest
from app.main import app
from app.rate_limit import limiter
from app.resources import get_http_client
from app.security import require_operator_key
from app.session_runner import _apply_result
from app.tools.errors import ToolError
from app.tools.registry import build_tool_registry, to_langchain_tools


@pytest.fixture(autouse=True)
def _wire_application_resources(db_pool):
    """Integration requests reuse the real fixture pool without app startup."""
    client = httpx.Client(timeout=15)
    checkpointer = create_checkpointer(db_pool)
    app.dependency_overrides[get_db_pool] = lambda: db_pool
    app.dependency_overrides[get_checkpointer] = lambda: checkpointer
    app.dependency_overrides[get_http_client] = lambda: client
    app.dependency_overrides[require_operator_key] = lambda: None
    limiter.reset()
    yield
    limiter.reset()
    client.close()
    app.dependency_overrides.clear()


class _ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def generate(self, messages, tools=None) -> LLMResponse:
        self.calls += 1
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


def test_archive_and_restore_session_through_the_real_api(db_pool) -> None:
    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]
    try:
        listed_before = client.get("/sessions").json()
        assert any(s["id"] == session_id for s in listed_before)

        archived = client.post(f"/sessions/{session_id}/archive")
        assert archived.status_code == 200
        assert archived.json()["archived_at"] is not None

        listed_after_archive = client.get("/sessions").json()
        assert not any(s["id"] == session_id for s in listed_after_archive)

        listed_including_archived = client.get("/sessions?include_archived=true").json()
        assert any(s["id"] == session_id for s in listed_including_archived)

        # the session still opens directly by URL while archived
        fetched = client.get(f"/sessions/{session_id}")
        assert fetched.status_code == 200
        assert fetched.json()["archived_at"] is not None

        restored = client.post(f"/sessions/{session_id}/restore")
        assert restored.status_code == 200
        assert restored.json()["archived_at"] is None

        listed_after_restore = client.get("/sessions").json()
        assert any(s["id"] == session_id for s in listed_after_restore)
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def test_archive_session_returns_404_when_missing() -> None:
    client = TestClient(app)
    response = client.post("/sessions/00000000-0000-0000-0000-000000000000/archive")
    assert response.status_code == 404


@pytest.mark.live
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
        create_checkpointer(db_pool).delete_thread(str(session_id))


class _FlakyCalculator:
    """Fails transiently exactly once, then behaves like the real
    calculator would for `2 + 2`."""

    name = "calculator"
    description = "flaky calculator for testing the retry path"
    args_schema = None

    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, arguments: dict[str, object]) -> str:
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
                # P2: a completed plan now routes through `verify` before `finalize`.
                LLMResponse(content="DONE", tool_calls=[], provider="gemini"),
                LLMResponse(content="the answer is 4", tool_calls=[], provider="gemini"),
            ]
        )
        graph = build_graph(llm, tools, langchain_tools, checkpointer=create_checkpointer(db_pool))
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
        create_checkpointer(db_pool).delete_thread(str(session_id))


def test_heartbeat_keeps_updated_at_moving_during_a_slow_run(db_pool, monkeypatch) -> None:
    """WP2 (Sprint 04, ADR-035): a single LLM call can legitimately take
    minutes (a real provider timeout plus failover) -- outside of a
    heartbeat, `updated_at` only changes at the start and the end of a run,
    making a genuinely slow one indistinguishable from a dead one to
    `scripts/reap_sessions.py`'s staleness check. The heartbeat must keep
    `updated_at` moving while a run is genuinely still executing, not just
    at the moment it finishes."""
    monkeypatch.setattr(session_runner, "HEARTBEAT_INTERVAL_SECONDS", 0.05)

    session = repo.create_session(db_pool)
    session_id = session["id"]
    repo.start_session(db_pool, session_id, task="slow task")
    before = repo.get_session(db_pool, session_id)["updated_at"]
    observed = {"moved": False}

    class _SlowLLM:
        def generate(self, messages, tools=None) -> LLMResponse:
            # Several heartbeat intervals (0.05s each) at 0.2s -- the
            # heartbeat thread should have fired at least once by now.
            time.sleep(0.2)
            current = repo.get_session(db_pool, session_id)["updated_at"]
            observed["moved"] = current > before
            return LLMResponse(
                content="a real enough answer for this test", tool_calls=[], provider="test"
            )

    try:
        session_runner.start_session_run(
            db_pool,
            create_checkpointer(db_pool),
            _SlowLLM(),
            session_id=session_id,
            task="slow task",
            tavily_api_key="",
        )
        assert observed["moved"], "updated_at never moved while the run was still executing"
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        create_checkpointer(db_pool).delete_thread(str(session_id))


class _RaisingProvider:
    """Simulates any uncaught exception during a run (a provider
    construction error like C1, a DB blip, a genuine bug) — anything that
    isn't a ToolError the graph itself already handles."""

    def generate(self, messages, tools=None):
        raise RuntimeError("simulated provider crash")


def _approval_provider(*, key: str = "k", content: str = "v") -> _ScriptedLLM:
    return _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="approval-step",
                        name="notes_store",
                        arguments={"action": "write", "key": key, "content": content},
                    )
                ],
                provider="test",
            ),
            LLMResponse(content="saved", tool_calls=[], provider="test"),
        ]
    )


def test_rejection_is_terminal_through_the_api(db_pool) -> None:
    from app.dependencies import get_llm_provider

    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]
    provider = _approval_provider(key="rejected-key", content="must-not-write")
    app.dependency_overrides[get_llm_provider] = lambda: provider
    try:
        sent = client.post(
            f"/sessions/{session_id}/messages",
            json={"content": "Save a protected note."},
        )
        pending_action_id = sent.json()["pending_action"]["id"]

        rejected = client.post(
            f"/approvals/{pending_action_id}/reject",
            json={"reason": "not authorized"},
        )

        assert rejected.status_code == 200
        assert rejected.json()["status"] == "failed"
        assert rejected.json()["pending_action"] is None
        assert provider.calls == 1
        assert repo.read_note(db_pool, session_id, key="rejected-key") is None
        trace = repo.list_trace_events(db_pool, session_id)
        rejection_events = [event for event in trace if "REJECTED" in event["detail"]]
        assert len(rejection_events) == 1
        assert "not authorized" in rejection_events[0]["detail"]
        assert not any(event["node"] == "tool_call" for event in trace)
        assert not any(event["node"] == "decide_next" for event in trace)
    finally:
        del app.dependency_overrides[get_llm_provider]
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        create_checkpointer(db_pool).delete_thread(str(session_id))


def test_provider_crash_during_send_message_leaves_session_failed_not_stuck(db_pool) -> None:
    """C4 (ADR-020): before this fix, an uncaught exception here left the
    session 'running' forever (repo.start_session's WHERE status='created'
    guard then turned every retry into a 409, permanently) and the client
    got a bare 500 with no record of what happened."""
    from app.dependencies import get_llm_provider

    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]

    app.dependency_overrides[get_llm_provider] = lambda: _RaisingProvider()
    try:
        response = client.post(f"/sessions/{session_id}/messages", json={"content": "do something"})
        assert response.status_code == 502
        assert "detail" in response.json()

        final = repo.get_session(db_pool, session_id)
        assert final["status"] == "failed"
        assert final["final_answer"]

        # 'failed' is a terminal status, but no longer a permanent trap
        # (ADR-030 supersedes ADR-015's one-task-per-session boundary): a
        # message to it is accepted as a follow-up turn via
        # repo.restart_session, not rejected with a 409. The provider is
        # still raising, so this retry crashes again -- correctly a fresh
        # 502, not a hang and not a silent no-op.
        retry = client.post(f"/sessions/{session_id}/messages", json={"content": "retry"})
        assert retry.status_code == 502

        events = repo.list_trace_events(db_pool, session_id)
        assert sum(1 for e in events if e["node"] == "system" and "CRASH" in e["detail"]) == 2
    finally:
        del app.dependency_overrides[get_llm_provider]
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        create_checkpointer(db_pool).delete_thread(str(session_id))


def test_message_to_an_awaiting_approval_session_still_409s(db_pool) -> None:
    """The part of ADR-015's boundary ADR-030 keeps: a session genuinely
    mid-flight -- paused on an approval, the one non-terminal status this
    fully synchronous architecture can ever observe between two requests --
    must still reject a second message with a 409. Only a session that
    reached a terminal status (done/degraded/failed) can take a follow-up."""
    from app.dependencies import get_llm_provider

    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]
    app.dependency_overrides[get_llm_provider] = lambda: _approval_provider()
    try:
        sent = client.post(
            f"/sessions/{session_id}/messages",
            json={"content": "Save a note with key 'k' and content 'v'."},
        )
        assert sent.json()["status"] == "awaiting_approval"

        blocked = client.post(f"/sessions/{session_id}/messages", json={"content": "anything"})
        assert blocked.status_code == 409
    finally:
        del app.dependency_overrides[get_llm_provider]
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        create_checkpointer(db_pool).delete_thread(str(session_id))


def test_add_message_failure_leaves_session_failed_not_stuck(db_pool) -> None:
    """C4 residual gap (day-4-review.md High finding): repo.add_message runs
    after repo.start_session has already committed the row to 'running', so
    it must be covered by the same failed/trace/502 handling as the run
    call itself -- a failure here must not permanently wedge the session at
    'running' with no retry path."""
    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]

    from app.dependencies import get_llm_provider

    app.dependency_overrides[get_llm_provider] = lambda: _RaisingProvider()

    try:
        with patch(
            "app.api.sessions.repo.add_message", side_effect=RuntimeError("simulated db blip")
        ):
            response = client.post(
                f"/sessions/{session_id}/messages", json={"content": "do something"}
            )

        assert response.status_code == 502

        final = repo.get_session(db_pool, session_id)
        assert final["status"] == "failed"
        assert final["final_answer"]

        # 'failed' is terminal but not a permanent trap (ADR-030): a retry
        # is accepted as a follow-up turn, not rejected with a 409. Swap in
        # a working provider to prove the session can actually recover, not
        # just crash again in a different way.
        app.dependency_overrides[get_llm_provider] = lambda: _ScriptedLLM(
            [LLMResponse(content="retried successfully", tool_calls=[], provider="test")]
        )
        retry = client.post(f"/sessions/{session_id}/messages", json={"content": "retry"})
        assert retry.status_code == 200
        assert retry.json()["status"] == "done"
        assert retry.json()["final_answer"] == "retried successfully"

        events = repo.list_trace_events(db_pool, session_id)
        assert any(e["node"] == "system" and "CRASH" in e["detail"] for e in events)
        # WP1 (Sprint 04): the CRASH row is written directly to trace_events
        # (repo.add_trace_event with no explicit sequence -- auto-numbered
        # from the DB's own MAX(sequence)), completely outside the graph's
        # checkpoint. The retry's checkpoint never saw that row, so its own
        # first trace event is computed at the SAME sequence number and
        # silently lost to `ON CONFLICT (session_id, sequence) DO NOTHING`
        # -- the retry still reports "done" with a real answer while its
        # own trace event vanishes. This must not happen.
        assert any(e["node"] == "planner" for e in events), (
            "the retry's own planner trace event was silently dropped "
            f"(sequence collision with the CRASH row); events={events}"
        )
    finally:
        del app.dependency_overrides[get_llm_provider]
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        create_checkpointer(db_pool).delete_thread(str(session_id))


def test_out_of_band_trace_row_does_not_swallow_the_next_turns_events(db_pool) -> None:
    """WP1 (Sprint 04): a trace row written directly to the database (a
    CRASH or REAPED event, both via repo.add_trace_event with no explicit
    sequence) desyncs the checkpoint's notion of trace length from the
    database's actual row count -- the checkpoint never sees that row, so
    the next graph-driven event is computed at a sequence number the row
    already occupies and is silently lost to `ON CONFLICT DO NOTHING`.

    Verified live in production (session ...c61d, reaped then messaged
    again): it reported status 'done' with a real answer while GET
    .../trace still returned only the single REAPED row -- the whole
    follow-up turn's trace was silently dropped."""
    from app.dependencies import get_llm_provider

    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]
    try:
        app.dependency_overrides[get_llm_provider] = lambda: _ScriptedLLM(
            [LLMResponse(content="first", tool_calls=[], provider="test")]
        )
        turn1 = client.post(f"/sessions/{session_id}/messages", json={"content": "one"})
        assert turn1.json()["status"] == "done"

        # An out-of-band trace write, same shape as a CRASH or REAPED row:
        # straight to the database, never through the graph.
        repo.add_trace_event(db_pool, session_id, node="system", detail="SYSTEM ROW")
        repo.update_session_status(db_pool, session_id, status="failed", final_answer="x")

        app.dependency_overrides[get_llm_provider] = lambda: _ScriptedLLM(
            [LLMResponse(content="second", tool_calls=[], provider="test")]
        )
        turn2 = client.post(f"/sessions/{session_id}/messages", json={"content": "two"})
        assert turn2.status_code == 200
        assert turn2.json()["status"] == "done"

        events = repo.list_trace_events(db_pool, session_id)
        planner_events = [e for e in events if e["node"] == "planner"]
        assert len(planner_events) == 2, (
            "turn 2's planner trace event was silently dropped (sequence "
            f"collision with the out-of-band system row); events={events}"
        )
    finally:
        del app.dependency_overrides[get_llm_provider]
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        create_checkpointer(db_pool).delete_thread(str(session_id))


def test_mark_executed_failure_leaves_session_failed_not_stranded(db_pool) -> None:
    """C4 residual gap (day-4-review.md High finding): repo.mark_pending_action_executed
    runs after repo.decide_pending_action has already committed 'approved',
    so a failure here must still be covered by the same failed/trace/502
    handling as the resume call. The pending action itself has no terminal
    'failed' status in this schema and legitimately stays 'approved' (never
    reaching 'executed', since that write is what failed) -- what must NOT
    happen is the session staying wedged at 'awaiting_approval' forever."""
    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]

    from app.dependencies import get_llm_provider

    app.dependency_overrides[get_llm_provider] = lambda: _approval_provider(key="k2", content="v2")
    sent = client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "Save a note with key 'k2' and content 'v2', using the notes tool."},
    )
    assert sent.json()["status"] == "awaiting_approval"
    pending_action_id = sent.json()["pending_action"]["id"]

    try:
        with patch(
            "app.session_runner.repo.mark_pending_action_executed",
            side_effect=RuntimeError("simulated db blip"),
        ):
            response = client.post(f"/approvals/{pending_action_id}/approve")

        assert response.status_code == 502

        final = repo.get_session(db_pool, session_id)
        assert final["status"] == "failed"

        # decide_pending_action already committed 'approved' before the try
        # began; mark_pending_action_executed's write never landed, so the
        # action correctly stays 'approved', not 'executed' -- the session
        # being 'failed' (terminal) is what actually matters here.
        decided = repo.get_pending_action(db_pool, pending_action_id)
        assert decided["status"] == "approved"

        events = repo.list_trace_events(db_pool, session_id)
        assert any(e["node"] == "system" and "CRASH" in e["detail"] for e in events)
    finally:
        del app.dependency_overrides[get_llm_provider]
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        create_checkpointer(db_pool).delete_thread(str(session_id))


def test_provider_crash_during_resume_leaves_session_failed_and_action_executed(db_pool) -> None:
    """The approval-path sibling of the test above, plus the strand check:
    the pending_action must already be 'executed' (marked before the resume
    attempt, ADR-020) even though the resume itself crashed -- not stuck at
    'approved' on a session stuck at 'awaiting_approval' forever."""
    from app.dependencies import get_llm_provider

    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]
    app.dependency_overrides[get_llm_provider] = lambda: _approval_provider()
    sent = client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "Save a note with key 'k' and content 'v', using the notes tool."},
    )
    assert sent.json()["status"] == "awaiting_approval"
    pending_action_id = sent.json()["pending_action"]["id"]

    app.dependency_overrides[get_llm_provider] = lambda: _RaisingProvider()
    try:
        response = client.post(f"/approvals/{pending_action_id}/approve")
    finally:
        del app.dependency_overrides[get_llm_provider]

    try:
        assert response.status_code == 502

        final = repo.get_session(db_pool, session_id)
        assert final["status"] == "failed"

        decided = repo.get_pending_action(db_pool, pending_action_id)
        assert decided["status"] == "executed"

        events = repo.list_trace_events(db_pool, session_id)
        assert any(e["node"] == "system" and "CRASH" in e["detail"] for e in events)
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        create_checkpointer(db_pool).delete_thread(str(session_id))


def test_apply_result_rolls_back_every_write_when_status_update_fails(db_pool) -> None:
    session = repo.create_session(db_pool, task="transaction rollback")
    session_id = session["id"]
    result = {
        "status": "done",
        "final_answer": "finished",
        "trace": [
            {
                "sequence": 1,
                "node": "finalize",
                "detail": "provider=test",
                "level": "success",
                "provider": "test",
            }
        ],
    }

    try:
        with (
            patch(
                "app.session_runner.repo.update_session_status_on_connection",
                side_effect=RuntimeError("simulated final write failure"),
            ),
            pytest.raises(RuntimeError, match="simulated final write failure"),
        ):
            _apply_result(db_pool, session_id, result)

        assert repo.list_trace_events(db_pool, session_id) == []
        assert repo.list_messages(db_pool, session_id) == []
        assert repo.get_session(db_pool, session_id)["status"] == "running"
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def test_apply_result_rejects_nonterminal_graph_exit_and_rolls_back_trace(db_pool) -> None:
    session = repo.create_session(db_pool, task="invalid graph exit")
    session_id = session["id"]
    result = {
        "status": "running",
        "trace": [
            {
                "sequence": 1,
                "node": "planner",
                "detail": "unexpected exit",
                "level": "error",
                "provider": None,
            }
        ],
    }

    try:
        with pytest.raises(RuntimeError, match="without an interrupt or terminal status"):
            _apply_result(db_pool, session_id, result)
        assert repo.list_trace_events(db_pool, session_id) == []
        assert repo.get_session(db_pool, session_id)["status"] == "running"
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def test_apply_result_rolls_back_pending_action_when_status_update_fails(db_pool) -> None:
    session = repo.create_session(db_pool, task="approval rollback")
    session_id = session["id"]
    result = {
        "trace": [],
        "__interrupt__": [
            SimpleNamespace(
                value={
                    "tool_name": "notes_store",
                    "tool_args": {"action": "write", "key": "k", "content": "v"},
                }
            )
        ],
    }

    try:
        with (
            patch(
                "app.session_runner.repo.update_session_status_on_connection",
                side_effect=RuntimeError("simulated status failure"),
            ),
            pytest.raises(RuntimeError, match="simulated status failure"),
        ):
            _apply_result(db_pool, session_id, result)

        assert repo.get_pending_action_for_session(db_pool, session_id) is None
        assert repo.get_session(db_pool, session_id)["status"] == "running"
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def test_resume_failure_before_tool_attempt_leaves_action_approved(db_pool) -> None:
    from app.dependencies import get_llm_provider

    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]
    app.dependency_overrides[get_llm_provider] = lambda: _approval_provider()
    sent = client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "Save a note with key 'k' and content 'v'."},
    )
    pending_action_id = sent.json()["pending_action"]["id"]

    try:
        with patch(
            "app.api.approvals.resume_session_run",
            side_effect=RuntimeError("checkpoint unavailable"),
        ):
            response = client.post(f"/approvals/{pending_action_id}/approve")

        assert response.status_code == 502
        assert repo.get_pending_action(db_pool, pending_action_id)["status"] == "approved"
        assert repo.get_session(db_pool, session_id)["status"] == "failed"
    finally:
        del app.dependency_overrides[get_llm_provider]
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def test_a_note_written_in_turn_one_is_read_back_in_turn_two(db_pool) -> None:
    """ADR-030's core promise: notes_store is scoped per session (a
    deliberate, pre-existing choice, not new here), so a follow-up turn on
    the SAME session can read back what an earlier turn wrote -- something
    no message before this feature could ever do, since a second message
    was unconditionally a 409."""
    from app.dependencies import get_llm_provider

    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]
    scripted = _ScriptedLLM(
        [
            # turn 1: write (needs approval) -> verify -> finalize
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="t1",
                        name="notes_store",
                        arguments={"action": "write", "key": "k", "content": "v1"},
                    )
                ],
                provider="test",
            ),
            LLMResponse(content="DONE", tool_calls=[], provider="test"),
            LLMResponse(content="Saved v1 under key k.", tool_calls=[], provider="test"),
            # turn 2: read (no approval needed) -> verify -> finalize
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="t2", name="notes_store", arguments={"action": "read", "key": "k"}
                    )
                ],
                provider="test",
            ),
            LLMResponse(content="DONE", tool_calls=[], provider="test"),
            LLMResponse(content="The note under key k stores v1.", tool_calls=[], provider="test"),
        ]
    )
    app.dependency_overrides[get_llm_provider] = lambda: scripted
    try:
        turn1 = client.post(
            f"/sessions/{session_id}/messages",
            json={"content": "Save a note with key 'k' and content 'v1', using the notes tool."},
        )
        assert turn1.json()["status"] == "awaiting_approval"
        pending_action_id = turn1.json()["pending_action"]["id"]

        approved = client.post(f"/approvals/{pending_action_id}/approve")
        assert approved.json()["status"] == "done"

        turn2 = client.post(
            f"/sessions/{session_id}/messages",
            json={"content": "What note is stored under key 'k'?"},
        )
        assert turn2.status_code == 200
        assert turn2.json()["status"] == "done"
        assert "v1" in turn2.json()["final_answer"]

        # trace sequences keep climbing across turns -- unique and monotonic
        # over the WHOLE session, not reset per turn.
        events = repo.list_trace_events(db_pool, session_id)
        sequences = [e["sequence"] for e in events]
        assert sequences == sorted(sequences)
        assert len(sequences) == len(set(sequences))
        assert sequences == list(range(1, len(sequences) + 1))
    finally:
        del app.dependency_overrides[get_llm_provider]
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        create_checkpointer(db_pool).delete_thread(str(session_id))


def test_approval_in_turn_two_pauses_and_resumes_correctly(db_pool) -> None:
    """A follow-up turn can hit the same approval gate a first turn can --
    continuing a session must not bypass ADR-016's human-in-the-loop check."""
    from app.dependencies import get_llm_provider

    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]

    # turn 1: no tool call at all -- answers directly, done immediately.
    app.dependency_overrides[get_llm_provider] = lambda: _ScriptedLLM(
        [LLMResponse(content="Sure, what should I remember?", tool_calls=[], provider="test")]
    )
    turn1 = client.post(f"/sessions/{session_id}/messages", json={"content": "hello"})
    assert turn1.json()["status"] == "done"

    # turn 2: a write this time -- must still pause for approval, then
    # (unlike every existing use of _approval_provider in this file, which
    # short-circuits via a crash before reaching this far) actually run
    # verify and finalize to completion.
    app.dependency_overrides[get_llm_provider] = lambda: _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="t1",
                        name="notes_store",
                        arguments={
                            "action": "write",
                            "key": "remember-this",
                            "content": "an important fact",
                        },
                    )
                ],
                provider="test",
            ),
            LLMResponse(content="DONE", tool_calls=[], provider="test"),
            LLMResponse(content="Saved the important fact.", tool_calls=[], provider="test"),
        ]
    )
    try:
        turn2 = client.post(
            f"/sessions/{session_id}/messages",
            json={"content": "Save a note with key 'remember-this'."},
        )
        assert turn2.status_code == 200
        assert turn2.json()["status"] == "awaiting_approval"
        pending_action_id = turn2.json()["pending_action"]["id"]
        assert pending_action_id

        approved = client.post(f"/approvals/{pending_action_id}/approve")
        assert approved.json()["status"] == "done"
        assert repo.read_note(db_pool, session_id, key="remember-this") == "an important fact"
    finally:
        del app.dependency_overrides[get_llm_provider]
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        create_checkpointer(db_pool).delete_thread(str(session_id))


def test_trace_sequence_conflict_with_different_content_is_logged(db_pool, caplog) -> None:
    """WP1/ADR-034: `ON CONFLICT DO NOTHING` silently drops a genuinely lost
    event just as readily as it (correctly) no-ops a replay. A mismatch
    between what's already at a sequence and what the graph just tried to
    write there must be logged, not silent."""
    session = repo.create_session(db_pool, task="conflict test")
    session_id = session["id"]
    repo.add_trace_event(db_pool, session_id, node="system", detail="existing row", sequence=1)
    result = {
        "status": "done",
        "final_answer": "done",
        "trace": [
            {
                "sequence": 1,
                "node": "planner",
                "detail": "a different event entirely",
                "level": "info",
                "provider": None,
            }
        ],
    }
    try:
        with caplog.at_level(logging.WARNING, logger="agent_ops.session_runner"):
            _apply_result(db_pool, session_id, result)

        assert any("trace_sequence_conflict" in record.message for record in caplog.records)
        # ON CONFLICT DO NOTHING really did nothing -- the original row survives.
        events = repo.list_trace_events(db_pool, session_id)
        assert len(events) == 1
        assert events[0]["detail"] == "existing row"
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def test_trace_sequence_conflict_with_identical_content_is_not_logged(db_pool, caplog) -> None:
    """A genuine replay (the same node+detail landing at the same sequence
    a second time) is expected and must stay silent -- this is what makes
    re-applying an already-persisted graph result safe (ADR-024)."""
    session = repo.create_session(db_pool, task="replay test")
    session_id = session["id"]
    repo.add_trace_event(db_pool, session_id, node="planner", detail="same event", sequence=1)
    result = {
        "status": "done",
        "final_answer": "done",
        "trace": [
            {
                "sequence": 1,
                "node": "planner",
                "detail": "same event",
                "level": "info",
                "provider": None,
            }
        ],
    }
    try:
        with caplog.at_level(logging.WARNING, logger="agent_ops.session_runner"):
            _apply_result(db_pool, session_id, result)

        assert not any("trace_sequence_conflict" in record.message for record in caplog.records)
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
