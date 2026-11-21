"""TCAD AI CLI - Auth commands"""

import click

from tcadai_cli.client import BoltzmannClient, AuthError, APIError
from tcadai_cli.errors import fail, fail_with
from tcadai_cli.exit_codes import EXIT_AUTH
from tcadai_cli.output import emit_structured

NOT_AUTHENTICATED = "Not authenticated. Set BOLTZMANN_API_KEY or run 'tcadai login'."

# The TCAD AI API has no email/password login route (sign-in is Auth0 in the
# browser; the CLI authenticates with an API key). `auth token` used to POST to
# /v1/auth/login, which does not exist, so it always 404'd and exited 0
# (KNOWN-API-PREFIX). The command stays and explains the supported path.
TOKEN_UNSUPPORTED = (
    "Email/password token login is not supported by the TCAD AI API.\n"
    "  Use an API key: tcadai login --key <key>\n"
    "  Create a key at app.tcadai.com → Account → Developer, or set BOLTZMANN_API_KEY.\n"
    "  To use an existing Bearer token, set AUTH_TOKEN."
)


def check_auth_status(client: BoltzmannClient, ctx=None):
    if not client.token and not client.api_key:
        if emit_structured(ctx, {"authenticated": False}):
            raise SystemExit(EXIT_AUTH)
        fail_with(EXIT_AUTH, NOT_AUTHENTICATED)
    try:
        data = client.get("/v1/auth/me")
        method = "API key" if client.api_key else "Bearer token"
        if emit_structured(ctx, {
            "authenticated": True,
            "email": data.get("email"),
            "user_id": data.get("sub", data.get("id")),
            "auth_method": method,
        }):
            return
        click.echo(f"Authenticated as: {data.get('email', 'unknown')}")
        click.echo(f"User ID:          {data.get('sub', data.get('id', 'unknown'))}")
        click.echo(f"Auth method:      {method}")
    except (AuthError, APIError) as e:
        fail(e)


def get_token(api_url=None, email=None, password=None):
    """Explain that email/password token login is unsupported and exit EXIT_AUTH.

    No credentials are sent anywhere.
    """
    fail_with(EXIT_AUTH, TOKEN_UNSUPPORTED)
