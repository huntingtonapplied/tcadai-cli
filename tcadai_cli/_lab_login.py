# VENDORED from latarence/coordination/launch/lab_login/lab_login.py sha256:45b31c84c441. Edit the source, then re-run vendor.sh.
# -*- coding: utf-8 -*-
"""lab_login: browser-assisted API-key sign-in for lab CLIs and engines (reference copy).

Canonical source: latarence/coordination/launch/lab_login/lab_login.py. Vendored (copied,
never imported across repos) by vendor.sh into each project as ``_lab_login.py``; keep
the copies byte-identical apart from the vendor header line.

Flow (needs no Auth0 / tenant change): print the product's API-keys page URL, open it in
the default browser after Enter (URL printed instead on SSH / headless / non-tty), read the
pasted key with hidden input, verify it against the hosted API (fail closed on 401/403 and
on any non-2xx), store it 0600 in the project's existing credentials file. The key is
never printed or logged.

Stdlib only; Python 3.8+.
"""
from __future__ import annotations

import getpass
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
import webbrowser
from typing import Callable, Mapping, Optional, Tuple

__all__ = [
    "can_open_browser", "open_key_page", "prompt_key", "http_verifier", "verify_key",
    "write_private_file", "store_key", "LoginError", "KeyRejected", "VerifyFailed",
]


class LoginError(Exception):
    """Base class; messages never contain the key."""


class KeyRejected(LoginError):
    """The API answered 401/403 for this key."""


class VerifyFailed(LoginError):
    """Verification could not complete (network, 5xx, malformed answer): fail closed."""


def is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def can_open_browser(env: Optional[Mapping[str, str]] = None, platform: Optional[str] = None) -> bool:
    """False over SSH and on a Linux box with no display; the caller then prints the URL."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if env.get("SSH_CONNECTION") or env.get("SSH_CLIENT") or env.get("SSH_TTY"):
        return False
    if platform.startswith("linux") and not (
        env.get("DISPLAY") or env.get("WAYLAND_DISPLAY") or env.get("BROWSER")
    ):
        return False
    return True


def open_key_page(
    url: str,
    *,
    interactive: Optional[bool] = None,
    out: Callable[[str], None] = print,
    ask: Callable[[str], str] = input,
    opener: Callable[[str], bool] = webbrowser.open,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """Show the key-page URL; at a terminal, open it after Enter. Returns True if a browser was launched.

    Non-interactive (pipe, CI): prints nothing and never blocks or launches anything.
    Headless (SSH, no display): prints the URL to open on any device; no Enter prompt.
    """
    if interactive is None:
        interactive = is_tty()
    if not interactive:
        return False
    if not can_open_browser(env):
        out("  No browser on this machine. Open this link on any device and sign in:\n    " + url)
        out("")
        return False
    try:
        ask("  Press Enter to open your browser (Ctrl+C to skip) ")
    except EOFError:
        return False
    try:
        opened = bool(opener(url))
    except Exception:
        opened = False
    if not opened:
        out("  Could not open a browser. Open this link on any device:\n    " + url)
    out("")
    return opened


def prompt_key(prompt: str = "  API key (input hidden): ", *, ask: Callable[[str], str] = getpass.getpass,
               attempts: int = 3) -> str:
    """Read the pasted key with hidden input; strips whitespace, re-asks on empty."""
    for _ in range(attempts):
        key = (ask(prompt) or "").strip()
        if key:
            return key
    raise LoginError("No key entered.")


def http_verifier(url: str, *, scheme: str = "ApiKey", timeout: float = 15.0,
                  opener: Optional[Callable] = None) -> Callable[[str], Tuple[int, dict]]:
    """Build a verifier callback: GET ``url`` with ``Authorization: <scheme> <key>`` -> (status, json)."""
    open_fn = opener or urllib.request.urlopen

    def _verify(key: str) -> Tuple[int, dict]:
        req = urllib.request.Request(url, headers={"Authorization": f"{scheme} {key}",
                                                   "Accept": "application/json"})
        try:
            with open_fn(req, timeout=timeout) as resp:
                status = resp.getcode()
                body = resp.read(1 << 20)
        except urllib.error.HTTPError as e:
            return e.code, {}
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise VerifyFailed("Could not reach the API: %s" % type(e).__name__)
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except ValueError:
            data = {}
        return status, data if isinstance(data, dict) else {}

    return _verify


def verify_key(key: str, verifier: Callable[[str], Tuple[int, dict]]) -> dict:
    """Run the project's verifier. 2xx -> returned info dict. 401/403 -> KeyRejected. Else VerifyFailed."""
    status, info = verifier(key)
    if 200 <= status < 300:
        return info
    if status in (401, 403):
        raise KeyRejected("The API rejected this key (HTTP %d)." % status)
    raise VerifyFailed("The API could not verify this key (HTTP %d)." % status)


def write_private_file(path, text: str) -> None:
    """Write ``text`` to ``path`` readable only by the owner from the first byte (no 0644 window).

    Temp file in the same directory created 0600, then atomically renamed; the parent
    directory is created 0700 when missing. On Windows the mode bits are advisory.
    """
    path = os.fspath(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)  # mkstemp creates 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def store_key(path, key: str, *, field: str = "api_key", extra: Optional[dict] = None) -> None:
    """Merge ``{field: key, **extra}`` into the JSON credentials file at ``path`` (0600)."""
    data: dict = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        pass
    data[field] = key
    data.update(extra or {})
    write_private_file(path, json.dumps(data, indent=2) + "\n")
