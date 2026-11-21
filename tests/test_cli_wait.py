"""R1104-CUE-STATENOTTERMINALUI-CLI-STATUS-FIELDS: status prints the fields SimulationRead really has;
`simulations wait` gives CI a non-zero exit on failed/cancelled."""
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from tcadai_cli.main import cli
from tcadai_cli.exit_codes import EXIT_RUN_FAILED, EXIT_TIMEOUT


def _client(*bodies):
    c = MagicMock()
    c.api_key, c.token, c.api_url = "k", None, "http://localhost:8009"
    c.get.side_effect = list(bodies)
    return c


def _run(args, client):
    with patch("tcadai_cli.client.BoltzmannClient", return_value=client), \
         patch("time.sleep", lambda s: None):
        return CliRunner().invoke(cli, args)


def test_status_shows_error_message_and_timing_not_fake_progress():
    c = _client({"name": "r1", "status": "failed", "error_message": "solver diverged", "error_code": "E_DIVERGE",
                 "engine_started_at": "2026-11-04T10:00:00Z", "failed_at": "2026-11-04T10:05:00Z"})
    r = _run(["simulations", "status", "s1"], c)
    assert r.exit_code == 0
    assert "solver diverged" in r.output and "E_DIVERGE" in r.output
    assert "2026-11-04T10:05:00Z" in r.output
    assert "Progress" not in r.output


def test_wait_exits_zero_on_completed():
    c = _client({"status": "running"}, {"status": "completed", "converged": True})
    r = _run(["simulations", "wait", "s1", "--interval", "1"], c)
    assert r.exit_code == 0, r.output
    assert "completed" in r.output


@pytest.mark.parametrize("final", ["failed", "cancelled"])
def test_wait_nonzero_on_failed_or_cancelled(final):
    c = _client({"status": "running"}, {"status": final, "error_message": "boom"})
    r = _run(["simulations", "wait", "s1"], c)
    assert r.exit_code == EXIT_RUN_FAILED
    assert "boom" in r.output


def test_wait_times_out():
    c = _client(*[{"status": "running"}] * 50)
    r = _run(["simulations", "wait", "s1", "--timeout", "0"], c)
    assert r.exit_code == EXIT_TIMEOUT
