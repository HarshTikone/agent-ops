"""Authentication for state-changing API operations."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


def require_operator_key(
    provided_key: Annotated[str | None, Header(alias="X-Agent-Ops-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    """Fail closed and compare the configured operator key in constant time."""
    expected_key = settings.agent_ops_api_key.get_secret_value()
    if (
        not expected_key
        or provided_key is None
        or not secrets.compare_digest(provided_key, expected_key)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="valid operator credentials are required",
            headers={"WWW-Authenticate": "AgentOpsKey"},
        )
