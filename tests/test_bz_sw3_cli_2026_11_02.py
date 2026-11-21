"""Regression pins for the TCAD AI CLI, sw3-cli lane (2026-11-02).

Rows: BZC-190 (HQ2-API-PREFIX: a base URL ending in /v1 gave /v1/v1/... 404s; login
rejected-key message), BZC-191 (auth token is by design unsupported; message stays honest),
BZC-192..195 (api-keys / simulations / projects / jobs command coverage), BZC-197 (CLI-04:
-o json|yaml on every command, including the api-keys mutations, config validate and doctor),
BZC-198 (version sync so a republished binary is distinguishable; update-check compare),
BZC-044 (the /developers/cli reference mirrors the shipped command tree), and the no-em-dash
rule for public copy. Hermetic: HTTP is mocked, nothing touches ~/.tcadai.
"""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import yaml

from tcadai_cli.main import cli
from tcadai_cli.client import BoltzmannClient, AuthError, APIError

CLI_DIR = Path(__file__).resolve().parent.parent
REPO = CLI_DIR.parent
DEV_HUB = REPO / "frontend" / "landing_app" / "src" / "components" / "Pages" / "Developers"


def _client(**attrs):
    c = MagicMock()
    c.api_key = "test-key-123"
    c.token = None
    c.api_url = "http://localhost:8009"
    for k, v in attrs.items():
        setattr(getattr(c, k), "side_effect" if isinstance(v, Exception) else "return_value", v)
    return c


def _invoke(runner, args, client, **kw):
    with patch("tcadai_cli.client.BoltzmannClient", return_value=client):
        return runner.invoke(cli, args, **kw)


def _resp(status, body=None, text=""):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.text = text
    r.content = b"x" if body is not None else b""
    r.json.return_value = body if body is not None else {}
    if body is None:
        r.json.side_effect = ValueError("no body")
    return r


# ─── BZC-190 / HQ2-API-PREFIX: trailing /v1 on the base URL ──────────────────

class TestApiPrefixBaseUrl:
    @pytest.mark.parametrize("given,want", [
        ("https://api.tcadai.com", "https://api.tcadai.com"),
        ("https://api.tcadai.com/", "https://api.tcadai.com"),
        ("https://api.tcadai.com/v1", "https://api.tcadai.com"),
        ("https://api.tcadai.com/v1/", "https://api.tcadai.com"),
        (" http://localhost:8009/v1 ", "http://localhost:8009"),
        ("https://proxy.example/tcadai", "https://proxy.example/tcadai"),
        ("https://proxy.example/tcadai/v1", "https://proxy.example/tcadai"),
    ])
    def test_normalize_api_url(self, given, want):
        from tcadai_cli.config import normalize_api_url
        assert normalize_api_url(given) == want

    @patch("tcadai_cli.client.httpx.request")
    def test_client_never_requests_v1_v1(self, mock_request):
        mock_request.return_value = _resp(200, {"email": "u@x"})
        BoltzmannClient("https://api.tcadai.com/v1", api_key="k").get("/v1/auth/me")
        url = mock_request.call_args.args[1]
        assert url == "https://api.tcadai.com/v1/auth/me"
        assert "/v1/v1" not in url

    def test_env_base_url_with_v1_is_normalized(self, tmp_config, monkeypatch):
        from tcadai_cli.config import get_api_url
        monkeypatch.setenv("BOLTZMANN_API_URL", "https://api.tcadai.com/v1")
        assert get_api_url() == "https://api.tcadai.com"

    def test_validate_config_warns_on_trailing_v1(self):
        from tcadai_cli.config import validate_config
        warnings = validate_config({"api_url": "https://api.tcadai.com/v1"})
        assert any("/v1" in w for w in warnings)
        assert validate_config({"api_url": "https://api.tcadai.com"}) == []

    @patch("tcadai_cli.client.httpx.request")
    def test_login_url_with_v1_verifies_at_the_origin(self, mock_request, runner, tmp_config):
        mock_request.return_value = _resp(200, {"email": "u@x"})
        result = runner.invoke(cli, ["login", "--key", "bz_live_k", "--url", "https://api.example/v1"])
        assert result.exit_code == 0, result.output
        assert mock_request.call_args.args[1] == "https://api.example/v1/auth/me"
        assert "Authenticated as u@x" in result.output


# ─── BZC-190 / CLI-03: a rejected key is reported as such, not as "run: tcadai login" ─

class TestLoginRejectedKey:
    @patch("tcadai_cli.client.httpx.request")
    def test_401_detail_is_shown_and_key_not_saved(self, mock_request, runner, tmp_config):
        mock_request.return_value = _resp(
            401, {"detail": {"code": "invalid_api_key", "description": "Invalid API key"}})
        result = runner.invoke(cli, ["login", "--key", "bz_live_bad"])
        assert result.exit_code == 2
        assert "Invalid API key" in result.output
        assert "rejected this key" in result.output
        assert "run: tcadai login" not in result.output
        assert not tmp_config.exists()

    def test_auth_error_text_carries_server_reason(self):
        c = BoltzmannClient("http://x", api_key="k")
        with pytest.raises(AuthError, match=r"Not authenticated \(Invalid API key\)"):
            c._handle(_resp(401, {"detail": {"code": "invalid_api_key", "description": "Invalid API key"}}))
        with pytest.raises(AuthError, match=r"Not authenticated \(Missing authorization header\)"):
            c._handle(_resp(401, {"detail": "Missing authorization header"}))
        with pytest.raises(AuthError, match=r"^Not authenticated\."):
            c._handle(_resp(401))

    def test_dict_detail_rendered_for_other_errors(self):
        c = BoltzmannClient("http://x", api_key="k")
        with pytest.raises(APIError, match="Project missing"):
            c._handle(_resp(422, {"detail": {"code": "x", "description": "Project missing"}}))


# ─── BZC-191: auth token is unsupported BY DESIGN; the message stays honest ─────

class TestAuthTokenByDesign:
    @patch("tcadai_cli.client.httpx.request")
    def test_exits_2_with_api_key_guidance_and_no_http(self, mock_request, runner, tmp_config):
        result = runner.invoke(cli, ["auth", "token", "--email", "a@b", "--password", "p"])
        assert result.exit_code == 2
        assert "not supported" in result.output
        assert "tcadai login --key" in result.output
        assert "404" not in result.output
        mock_request.assert_not_called()

    def test_help_says_unsupported(self, runner):
        result = runner.invoke(cli, ["auth", "token", "--help"])
        assert result.exit_code == 0
        assert "not supported" in result.output


# ─── BZC-197 / CLI-04: -o json|yaml on the api-keys mutations, config validate, doctor ─

KEY = {"id": "k1", "name": "ci", "key_prefix": "bz_live_", "key": "bz_live_SECRET"}


class TestStructuredOutputEverywhere:
    def test_api_keys_create_json_prints_response_and_never_prompts(self, runner, tmp_config):
        c = _client(post=KEY)
        with patch("tcadai_cli.commands.api_keys.click.confirm", side_effect=AssertionError("prompted")), \
             patch("tcadai_cli.commands.api_keys._interactive", return_value=True):
            result = _invoke(runner, ["-o", "json", "api-keys", "create", "ci"], c)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == KEY

    def test_api_keys_rotate_yaml(self, runner, tmp_config):
        result = _invoke(runner, ["-o", "yaml", "api-keys", "rotate", "k1"], _client(post=KEY))
        assert result.exit_code == 0, result.output
        assert yaml.safe_load(result.output) == KEY

    def test_api_keys_update_json(self, runner, tmp_config):
        c = _client(patch={"id": "k1", "name": "new"})
        result = _invoke(runner, ["-o", "json", "api-keys", "update", "k1", "--name", "new"], c)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["name"] == "new"
        c.patch.assert_called_once_with("/v1/api-keys/k1", data={"name": "new"})

    def test_api_keys_revoke_json(self, runner, tmp_config):
        c = _client(delete=None)
        result = _invoke(runner, ["-o", "json", "api-keys", "revoke", "k1", "--yes"], c)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {"id": "k1", "revoked": True}
        c.delete.assert_called_once_with("/v1/api-keys/k1")

    def test_api_keys_delete_json(self, runner, tmp_config):
        c = _client(delete=None)
        result = _invoke(runner, ["-o", "json", "api-keys", "delete", "k1", "--yes"], c)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {"id": "k1", "deleted": True}
        c.delete.assert_called_once_with("/v1/api-keys/k1/permanent")

    @patch("tcadai_cli.commands.config.httpx.get")
    def test_config_validate_json(self, mock_get, runner, tmp_config):
        mock_get.return_value = _resp(200, {"status": "healthy"})
        result = runner.invoke(cli, ["-o", "json", "config", "validate"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["valid"] is True and data["status"] == "healthy"

    def test_doctor_yaml(self, runner, tmp_config):
        with patch("httpx.get", side_effect=httpx.ConnectError("offline")):
            result = runner.invoke(cli, ["-o", "yaml", "doctor"])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load(result.output)
        assert "checks" in data and "version" in data
        assert "✓" not in result.output and "✗" not in result.output

    def test_every_leaf_command_accepts_output_flag(self, runner, tmp_config):
        # -o is a group option; it must parse for every leaf (no leaf redefines it).
        for name in _click_leaves():
            result = runner.invoke(cli, ["-o", "json", *name.split(), "--help"])
            assert result.exit_code == 0, (name, result.output)


# ─── BZC-192..195: command coverage (api-keys, simulations, projects, jobs) ────

class TestApiKeysCommands:
    def test_create_table_shows_key_once_and_declined_save_keeps_config_clean(self, runner, tmp_config):
        c = _client(post=KEY)
        with patch("tcadai_cli.commands.api_keys._interactive", return_value=True), \
             patch("tcadai_cli.commands.api_keys.click.confirm", return_value=False):
            result = _invoke(runner, ["api-keys", "create", "ci", "--scope", "read", "--scope", "write",
                                      "--expires-in-days", "30"], c)
        assert result.exit_code == 0, result.output
        assert "bz_live_SECRET" in result.output and "shown only once" in result.output
        payload = c.post.call_args.kwargs["data"]
        assert payload["name"] == "ci" and payload["scopes"] == ["read", "write"] and "expires_at" in payload
        assert not tmp_config.exists()

    def test_create_accepted_save_writes_config(self, runner, tmp_config):
        c = _client(post=KEY)
        with patch("tcadai_cli.commands.api_keys._interactive", return_value=True), \
             patch("tcadai_cli.commands.api_keys.click.confirm", return_value=True):
            result = _invoke(runner, ["api-keys", "create", "ci"], c)
        assert result.exit_code == 0, result.output
        assert yaml.safe_load(tmp_config.read_text())["api_key"] == "bz_live_SECRET"

    def test_rotate_table(self, runner, tmp_config):
        c = _client(post=KEY)
        result = _invoke(runner, ["api-keys", "rotate", "k1"], c)
        assert result.exit_code == 0 and "rotated" in result.output and "bz_live_SECRET" in result.output
        c.post.assert_called_once_with("/v1/api-keys/k1/rotate")

    def test_update_without_name_is_validation_error_without_request(self, runner, tmp_config):
        c = _client()
        result = _invoke(runner, ["api-keys", "update", "k1"], c)
        assert result.exit_code == 4
        c.patch.assert_not_called()

    def test_revoke_without_yes_prompts_and_aborts(self, runner, tmp_config):
        c = _client()
        result = _invoke(runner, ["api-keys", "revoke", "k1"], c, input="n\n")
        assert result.exit_code != 0
        c.delete.assert_not_called()

    def test_stats_table(self, runner, tmp_config):
        c = _client(get={"total_keys": 3, "active_keys": 2, "revoked_keys": 1, "total_requests": 42})
        result = _invoke(runner, ["api-keys", "stats"], c)
        assert result.exit_code == 0 and "42" in result.output
        c.get.assert_called_once_with("/v1/api-keys/stats/usage")

    @pytest.mark.parametrize("args", [
        ["api-keys", "list"], ["api-keys", "create", "n"], ["api-keys", "rotate", "k"],
        ["api-keys", "update", "k", "--name", "n"], ["api-keys", "revoke", "k", "--yes"],
        ["api-keys", "delete", "k", "--yes"], ["api-keys", "stats"],
    ])
    def test_unauthenticated_exits_2_without_request(self, runner, tmp_config, args):
        c = _client()
        c.api_key = None
        result = _invoke(runner, args, c)
        assert result.exit_code == 2
        for m in ("get", "post", "patch", "delete"):
            getattr(c, m).assert_not_called()


class TestSimulationsCommands:
    def test_status_table(self, runner, tmp_config):
        c = _client(get={"id": "s1", "name": "run-1", "status": "running", "progress": 40})
        result = _invoke(runner, ["simulations", "status", "s1"], c)
        assert result.exit_code == 0 and "running" in result.output and "40%" in result.output
        c.get.assert_called_once_with("/v1/simulations/s1")

    def test_status_shows_error_and_404_exits_3(self, runner, tmp_config):
        c = _client(get={"name": "r", "status": "failed", "error": "solver diverged"})
        result = _invoke(runner, ["simulations", "status", "s1"], c)
        assert result.exit_code == 0 and "solver diverged" in result.output
        result = _invoke(runner, ["simulations", "status", "nope"], _client(get=APIError("missing", 404)))
        assert result.exit_code == 3

    def test_stop_posts_stop_route(self, runner, tmp_config):
        c = _client(post={"id": "s1", "status": "stopping"})
        result = _invoke(runner, ["simulations", "stop", "s1"], c)
        assert result.exit_code == 0 and "stopped" in result.output
        c.post.assert_called_once_with("/v1/simulations/s1/stop")

    def test_stop_json_with_empty_body(self, runner, tmp_config):
        result = _invoke(runner, ["-o", "json", "simulations", "stop", "s1"], _client(post=None))
        assert json.loads(result.output) == {"id": "s1", "stopped": True}

    def test_list_passes_filters(self, runner, tmp_config):
        c = _client(get=[])
        _invoke(runner, ["simulations", "list", "--status", "running", "--limit", "5", "--offset", "10"], c)
        c.get.assert_called_once_with("/v1/simulations", params={"limit": 5, "offset": 10, "status": "running"})


class TestProjectsCreate:
    def test_posts_name_description_visibility(self, runner, tmp_config):
        c = _client(post={"id": "p1"})
        result = _invoke(runner, ["projects", "create", "RF", "--description", "d", "--visibility", "public"], c)
        assert result.exit_code == 0 and "p1" in result.output
        c.post.assert_called_once_with("/v1/projects", data={"name": "RF", "visibility": "public", "description": "d"})

    def test_json(self, runner, tmp_config):
        result = _invoke(runner, ["-o", "json", "projects", "create", "RF"], _client(post={"id": "p1", "name": "RF"}))
        assert json.loads(result.output)["id"] == "p1"

    def test_duplicate_exits_7(self, runner, tmp_config):
        result = _invoke(runner, ["projects", "create", "RF"], _client(post=APIError("exists", 409)))
        assert result.exit_code == 7


class TestJobsStatus:
    def test_reads_backend_fields(self, runner, tmp_config):
        c = _client(get={"job_id": "j1", "status": "running", "job_type": "sweep", "progress": 12})
        result = _invoke(runner, ["jobs", "status", "j1"], c)
        assert result.exit_code == 0 and "sweep" in result.output and "12%" in result.output
        c.get.assert_called_once_with("/v1/orchestration/jobs/j1")

    def test_unknown_job_exits_3(self, runner, tmp_config):
        result = _invoke(runner, ["jobs", "status", "zz"], _client(get=APIError("missing", 404)))
        assert result.exit_code == 3


# ─── BZC-198 / BZ-CLI-STALE-ON-CDN (repo side): one version everywhere ─────────

def _pyproject_version():
    m = re.search(r'^version = "([^"]+)"', (CLI_DIR / "pyproject.toml").read_text(), re.M)
    return m.group(1)


class TestVersionSync:
    def test_pyproject_init_readme_changelog_agree(self):
        v = _pyproject_version()
        init = (CLI_DIR / "tcadai_cli" / "__init__.py").read_text()
        assert f'__version__ = "{v}"' in init, "binary fallback version (PackageNotFoundError) must match pyproject"
        assert f"Version {v} (" in (CLI_DIR / "README.md").read_text()
        assert f"## [{v}] - " in (CLI_DIR / "CHANGELOG.md").read_text(), "release the Unreleased section with the bump"

    def test_fixes_since_last_publish_have_a_new_number(self):
        # 1.0.3 was published to the CDN on 2026-10-30; the fixes since (ba7d08989 onwards and
        # this lane) must not ship under the same number, or the update check cannot tell them apart.
        from tcadai_cli.update_check import _is_newer
        v = _pyproject_version()
        assert _is_newer(v, "1.0.3")
        assert not _is_newer("1.0.3", v)

    def test_update_notice_only_for_strictly_newer(self, capsys):
        from tcadai_cli import update_check
        uc = update_check.UpdateChecker()
        uc.latest_version = "1.0.3"
        with patch.object(update_check, "__version__", "1.0.4"):
            uc.notify_if_outdated()
        assert capsys.readouterr().err == ""
        uc.latest_version = "1.0.5"
        with patch.object(update_check, "__version__", "1.0.4"):
            uc.notify_if_outdated()
        err = capsys.readouterr().err
        assert "1.0.5" in err and "install.sh" in err


# ─── Public copy: no em dashes in the CLI, its docs, or the developers hub CLI pages ──

PUBLIC_COPY = [
    *sorted((CLI_DIR / "tcadai_cli").rglob("*.py")),
    CLI_DIR / "README.md", CLI_DIR / "CHANGELOG.md", CLI_DIR / "install.sh",
    DEV_HUB / "CLI" / "cliData.tsx", DEV_HUB / "CLI" / "CliPageSections.tsx",
    DEV_HUB / "GettingStartedSection.tsx", DEV_HUB / "developersData.tsx",
]


class TestNoEmDashes:
    @pytest.mark.parametrize("path", PUBLIC_COPY, ids=lambda p: str(p.relative_to(REPO)))
    def test_file_has_no_em_dash(self, path):
        assert path.exists(), path
        bad = [i + 1 for i, line in enumerate(path.read_text().splitlines()) if "—" in line]
        assert bad == [], f"em dash on lines {bad}"

    def test_help_output_has_no_em_dash(self, runner, tmp_config):
        for name in ["", *_click_leaves()]:
            result = runner.invoke(cli, [*name.split(), "--help"])
            assert "—" not in result.output, name


# ─── BZC-044: /developers/cli reference mirrors the shipped CLI ───────────────

def _click_leaves(group=None, prefix=""):
    import click
    group = group or cli
    out = []
    for name, cmd in sorted(group.commands.items()):
        full = f"{prefix}{name}"
        if isinstance(cmd, click.Group):
            out.extend(_click_leaves(cmd, full + " "))
        else:
            out.append(full)
    return out


def _click_command(name):
    cmd = cli
    for part in name.split():
        cmd = cmd.commands[part]
    return cmd


def _option_names(cmd):
    import click
    names = set()
    for p in cmd.params:
        if isinstance(p, click.Option):
            names.update(p.opts + p.secondary_opts)
    return names


def _dev_hub_commands():
    text = (DEV_HUB / "CLI" / "cliData.tsx").read_text()
    body = text[text.index("export const commands"):]
    starts = [m for m in re.finditer(r'\n\s+name: "([^"]+)"', body)]
    out = {}
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(body)
        block = body[m.start():end]
        flags = re.findall(r'flag: "([^"]+)"', block)
        desc = re.search(r'description:\s*\n?\s*"([^"]+)"', block).group(1)
        out[m.group(1)] = {"flags": flags, "description": desc, "block": block}
    return out


class TestDevHubCliReference:
    def test_every_shipped_command_is_documented_and_nothing_else(self):
        assert set(_dev_hub_commands()) == set(_click_leaves())

    def test_documented_option_flags_exist(self):
        for name, info in _dev_hub_commands().items():
            real = _option_names(_click_command(name))
            for flag in info["flags"]:
                long = flag.split()[0].rstrip(",")
                assert long in real, f"{name}: {flag} is not a CLI option (has {sorted(real)})"

    def test_global_options_exist(self):
        text = (DEV_HUB / "CLI" / "cliData.tsx").read_text()
        block = text[text.index("export const globalOptions"):text.index("export const commands")]
        real = _option_names(cli)
        for flag in re.findall(r'flag: "([^"]+)"', block):
            assert flag.split()[0].rstrip(",") in real, flag
        for want in ("--output", "--no-color", "--verbose", "--debug", "--ci", "--version"):
            assert want in block, f"global option {want} undocumented"

    def test_auth_token_is_described_as_unsupported(self):
        info = _dev_hub_commands()["auth token"]
        assert "not supported" in info["description"]
        assert "password" not in info["description"].lower() or "not supported" in info["description"]
        assert "login --key" in info["block"]

    def test_simulations_create_documents_required_ids(self):
        info = _dev_hub_commands()["simulations create"]
        assert any(f.startswith("--solution-id") for f in info["flags"])
        assert any(f.startswith("--project-id") for f in info["flags"])
        assert "--solution-id" in info["block"] and "--project-id" in info["block"]

    def test_jobs_list_says_no_server_route_yet(self):
        assert "no job-listing route" in _dev_hub_commands()["jobs list"]["description"]

    def test_quick_start_uses_login_not_auth_token(self):
        text = (DEV_HUB / "CLI" / "CliPageSections.tsx").read_text()
        qs = text[text.index("function QuickStartSection"):text.index("function CommandReferenceSection")] \
            if "function CommandReferenceSection" in text else text[text.index("function QuickStartSection"):]
        codes = re.findall(r"code: '([^']+)'", qs)
        assert not any("auth token" in c for c in codes), codes
        assert any(c.startswith("tcadai login --key") for c in codes), codes
        assert any("--solution-id" in c and "--project-id" in c for c in codes), codes

    def test_getting_started_curl_matches_the_api(self):
        text = (DEV_HUB / "GettingStartedSection.tsx").read_text()
        assert '"meta"' not in text and '"data": [' not in text, "GET /v1/simulations returns a bare list"
        assert "physics_domain" not in text and "mesh_elements" not in text, "not SimulationListItem fields"
        assert "Authorization: ApiKey YOUR_API_KEY" in text or "Authorization: Bearer YOUR_API_KEY" in text
        for field in ("solution_id", "project_id", "run_number", "status", "created_at"):
            assert f'"{field}"' in text, field

    def test_getting_started_steps_claim_no_app_registration(self):
        text = (DEV_HUB / "developersData.tsx").read_text()
        assert "client credentials" not in text and "Create an Application" not in text
        assert "paid plan" in text
