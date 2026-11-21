"""BZ-CLI-README-PUBLIC-BROKEN: the public README quickstart must match the shipped CLI."""
import re
from pathlib import Path

from click.testing import CliRunner

from tcadai_cli.main import cli

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
VERSION = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)


def test_readme_version_pin_example_is_current():
    pins = re.findall(r"--version (\d+\.\d+\.\d+)", README)
    assert pins and all(p == VERSION for p in pins), (pins, VERSION)


def test_readme_status_version_matches_pyproject():
    assert f"Version {VERSION}" in README


def test_readme_dev_block_has_no_contradictory_cd():
    dev = README.split("## Development", 1)[1].split("###", 1)[0]
    assert "pip install -e cli/" not in dev


def test_readme_quickstart_commands_exist():
    for cmd in ("login", "doctor", "simulations", "projects", "jobs", "api-keys", "auth", "config", "completion"):
        r = CliRunner().invoke(cli, [cmd, "--help"])
        assert r.exit_code == 0, (cmd, r.output)
