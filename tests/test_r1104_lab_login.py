"""R1104-CLI-BROWSER-LOGIN / R1104-LAB-SHARED-LOGIN-MODULE: shared lab_login module + real login flow.

The flow tests run the real CLI under a pty against a local mock API (no real keys, no
network): Enter opens the browser (a BROWSER stub records the URL), the pasted key is
hidden, verified with GET /v1/auth/me, and stored 0600. 401/403 fail closed.
"""
import fcntl
import json
import os
import pty
import termios
import select
import stat
import subprocess
import sys
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from tcadai_cli import _lab_login as ll

GOOD = "bz_live_GOODKEY1234567890"
CLI_DIR = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- module units
def test_can_open_browser_matrix():
    assert not ll.can_open_browser({"SSH_CONNECTION": "1 2 3 4"}, "darwin")
    assert not ll.can_open_browser({"SSH_TTY": "/dev/pts/1", "DISPLAY": ":0"}, "linux")
    assert not ll.can_open_browser({}, "linux")
    assert ll.can_open_browser({"DISPLAY": ":0"}, "linux")
    assert ll.can_open_browser({"WAYLAND_DISPLAY": "w0"}, "linux")
    assert ll.can_open_browser({}, "darwin") and ll.can_open_browser({}, "win32")


def test_open_key_page_non_interactive_is_silent():
    out, calls = [], []
    assert ll.open_key_page("https://x/y", interactive=False, out=out.append,
                            ask=lambda p: calls.append(p) or "", opener=lambda u: calls.append(u)) is False
    assert out == [] and calls == []


def test_open_key_page_headless_prints_url_no_prompt():
    out, calls = [], []
    r = ll.open_key_page("https://x/y", interactive=True, out=out.append,
                         ask=lambda p: calls.append(p) or "", opener=lambda u: calls.append(u),
                         env={"SSH_CONNECTION": "a"})
    assert r is False and calls == [] and "https://x/y" in "\n".join(out)


def test_open_key_page_enter_opens_browser():
    out, opened = [], []
    r = ll.open_key_page("https://x/y", interactive=True, out=out.append, ask=lambda p: "",
                         opener=lambda u: opened.append(u) or True, env={"DISPLAY": ":0"})
    assert r is True and opened == ["https://x/y"]


def test_open_key_page_opener_failure_prints_fallback():
    out = []
    def boom(u):
        raise RuntimeError("no display")
    r = ll.open_key_page("https://x/y", interactive=True, out=out.append, ask=lambda p: "",
                         opener=boom, env={"DISPLAY": ":0"})
    assert r is False and "https://x/y" in "\n".join(out)


def test_prompt_key_strips_and_rejects_empty():
    answers = iter(["", "  k1  "])
    assert ll.prompt_key(ask=lambda p: next(answers)) == "k1"
    with pytest.raises(ll.LoginError):
        ll.prompt_key(ask=lambda p: "  ", attempts=2)


@pytest.mark.parametrize("status,exc", [(401, ll.KeyRejected), (403, ll.KeyRejected),
                                        (500, ll.VerifyFailed), (404, ll.VerifyFailed)])
def test_verify_key_fails_closed(status, exc):
    with pytest.raises(exc) as e:
        ll.verify_key("SECRETKEY", lambda k: (status, {}))
    assert "SECRETKEY" not in str(e.value)


def test_verify_key_ok_returns_info():
    assert ll.verify_key("k", lambda k: (200, {"email": "a@b.c"})) == {"email": "a@b.c"}


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_write_private_file_is_0600_from_first_byte_and_dir_0700(tmp_path):
    p = tmp_path / "newdir" / "creds.json"
    ll.store_key(p, "KEY1", extra={"saved_at": 1})
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    ll.store_key(p, "KEY2")
    d = json.loads(p.read_text())
    assert d == {"api_key": "KEY2", "saved_at": 1}
    assert [f.name for f in p.parent.iterdir()] == ["creds.json"]  # no temp litter


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_config_save_never_world_readable_even_with_loose_umask(tmp_path):
    from unittest.mock import patch
    from tcadai_cli import config
    old = os.umask(0o000)
    try:
        d = tmp_path / ".tcadai"
        with patch.object(config, "CONFIG_DIR", d), patch.object(config, "CONFIG_FILE", d / "config.yaml"):
            config.set_api_key("SECRET")
            assert stat.S_IMODE((d / "config.yaml").stat().st_mode) == 0o600
            assert stat.S_IMODE(d.stat().st_mode) == 0o700
    finally:
        os.umask(old)


# ---------------------------------------------------------------- mock API + pty flow
class _H(BaseHTTPRequestHandler):
    mode = "ok"
    seen = []

    def do_GET(self):
        _H.seen.append((self.path, self.headers.get("Authorization")))
        if self.path != "/v1/auth/me":
            self.send_response(404); self.end_headers(); return
        good = self.headers.get("Authorization") == f"ApiKey {GOOD}"
        code = 200 if good else {"deny401": 401, "deny403": 403}.get(_H.mode, 401)
        if _H.mode == "deny403":
            code = 403
        body = json.dumps({"email": "dev@example.test"} if code == 200 else {"detail": "Invalid API key"}).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def api():
    _H.seen = []; _H.mode = "ok"
    srv = HTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _become_session_leader():
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _run_pty(args, env, script):
    """Run the CLI under a pty; ``script`` is a list of (wait_for_substring, send_text)."""
    mfd, sfd = pty.openpty()
    p = subprocess.Popen([sys.executable, "-m", "tcadai_cli.main"] + args, stdin=sfd, stdout=sfd,
                         stderr=sfd, env=env, cwd=str(CLI_DIR), close_fds=True,
                         preexec_fn=_become_session_leader)  # real controlling tty, like a user's terminal
    os.close(sfd)
    buf, steps, deadline = "", list(script), time.time() + 40
    while time.time() < deadline:
        r, _, _ = select.select([mfd], [], [], 0.2)
        if r:
            try:
                chunk = os.read(mfd, 4096).decode("utf-8", "replace")
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            if steps and steps[0][0] in buf:
                time.sleep(0.15); os.write(mfd, steps.pop(0)[1].encode())
        elif p.poll() is not None:
            break
    try:
        rc = p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill(); rc = -9
    os.close(mfd)
    return rc, buf


def _env(tmp_path, **extra):
    stub = tmp_path / "browser_stub.sh"
    stub.write_text("#!/bin/sh\necho \"$1\" >> %s/opened.txt\n" % tmp_path)
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SSH_", "TCADAI_", "BOLTZMANN_", "AHL_")) and k not in ("DISPLAY", "BROWSER")}
    env.update({"HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "DISPLAY": ":0",
                "BROWSER": f"{stub} %s", "PYTHONPATH": str(CLI_DIR), "TERM": "dumb"})
    env.update(extra)
    return env


@pytest.mark.skipif(os.name == "nt", reason="pty")
def test_pty_enter_opens_browser_paste_key_verifies_and_stores_0600(tmp_path, api):
    rc, out = _run_pty(["login", "--url", api], _env(tmp_path),
                       [("Press Enter", "\n"), ("API Key:", GOOD + "\n")])
    assert rc == 0, out
    assert GOOD not in out, "pasted key must not be echoed"
    assert "Authenticated as dev@example.test" in out
    assert (tmp_path / "opened.txt").read_text().strip() == "https://app.tcadai.com/account?tab=developers"
    cfg = tmp_path / ".tcadai" / "config.yaml"
    assert GOOD in cfg.read_text()
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
    assert ("/v1/auth/me", f"ApiKey {GOOD}") in _H.seen


@pytest.mark.skipif(os.name == "nt", reason="pty")
@pytest.mark.parametrize("mode,word", [("deny401", "rejected"), ("deny403", "rejected")])
def test_pty_rejected_key_fails_closed_and_keeps_old_key(tmp_path, api, mode, word):
    _H.mode = mode
    cfgdir = tmp_path / ".tcadai"; cfgdir.mkdir()
    (cfgdir / "config.yaml").write_text("api_key: OLDKEY\n")
    rc, out = _run_pty(["login", "--url", api], _env(tmp_path),
                       [("Press Enter", "\n"), ("API Key:", "bz_live_WRONG\n")])
    assert rc != 0, out
    assert word in out and "bz_live_WRONG" not in out
    import yaml
    saved = yaml.safe_load((cfgdir / "config.yaml").read_text())
    assert saved["api_key"] == "OLDKEY"  # (the background update-check may add its own timestamp)


@pytest.mark.skipif(os.name == "nt", reason="pty")
def test_pty_ssh_session_prints_url_and_never_launches_browser(tmp_path, api):
    rc, out = _run_pty(["login", "--url", api], _env(tmp_path, SSH_CONNECTION="1.2.3.4 5 6.7.8.9 22"),
                       [("API Key:", GOOD + "\n")])
    assert rc == 0, out
    assert "Press Enter" not in out and "account?tab=developers" in out
    assert not (tmp_path / "opened.txt").exists()


@pytest.mark.skipif(os.name == "nt", reason="pty")
def test_pty_warns_when_env_key_would_override_saved_key(tmp_path, api):
    rc, out = _run_pty(["login", "--url", api], _env(tmp_path, BOLTZMANN_API_KEY="from_env"),
                       [("Press Enter", "\n"), ("API Key:", GOOD + "\n")])
    assert rc == 0, out
    assert "BOLTZMANN_API_KEY" in out and "overrides" in out and "from_env" not in out


def test_non_tty_pipe_never_blocks_or_opens_browser(tmp_path, api):
    env = _env(tmp_path)
    r = subprocess.run([sys.executable, "-m", "tcadai_cli.main", "login", "--url", api],
                       input=GOOD + "\n", capture_output=True, text=True, env=env, cwd=str(CLI_DIR), timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "account?tab=developers" in r.stdout   # the instructions still show the link
    assert not (tmp_path / "opened.txt").exists()
