"""FakeAgent: echoes the request and emits a demo toolCall, per agent.openapi.yaml.

Lets Lane A (Router) and Lane F (client) develop against the agent contract
without Lane C's real container. Mirrors the MVP "echo + demo toolCall" agent.
"""

from __future__ import annotations

from common.protocol import (
    Request,
    Response,
    ResponseMetadata,
    ToolCall,
    ToolResult,
)


class FakeAgent:
    def __init__(self, agent_id: str = "fake-agent") -> None:
        self.agent_id = agent_id

    def infer(self, request: Request) -> Response:
        if request.type == "voice":
            raise NotImplementedError("voice is not supported in the MVP (501)")
        return Response(
            id=request.id,
            type="text",
            content=f"echo: {request.content}",
            metadata=ResponseMetadata(
                agentId=self.agent_id,
                sessionId=request.metadata.sessionId,
                toolCalls=[ToolCall(name="echo", arguments={"content": request.content})],
                toolResults=[ToolResult(name="echo", output=request.content)],
            ),
        )
