# SPDX-License-Identifier: LGPL-2.1-or-later
"""Handler registry for the worker.

Decorate a function with ``@handler("method_name")`` to register it; the
server's dispatch loop will invoke it with the request's ``params`` dict as
keyword arguments and return the value as ``result``.

Handlers may be sync or async. Keep the dispatch table module-local so tests
can reset it in isolation via :func:`clear`.
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Union

Handler = Callable[..., Union[Any, Awaitable[Any]]]

_HANDLERS: dict[str, Handler] = {}


def handler(method: str) -> Callable[[Handler], Handler]:
    """Register ``fn`` under ``method``. Re-registration overwrites."""

    def decorate(fn: Handler) -> Handler:
        _HANDLERS[method] = fn
        return fn

    return decorate


def get(method: str) -> Handler | None:
    return _HANDLERS.get(method)


def methods() -> list[str]:
    return sorted(_HANDLERS)


def clear() -> None:
    """Drop every registered handler. Tests only."""
    _HANDLERS.clear()


class UnknownMethod(LookupError):
    """Raised when ``dispatch`` is asked for a method that isn't registered.

    Distinct from the ``KeyError`` a handler may raise for a missing
    document/object — the server reports those two cases differently."""


async def dispatch(method: str, params: dict[str, Any]) -> Any:
    """Look up ``method`` and invoke it with ``**params``.

    Raises :class:`UnknownMethod` if the method is unknown — the server
    turns that into a structured error response. Handler-raised KeyError
    propagates as a normal handler error (e.g. "no such object").
    """
    fn = _HANDLERS.get(method)
    if fn is None:
        raise UnknownMethod(method)
    result = fn(**params)
    if inspect.isawaitable(result):
        result = await result
    return result
