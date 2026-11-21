"""TCAD AI CLI - login command"""

import os
import sys
import webbrowser

import click

from tcadai_cli import _lab_login
from tcadai_cli.config import set_api_key, set_api_url, get_api_url
from tcadai_cli.client import BoltzmannClient, AuthError, APIError
from tcadai_cli.errors import fail


KEYS_URL = "https://app.tcadai.com/account?tab=developers"


def _offer_browser(url: str) -> None:
    """Press Enter to open the signed-in account's API-key page (shared lab_login flow).

    Quiet when not at a terminal; over SSH or with no display it prints the URL to open
    elsewhere instead of launching (or blocking on) a browser.
    """
    _lab_login.open_key_page(
        url,
        interactive=bool(sys.stdin.isatty() and sys.stdout.isatty()),
        out=click.echo,
        ask=lambda p: click.prompt(p.rstrip(), default="", show_default=False),
        opener=lambda u: webbrowser.open(u),
    )


@click.command()
@click.option("--key", default=None, help="API key (skips wizard)")
@click.option("--url", default=None, help="Custom API URL")
@click.pass_context
def login(ctx, key, url):
    """Authenticate with the TCAD AI platform.

    The key is checked against the API first and saved only if it works.

    \b
    Examples:
        tcadai login                        # interactive wizard
        tcadai login --key bz_live_abc123   # non-interactive
    """
    if not key:
        click.echo()
        click.echo("  Welcome to TCAD AI CLI!")
        click.echo()
        click.echo("  To get your API key:")
        click.echo(f"    1. Open {KEYS_URL} (sign in if asked)")
        click.echo("    2. Click 'Create API Key'")
        click.echo("    3. Copy the key and paste it below")
        click.echo()
        _offer_browser(KEYS_URL)
        key = click.prompt("  API Key", hide_input=True)
        if not url and click.confirm("  Use a custom API URL?", default=False):
            url = click.prompt("  API URL", default=get_api_url())

    key = key.strip()
    url = url.strip() if url else None
    api_url = url or ctx.obj.get("API_URL") or get_api_url()

    # Verify BEFORE saving (U10): a bad key must not replace a working one, and the
    # command must exit non-zero so scripts stop.
    try:
        client = BoltzmannClient(api_url, api_key=key)
        data = client.get("/v1/auth/me") or {}
    except AuthError as e:
        # The hint inside AuthError says "run: tcadai login", which is this command.
        reason = str(e).splitlines()[0]
        fail(e, f"✗ The API at {client.api_url} rejected this key: {reason}\n"
                "  Key not written to ~/.tcadai/config.yaml.\n"
                "  Create a key at app.tcadai.com → Account → Developer, then retry:\n"
                "    tcadai login --key <key>")
    except APIError as e:
        if getattr(e, "status_code", 0) == 403:
            fail(e, f"✗ The API at {client.api_url} rejected this key (403: no permission).\n"
                    "  Key not written to ~/.tcadai/config.yaml.\n"
                    "  Create a new key at app.tcadai.com → Account → Developer, then retry:\n"
                    "    tcadai login --key <key>")
        fail(e, f"✗ API key verification failed: {e}\n"
                "  Key not written to ~/.tcadai/config.yaml.\n"
                "  Check your key and try: tcadai login --key <key>")

    set_api_key(key)
    if url:
        set_api_url(client.api_url)  # normalized (no trailing /v1)
    email = data.get("email", "unknown")
    click.echo(f"✓ Authenticated as {email}")
    click.echo("✓ API key saved to ~/.tcadai/config.yaml")
    if os.environ.get("BOLTZMANN_API_KEY"):
        click.echo("  Note: BOLTZMANN_API_KEY is set in this environment and overrides the saved key.")
    click.echo()
    click.echo("  Next steps:")
    click.echo("    tcadai simulations list   list your simulations")
    click.echo("    tcadai projects list      list your projects")
    click.echo("    tcadai api-keys list      manage API keys")
