"""R1104-CLI-PRESS-ENTER-LOGIN: 'tcadai login' offers to open the browser on the API-key page."""
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from tcadai_cli.commands import login as login_mod
from tcadai_cli.main import cli


def test_offer_browser_opens_key_page_on_tty(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_CLIENT", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    with patch.object(login_mod.sys.stdin, "isatty", return_value=True), \
         patch.object(login_mod.sys.stdout, "isatty", return_value=True), \
         patch.object(login_mod.click, "prompt", return_value="") as prompt, \
         patch.object(login_mod.webbrowser, "open", return_value=True) as wb:
        login_mod._offer_browser(login_mod.KEYS_URL)
    assert "Press Enter" in prompt.call_args[0][0]
    wb.assert_called_once_with("https://app.tcadai.com/account?tab=developers")


def test_offer_browser_prints_url_when_no_browser(capsys, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_CLIENT", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    with patch.object(login_mod.sys.stdin, "isatty", return_value=True), \
         patch.object(login_mod.sys.stdout, "isatty", return_value=True), \
         patch.object(login_mod.click, "prompt", return_value=""), \
         patch.object(login_mod.webbrowser, "open", side_effect=RuntimeError("no display")):
        login_mod._offer_browser(login_mod.KEYS_URL)
    assert "account?tab=developers" in capsys.readouterr().out


def test_no_tty_never_opens_browser():
    # CliRunner stdin is not a tty: CI/pipes must not block or launch a browser.
    with patch.object(login_mod.webbrowser, "open") as wb:
        m = MagicMock()
        m.get.return_value = {"email": "a@b.c"}
        with patch("tcadai_cli.commands.login.BoltzmannClient", return_value=m), \
             patch("tcadai_cli.commands.login.set_api_key"):
            r = CliRunner().invoke(cli, ["login"], input="bz_live_x\nn\n")
    wb.assert_not_called()
    assert "account?tab=developers" in r.output
