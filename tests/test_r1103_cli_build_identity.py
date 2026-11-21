"""R1103-BINARY-CLI-NO-COMMIT-STALE-MANIFEST: --version carries the build commit, and the release manifest is
generated from the served binaries so its sha cannot go stale."""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from tcadai_cli import __version__, _build_info
from tcadai_cli.main import cli

CLI_DIR = Path(__file__).resolve().parent.parent
SHA = "0123456789abcdef0123456789abcdef01234567"


def test_version_reports_the_stamped_commit(monkeypatch):
    monkeypatch.setattr(_build_info, "COMMIT", SHA)
    out = CliRunner().invoke(cli, ["--version"]).output
    assert __version__ in out
    assert "commit 0123456789ab" in out


def test_version_without_a_stamp_says_unknown_not_blank(monkeypatch):
    monkeypatch.setattr(_build_info, "COMMIT", "")
    monkeypatch.delenv("BOLTZMANN_BUILD_ID", raising=False)
    assert "commit unknown" in CliRunner().invoke(cli, ["--version"]).output


def test_committed_build_info_is_unstamped():
    assert _build_info.COMMIT == ""


def test_build_script_stamps_and_restores_and_checks_the_binary():
    s = (CLI_DIR / "scripts" / "build_binary.sh").read_text()
    assert "_build_info.py" in s and "trap restore_build_info EXIT" in s
    assert '--version | grep -q "commit' in s
    assert subprocess.run(["bash", "-n", str(CLI_DIR / "scripts" / "build_binary.sh")]).returncode == 0


def _load_manifest_module():
    spec = importlib.util.spec_from_file_location("write_manifest", CLI_DIR / "scripts" / "write_manifest.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_manifest_sha_is_the_served_binary(tmp_path):
    wm = _load_manifest_module()
    b = tmp_path / "tcadai-darwin-arm64"
    b.write_bytes(b"binary-bytes")
    out = tmp_path / "manifest.json"
    assert wm.main(["--version", __version__, "--commit", SHA, "--binary", f"darwin-arm64={b}", "--out", str(out)]) == 0
    m = json.loads(out.read_text())
    assert m["version"] == __version__ and m["commit"] == SHA
    assert m["binaries"]["darwin-arm64"]["sha256"] == hashlib.sha256(b"binary-bytes").hexdigest()


def test_manifest_refuses_bad_input(tmp_path):
    wm = _load_manifest_module()
    b = tmp_path / "x"
    b.write_bytes(b"x")
    assert wm.main(["--version", "latest", "--commit", SHA, "--binary", f"a={b}"]) == 2
    assert wm.main(["--version", "1.0.4", "--commit", "abc", "--binary", f"a={b}"]) == 2
    assert wm.main(["--version", "1.0.4", "--commit", SHA, "--binary", f"a={tmp_path / 'missing'}"]) == 2
