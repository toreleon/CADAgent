# SPDX-License-Identifier: LGPL-2.1-or-later
"""Multimodal user-prompt assembly: text + image attachments.

Encodes attachments as Anthropic-format streaming user messages;
LiteLLM translates the image block to whatever the proxied model
expects (e.g. OpenAI ``image_url`` for ``gpt-*``). The single yield is
fed to ``ClaudeSDKClient.query``.
"""

from __future__ import annotations

import base64
import mimetypes
from typing import Any


async def multimodal_prompt(user_text: str, attachments: list[str]):
    """Yield a single Anthropic-format streaming user message with images."""
    content: list[dict[str, Any]] = []
    if user_text:
        content.append({"type": "text", "text": user_text})
    for path in attachments:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        mime, _ = mimetypes.guess_type(path)
        if not mime or not mime.startswith("image/"):
            mime = "image/png"
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            }
        )
    yield {
        "type": "user",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
    }


__all__ = ["multimodal_prompt"]
