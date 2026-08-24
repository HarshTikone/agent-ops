"""The checkpoint serializer every checkpointer construction site should
use — pre-registers `ToolCallRequest` as an explicitly allowed msgpack type.

Verified directly (not assumed from the warning text): LangGraph's default
serde mode ("warn but allow") logs `Deserializing unregistered type ...
This will be blocked in a future version` for ANY custom class it has to
reconstruct that isn't in its own built-in safe list — including a Pydantic
v2 model like `ToolCallRequest`, which gets a different wire encoding but
goes through the identical allowlist check on the way back out. Passing
`allowed_msgpack_modules` explicitly is what actually silences it, not
switching from a dataclass to Pydantic by itself (ADR-014).
"""

from __future__ import annotations

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

GRAPH_SERDE = JsonPlusSerializer(allowed_msgpack_modules=[("app.llm.base", "ToolCallRequest")])
