# SPDX-License-Identifier: LGPL-2.1-or-later
"""Wire protocol for the CAD worker.

Newline-delimited JSON over stdio, UTF-8, one message per line. A message is
either a Request or a Response; ``id`` correlates the two. No batching, no
notifications — keep it boring.

Request:  {"id": <int>, "method": <str>, "params": <dict>}
Response: {"id": <int>, "result": <any>}          on success
          {"id": <int>, "error":  <str>}          on failure

``id`` is echoed verbatim. ``params`` defaults to ``{}`` if omitted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Request:
    id: int
    method: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, line: str) -> "Request":
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise ValueError("request must be a JSON object")
        if "id" not in obj or "method" not in obj:
            raise ValueError("request missing 'id' or 'method'")
        params = obj.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("'params' must be an object")
        return cls(id=int(obj["id"]), method=str(obj["method"]), params=params)


@dataclass
class Response:
    id: int
    result: Any = None
    error: str | None = None

    def to_json(self) -> str:
        if self.error is not None:
            payload: dict[str, Any] = {"id": self.id, "error": self.error}
        else:
            payload = {"id": self.id, "result": self.result}
        return json.dumps(payload, default=str)


def ok(req_id: int, result: Any) -> Response:
    return Response(id=req_id, result=result)


def err(req_id: int, message: str) -> Response:
    return Response(id=req_id, error=message)
