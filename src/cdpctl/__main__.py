"""Support ``python -m cdpctl`` by delegating to :func:`cdpctl.core.main`."""

from __future__ import annotations

import sys
from typing import Sequence

from . import core as _core


def main(argv: Sequence[str] | None = None) -> int:
    """Run the :mod:`cdpctl` command-line interface.

    Parameters
    ----------
    argv:
        Optional iterable of command-line arguments. When *None* (the default),
        :data:`sys.argv` is used so executing ``python -m cdpctl`` behaves the
        same as invoking the ``cdpctl`` console script.
    """

    # ``cdpctl.core.main`` already accepts an optional argument vector, so we
    # simply forward the value through. Accepting ``Sequence`` makes the helper
    # test-friendly without constraining the caller to pass a mutable list.
    if argv is None:
        argv = sys.argv[1:]
    return _core.main(list(argv))


if __name__ == "__main__":  # pragma: no cover - exercised via CLI usage
    raise SystemExit(main())
