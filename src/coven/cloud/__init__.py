"""Coven Cloud package.

`app` is exposed lazily so importing `coven.cloud.store` (or any other submodule)
does not pull FastAPI in — useful in tests and in the relay, which only ever
talks HTTP to this package from a distance.
"""

from __future__ import annotations

from typing import Any

__all__ = ["app"]


def __getattr__(name: str) -> Any:
    if name == "app":
        from .app import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
