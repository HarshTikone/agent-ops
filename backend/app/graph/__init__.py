"""The LangGraph agent graph (ADR-001, ARCHITECTURE.md §2/§3/§4):

planner -> delegate -> tool_call -> observe -> decide_next -> (retry | replan | finalize | give up)

State stays in-memory for Day 2 (ARCHITECTURE.md's Supabase-backed trace log
and session memory arrive Day 3) — `state["trace"]` is a lightweight in-memory
stand-in for the real `trace_events` table.
"""
