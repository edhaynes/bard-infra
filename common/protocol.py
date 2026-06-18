"""Pydantic models mirroring ``contracts/protocol.schema.json``.

The JSON Schema is the canonical contract; these models are the Python
projection of it for the FastAPI lanes. Field names stay camelCase to match the
wire format exactly. If the two ever disagree, the schema wins — fix it there
and update these to match (see ``tests/test_contracts.py``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    output: str


class RequestMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targetAgent: str
    sessionId: str | None = None
    timestamp: str | None = None
    authToken: str


class ResponseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agentId: str
    sessionId: str | None = None
    timestamp: str | None = None
    toolCalls: list[ToolCall] = Field(default_factory=list)
    toolResults: list[ToolResult] = Field(default_factory=list)


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["text", "voice"]
    content: str
    metadata: RequestMetadata


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["text", "voice"]
    content: str
    metadata: ResponseMetadata


class ProtocolError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: str
    retry: bool = False
    detail: str | None = None
