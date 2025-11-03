"""Automation sessions for python-cdpctl."""

import nox

nox.options.sessions = ["tests"]


@nox.session(python=["3.11"])
def tests(session: nox.Session) -> None:
    """Run the test suite."""
    session.install("pytest>=8.0")
    session.install(".")
    session.run("pytest", "--maxfail=1", "--disable-warnings")
