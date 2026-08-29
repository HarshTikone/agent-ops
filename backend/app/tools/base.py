"""The uniform tool-adapter interface every tool implements."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class Tool(Protocol):
    name: str
    description: str

    @property
    def args_schema(self) -> type[BaseModel]: ...

    def invoke(self, arguments: dict[str, object]) -> str:
        """Validate and execute one planner-supplied argument mapping."""
        ...
