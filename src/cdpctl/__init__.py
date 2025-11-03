"""Public entry point for the :mod:`cdpctl` package.

The :mod:`cdpctl` package primarily exposes an asynchronous Chrome DevTools
Protocol (CDP) client alongside a convenient command-line interface. Re-export
the key building blocks here so users can ``import cdpctl`` and immediately
reach for the HTTP helpers, websocket client, and CLI entry points without
digging through internal modules.
"""

from __future__ import annotations

from .core import (
    BooleanOptionalAction,
    CdpClient,
    HttpClient,
    TargetInfo,
    main,
    main_async,
)

__all__ = [
    "BooleanOptionalAction",
    "CdpClient",
    "HttpClient",
    "TargetInfo",
    "main",
    "main_async",
]
