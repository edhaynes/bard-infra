"""Helpers for emitting the protocol Error envelope as an HTTP response."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from common.protocol import ProtocolError


def error_response(
    status: int, error: str, *, retry: bool = False, detail: str | None = None
) -> JSONResponse:
    """Build a JSONResponse carrying a contract-shaped Error body."""
    body = ProtocolError(error=error, retry=retry, detail=detail).model_dump(exclude_none=True)
    return JSONResponse(status_code=status, content=body)
