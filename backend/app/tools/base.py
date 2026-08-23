"""The uniform tool-adapter interface every tool implements."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel


class Tool(Protocol):
    name: str
    description: str
    args_schema: type[BaseModel]

    def run(self, **kwargs: Any) -> str: ...
