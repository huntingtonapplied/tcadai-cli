"""One shared error -> exit-code handler for every CLI command (BZ CLI-03 / U10).

Before this, each command caught AuthError/APIError, printed it and returned, so the
process exited 0 on 401, 404, 422 and 5xx and scripts could not tell failure from
success. Commands now call ``fail(exc)`` (or use ``handle_errors()``), which prints the
message to stderr and exits with the code from exit_codes.py.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import NoReturn, Optional

import click

from tcadai_cli.client import APIError, AuthError, NetworkError
from tcadai_cli.exit_codes import (
    EXIT_AUTH,
    EXIT_DUPLICATE,
    EXIT_GENERAL,
    EXIT_NETWORK,
    EXIT_NOT_FOUND,
    EXIT_SERVER,
    EXIT_VALIDATION,
)


def exit_code_for(exc: BaseException) -> int:
    """Map a client exception to a documented exit code."""
    if isinstance(exc, AuthError):
        return EXIT_AUTH
    if isinstance(exc, NetworkError):
        return EXIT_NETWORK
    if isinstance(exc, APIError):
        code = getattr(exc, "status_code", 0) or 0
        if code in (401, 403):
            return EXIT_AUTH
        if code == 404:
            return EXIT_NOT_FOUND
        if code == 409:
            return EXIT_DUPLICATE
        if code in (400, 422):
            return EXIT_VALIDATION
        if code == 429 or code >= 500:
            return EXIT_SERVER
        if code == 0:
            # Raised by the client when no HTTP response was received.
            return EXIT_NETWORK
    return EXIT_GENERAL


def fail(exc: BaseException, message: Optional[str] = None) -> NoReturn:
    """Print ``message`` (default: the exception text) to stderr and exit non-zero."""
    click.echo(message if message is not None else str(exc), err=True)
    sys.exit(exit_code_for(exc))


def fail_with(code: int, message: str) -> NoReturn:
    """Print ``message`` to stderr and exit with ``code`` (no exception involved)."""
    click.echo(message, err=True)
    sys.exit(code)


@contextmanager
def handle_errors():
    """``with handle_errors(): ...``: turn AuthError/APIError into a mapped exit."""
    try:
        yield
    except (AuthError, APIError) as e:
        fail(e)
