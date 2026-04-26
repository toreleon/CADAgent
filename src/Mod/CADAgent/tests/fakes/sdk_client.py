"""Scriptable fake of `claude_agent_sdk.ClaudeSDKClient`.

Real SDK message/block types are reused (they're plain dataclasses), so
assertions can use `isinstance(b, TextBlock)` etc. — only the network-touching
client is faked.

Usage:

    script = [
        [TextBlock(text="hello")],
        [ToolUseBlock(id="t1", name="Read", input={"path": "/tmp/x"})],
        ResultMessage(...),
    ]
    fake = FakeSDKClient(script)
    async with fake:
        await fake.query("hi")
        async for msg in fake.receive_response():
            ...
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ContentBlock,
    Message,
    ResultMessage,
)


class FakeSDKClient:
    """Drop-in replacement for `ClaudeSDKClient` in tests.

    `script` is a list whose items are either:
      - a list of ContentBlock (rendered as one AssistantMessage), or
      - a Message subclass instance (yielded as-is — useful for ResultMessage).

    The script is consumed once per `query()` call; provide one entry (or one
    sub-script) per turn. For multi-turn tests, pass a list of scripts and call
    `next_turn()` between turns, OR simply call `query()` repeatedly with the
    flat script segmented by `ResultMessage`s.
    """

    def __init__(self, script: list[Any] | None = None, *, options: Any = None) -> None:
        self._script: list[Any] = list(script or [])
        self._options = options
        self.queries: list[str | list[Any]] = []
        self.entered = False
        self.closed = False
        self.session_id: str | None = "fake-session-0001"

    # --- async context manager ---
    async def __aenter__(self) -> "FakeSDKClient":
        self.entered = True
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.closed = True

    # --- public surface mirroring ClaudeSDKClient ---
    async def query(self, prompt: str | list[Any]) -> None:
        self.queries.append(prompt)

    async def receive_response(self) -> AsyncIterator[Message]:
        # Drain the script until (and including) the next ResultMessage, or
        # until the script is exhausted.
        while self._script:
            item = self._script.pop(0)
            if isinstance(item, Message):
                yield item
                if isinstance(item, ResultMessage):
                    return
                continue
            if isinstance(item, list):
                yield AssistantMessage(content=item, model="fake-model", parent_tool_use_id=None)
                continue
            raise TypeError(f"FakeSDKClient script item not understood: {type(item)!r}")

    async def interrupt(self) -> None:
        return None


def make_result(
    *,
    session_id: str = "fake-session-0001",
    duration_ms: int = 10,
    duration_api_ms: int = 5,
    is_error: bool = False,
    num_turns: int = 1,
    total_cost_usd: float = 0.0,
) -> ResultMessage:
    """Convenience factory for terminal `ResultMessage` rows in scripts."""
    return ResultMessage(
        subtype="success" if not is_error else "error",
        duration_ms=duration_ms,
        duration_api_ms=duration_api_ms,
        is_error=is_error,
        num_turns=num_turns,
        session_id=session_id,
        total_cost_usd=total_cost_usd,
        usage=None,
        result=None,
    )
