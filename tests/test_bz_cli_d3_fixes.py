"""Regression pins for the BZ pre-launch CLIENTS review (D3 cli lane, 2026-10-24).

Rows: CLI-01, CLI-02, CLI-03 + KNOWN-U10, CLI-04, CLI-05, CLI-06, KNOWN-API-PREFIX, A13b.
Every test here is hermetic (no network): HTTP is mocked, the installer runs against
file:// fixtures with shimmed `uname` and `curl`.
"""

import json
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import yaml

from tcadai_cli.main import cli
from tcadai_cli.client import AuthError, APIError

CLI_DIR = Path(__file__).resolve().parent.parent
SOL = "11111111-1111-1111-1111-111111111111"
PRJ = "22222222-2222-2222-2222-222222222222"


def _client(**get_or_post):
    c = MagicMock()
    c.api_key = "test-key-123"
    c.token = None
    c.api_url = "http://localhost:8009"
    for k, v in get_or_post.items():
        setattr(getattr(c, k), "side_effect" if isinstance(v, Exception) else "return_value", v)
    return c


def _invoke(runner, args, client):
    with patch("tcadai_cli.client.BoltzmannClient", return_value=client):
        return runner.invoke(cli, args)


# ─── CLI-01: simulations create sends solution_id / project_id ───────────────

class TestCli01SimulationsCreate:
    def test_ids_sent(self, runner, tmp_config):
        c = _client(post={"id": "sim-abc"})
        r = _invoke(runner, ["simulations", "create", "dev1", "--solution-id", SOL, "--project-id", PRJ], c)
        assert r.exit_code == 0, r.output
        path, = c.post.call_args.args[:1]
        payload = c.post.call_args.kwargs.get("data") or c.post.call_args.args[1]
        assert path == "/v1/simulations"
        assert payload["solution_id"] == SOL and payload["project_id"] == PRJ
        assert payload["name"] == "dev1"
        assert "sim-abc" in r.output

    def test_short_aliases(self, runner, tmp_config):
        c = _client(post={"id": "sim-abc"})
        r = _invoke(runner, ["simulations", "create", "dev1", "--solution", SOL, "--project", PRJ], c)
        assert r.exit_code == 0, r.output

    def test_ids_from_config_file(self, runner, tmp_config, tmp_path):
        cfg = tmp_path / "sim.json"
        cfg.write_text(json.dumps({"solution_id": SOL, "project_id": PRJ, "description": "d"}))
        c = _client(post={"id": "sim-abc"})
        r = _invoke(runner, ["simulations", "create", "dev1", "--config", str(cfg)], c)
        assert r.exit_code == 0, r.output
        payload = c.post.call_args.kwargs.get("data") or c.post.call_args.args[1]
        assert payload["solution_id"] == SOL and payload["project_id"] == PRJ
        assert payload["description"] == "d"

    def test_missing_ids_is_validation_error_without_request(self, runner, tmp_config):
        c = _client(post={"id": "x"})
        r = _invoke(runner, ["simulations", "create", "dev1", "--type", "electromagnetic"], c)
        assert r.exit_code == 4, r.output
        assert "--solution-id" in r.output and "--project-id" in r.output
        c.post.assert_not_called()

    def test_type_option_kept(self, runner, tmp_config):
        c = _client(post={"id": "sim-abc"})
        r = _invoke(runner, ["simulations", "create", "dev1", "--type", "thermal",
                             "--solution-id", SOL, "--project-id", PRJ], c)
        assert r.exit_code == 0, r.output


# ─── CLI-02: jobs list ────────────────────────────────────────────────────────

class TestCli02JobsList:
    def test_missing_route_gives_clear_message_and_nonzero(self, runner, tmp_config):
        c = _client(get=APIError("API error 404: Not Found\n  Resource not found — check the ID.", 404))
        r = _invoke(runner, ["jobs", "list"], c)
        assert r.exit_code != 0
        assert "check the ID" not in r.output
        assert "tcadai jobs status" in r.output

    def test_list_still_renders_when_server_has_route(self, runner, tmp_config):
        c = _client(get=[{"job_id": "job-1234abcd", "status": "RUNNING", "job_type": "sweep"}])
        r = _invoke(runner, ["jobs", "list"], c)
        assert r.exit_code == 0, r.output
        assert "RUNNING" in r.output and "job-1234" in r.output

    def test_status_reads_backend_field_names(self, runner, tmp_config):
        c = _client(get={"job_id": "j-1", "job_type": "fdtd", "status": "RUNNING",
                         "progress": 40, "error_message": None})
        r = _invoke(runner, ["jobs", "status", "j-1"], c)
        assert r.exit_code == 0, r.output
        assert "fdtd" in r.output and "unknown" not in r.output


# ─── CLI-03: errors map to non-zero exit codes ───────────────────────────────

ERRORS = [
    (AuthError("Not authenticated."), 2),
    (APIError("API error 403: forbidden", 403), 2),
    (APIError("API error 404: nope", 404), 3),
    (APIError("API error 422: bad", 422), 4),
    (APIError("API error 409: dup", 409), 7),
    (APIError("API error 500: boom", 500), 6),
    (APIError("API error 503: down", 503), 6),
]
COMMANDS = [
    (["simulations", "list"], "get"),
    (["simulations", "status", "s1"], "get"),
    (["simulations", "stop", "s1"], "post"),
    (["simulations", "create", "n", "--solution-id", SOL, "--project-id", PRJ], "post"),
    (["projects", "list"], "get"),
    (["projects", "create", "p"], "post"),
    (["jobs", "status", "j1"], "get"),
    (["auth", "status"], "get"),
    (["api-keys", "list"], "get"),
    (["api-keys", "stats"], "get"),
    (["api-keys", "rotate", "k1"], "post"),
]


class TestCli03ExitCodes:
    @pytest.mark.parametrize("args,meth", COMMANDS)
    @pytest.mark.parametrize("err,code", ERRORS)
    def test_error_exit_code(self, runner, tmp_config, args, meth, err, code):
        c = _client(**{meth: err})
        r = _invoke(runner, args, c)
        assert r.exit_code == code, (args, err, r.output)

    def test_network_error_exit_5(self, runner, tmp_config):
        with patch("tcadai_cli.client.MAX_RETRIES", 0), \
             patch("tcadai_cli.client.httpx.request", side_effect=httpx.ConnectError("refused")):
            r = runner.invoke(cli, ["simulations", "list"], env={"BOLTZMANN_API_KEY": "k"})
        assert r.exit_code == 5, r.output

    def test_auth_status_without_credentials_exits_auth(self, runner, tmp_config):
        c = _client()
        c.api_key = None
        r = _invoke(runner, ["auth", "status"], c)
        assert r.exit_code == 2

    def test_api_keys_without_credentials_exits_auth(self, runner, tmp_config):
        c = _client()
        c.api_key = None
        r = _invoke(runner, ["api-keys", "list"], c)
        assert r.exit_code == 2

    def test_config_validate_failure_nonzero(self, runner, tmp_config):
        with patch("tcadai_cli.commands.config.httpx.get", side_effect=httpx.ConnectError("x")):
            r = runner.invoke(cli, ["config", "validate"])
        assert r.exit_code == 5

    def test_success_still_exit_0(self, runner, tmp_config):
        c = _client(get=[{"id": "s-1", "name": "ok"}])
        r = _invoke(runner, ["simulations", "list"], c)
        assert r.exit_code == 0


# ─── KNOWN-U10: login --key verifies before saving ───────────────────────────

class TestU10LoginVerifyFirst:
    @pytest.mark.parametrize("err,code", [
        (AuthError("Not authenticated."), 2),
        (APIError("Connection failed: refused"), 5),
        (APIError("API error 500", 500), 6),
    ])
    def test_bad_key_not_saved_nonzero(self, runner, tmp_config, err, code):
        m = MagicMock()
        m.get.side_effect = err
        with patch("tcadai_cli.commands.login.BoltzmannClient", return_value=m):
            r = runner.invoke(cli, ["login", "--key", "bz_live_badkey_123"])
        assert r.exit_code == code, r.output
        assert "saved" not in r.output.lower().replace("not saved", "")
        assert not tmp_config.exists() or "bz_live_badkey_123" not in tmp_config.read_text()

    def test_good_key_saved_after_verify(self, runner, tmp_config):
        m = MagicMock()
        m.get.return_value = {"email": "u@example.com"}
        with patch("tcadai_cli.commands.login.BoltzmannClient", return_value=m):
            r = runner.invoke(cli, ["login", "--key", "bz_live_goodkey"])
        assert r.exit_code == 0, r.output
        assert "bz_live_goodkey" in tmp_config.read_text()
        assert "Authenticated as u@example.com" in r.output

    def test_bad_key_keeps_previous_key(self, runner, tmp_config):
        from tcadai_cli.config import set_api_key
        set_api_key("bz_live_previous")
        m = MagicMock()
        m.get.side_effect = AuthError("Not authenticated.")
        with patch("tcadai_cli.commands.login.BoltzmannClient", return_value=m):
            r = runner.invoke(cli, ["login", "--key", "bz_live_typo"])
        assert r.exit_code == 2
        assert "bz_live_previous" in tmp_config.read_text()
        assert "bz_live_typo" not in tmp_config.read_text()


# ─── CLI-04: -o json|yaml honoured ───────────────────────────────────────────

STRUCT = [
    (["simulations", "list"], [{"id": "s-1", "name": "a", "status": "draft"}]),
    (["simulations", "status", "s-1"], {"id": "s-1", "name": "a", "status": "running", "progress": 5}),
    (["projects", "list"], [{"id": "p-1", "name": "P"}]),
    (["jobs", "list"], [{"job_id": "j-1", "status": "RUNNING"}]),
    (["jobs", "status", "j-1"], {"job_id": "j-1", "status": "RUNNING"}),
    (["auth", "status"], {"email": "u@example.com", "sub": "u1"}),
    (["api-keys", "list"], [{"id": "k-1", "name": "ci"}]),
    (["api-keys", "stats"], {"total_keys": 3}),
]


class TestCli04StructuredOutput:
    @pytest.mark.parametrize("args,data", STRUCT)
    def test_json(self, runner, tmp_config, args, data):
        c = _client(get=data)
        r = _invoke(runner, ["-o", "json"] + args, c)
        assert r.exit_code == 0, r.output
        parsed = json.loads(r.stdout)
        if args[-1] == "status" and args[0] == "auth":
            assert parsed["email"] == "u@example.com"
        else:
            assert parsed == data

    @pytest.mark.parametrize("args,data", STRUCT)
    def test_yaml(self, runner, tmp_config, args, data):
        c = _client(get=data)
        r = _invoke(runner, ["-o", "yaml"] + args, c)
        assert r.exit_code == 0, r.output
        parsed = yaml.safe_load(r.stdout)
        if args[-1] == "status" and args[0] == "auth":
            assert parsed["email"] == "u@example.com"
        else:
            assert parsed == data

    def test_json_empty_list_is_json(self, runner, tmp_config):
        c = _client(get=[])
        r = _invoke(runner, ["-o", "json", "simulations", "list"], c)
        assert json.loads(r.stdout) == []

    def test_table_default_unchanged(self, runner, tmp_config):
        c = _client(get=[{"id": "s-1234abcd", "name": "Sim One", "status": "running"}])
        r = _invoke(runner, ["simulations", "list"], c)
        assert "Sim One" in r.output and "ID" in r.output


# ─── CLI-05: projects list --visibility → is_public ──────────────────────────

class TestCli05Visibility:
    def _params(self, c):
        return c.get.call_args.kwargs.get("params") or c.get.call_args.args[1]

    def test_public(self, runner, tmp_config):
        c = _client(get=[])
        r = _invoke(runner, ["projects", "list", "--visibility", "public"], c)
        assert r.exit_code == 0, r.output
        p = self._params(c)
        assert "visibility" not in p
        assert p["is_public"] in (True, "true") and p["include_public"] in (True, "true")

    def test_private(self, runner, tmp_config):
        c = _client(get=[])
        r = _invoke(runner, ["projects", "list", "--visibility", "private"], c)
        assert r.exit_code == 0, r.output
        p = self._params(c)
        assert "visibility" not in p
        assert p["is_public"] in (False, "false")

    def test_none(self, runner, tmp_config):
        c = _client(get=[])
        _invoke(runner, ["projects", "list"], c)
        p = self._params(c)
        assert "is_public" not in p and "visibility" not in p


# ─── KNOWN-API-PREFIX: auth token ────────────────────────────────────────────

class TestApiPrefixAuthToken:
    def test_command_kept_and_points_to_api_key(self, runner, tmp_config):
        with patch("httpx.post") as post:
            r = runner.invoke(cli, ["auth", "token", "--email", "a@b.c", "--password", "pw"])
        assert r.exit_code == 2, r.output
        assert "tcadai login --key" in r.output
        for call in post.call_args_list:
            assert "/v1/auth/login" not in str(call)

    def test_no_password_prompt(self, runner, tmp_config):
        r = runner.invoke(cli, ["auth", "token"], input="")
        assert r.exit_code == 2, r.output
        assert "tcadai login --key" in r.output

    def test_listed_in_help(self, runner):
        r = runner.invoke(cli, ["auth", "--help"])
        assert "token" in r.output


# ─── A13b: upgrade text points at the binary installer, not pip ──────────────

class TestA13bUpgradeText:
    def test_notice_uses_installer(self, capsys):
        from tcadai_cli import update_check
        uc = update_check.UpdateChecker()
        uc.latest_version = "99.0.0"
        with patch.object(update_check, "__version__", "1.0.3"):
            uc.notify_if_outdated()
        err = capsys.readouterr().err
        assert "99.0.0" in err
        assert "downloads.tcadai.com/cli/install.sh" in err
        assert "pip install" not in err

    def test_no_pip_install_in_shipped_strings(self):
        src = (CLI_DIR / "tcadai_cli").rglob("*.py")
        for f in src:
            text = f.read_text()
            assert "pip install --upgrade" not in text, f
            assert "pip install tcadai" not in text, f


# ─── CLI-06: installer rejects unpublished platforms clearly ─────────────────

def _shim(dirpath: Path, name: str, body: str):
    p = dirpath / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def install_env(tmp_path):
    rel = tmp_path / "srv" / "cli" / "releases" / "latest"
    rel.mkdir(parents=True)
    import hashlib
    lines = []
    for asset in ("tcadai-darwin-arm64", "tcadai-linux-x86_64"):
        f = rel / asset
        f.write_text("#!/bin/sh\necho tcadai 0.0.0-test\n")
        f.chmod(0o755)
        lines.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {asset}")
    (rel / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    shims = tmp_path / "shims"
    shims.mkdir()
    # curl shim: file:// only, mimics `curl -fsSL URL -o OUT` (exit 22 + curl's message on missing).
    _shim(shims, "curl", r'''
url=""; out=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; -*) shift;; *) url="$1"; shift;; esac; done
path="${url#file://}"
if [ ! -f "$path" ]; then echo "curl: (22) The requested URL returned error: 404" >&2; exit 22; fi
if [ -n "$out" ]; then cp "$path" "$out"; else cat "$path"; fi
''')
    return tmp_path, shims


def _run_installer(tmp_path, shims, s, m):
    _shim(shims, "uname", f'case "$1" in -s) echo {s};; -m) echo {m};; *) echo {s};; esac\n')
    env = {"PATH": f"{shims}:/usr/bin:/bin", "HOME": str(tmp_path / "home")}
    return subprocess.run(
        ["bash", str(CLI_DIR / "install.sh"), "--base-url", f"file://{tmp_path}/srv",
         "--install-dir", str(tmp_path / "bin"), "--no-modify-path"],
        env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
    )


class TestCli06Installer:
    @pytest.mark.parametrize("s,m", [("Darwin", "x86_64"), ("Linux", "aarch64"), ("Linux", "arm64")])
    def test_unpublished_platform_clear_message(self, install_env, s, m):
        tmp_path, shims = install_env
        r = _run_installer(tmp_path, shims, s, m)
        out = r.stdout + r.stderr
        assert r.returncode != 0
        assert "curl: (22)" not in out
        assert "nsupported platform" in out
        assert "darwin-arm64" in out and "linux-x86_64" in out
        assert not (tmp_path / "bin" / "tcadai").exists()

    @pytest.mark.parametrize("s,m", [("Darwin", "arm64"), ("Linux", "x86_64")])
    def test_published_platform_installs(self, install_env, s, m):
        tmp_path, shims = install_env
        r = _run_installer(tmp_path, shims, s, m)
        assert r.returncode == 0, r.stdout + r.stderr
        assert (tmp_path / "bin" / "tcadai").exists()

    def test_unknown_version_clear_message(self, install_env):
        tmp_path, shims = install_env
        _shim(shims, "uname", 'case "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n')
        env = {"PATH": f"{shims}:/usr/bin:/bin", "HOME": str(tmp_path / "home")}
        r = subprocess.run(
            ["bash", str(CLI_DIR / "install.sh"), "--base-url", f"file://{tmp_path}/srv",
             "--install-dir", str(tmp_path / "bin"), "--no-modify-path", "--version", "9.9.9"],
            env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        out = r.stdout + r.stderr
        assert r.returncode != 0
        assert "curl: (22)" not in out
        assert "9.9.9" in out
