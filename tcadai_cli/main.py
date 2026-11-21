"""
TCAD AI CLI - Command-line interface for TCAD AI platform

Copyright (c) 2026 Huntington Applied
All Rights Reserved

Usage:
    tcadai [command] [options]

Commands:
    login         Authenticate and save API key
    simulations   Manage simulations (list, create, status, wait, stop)
    projects      Manage projects (list, create)
    jobs          Manage background jobs (list, status)
    config        Configuration management
    auth          Authentication commands
    api-keys      Manage API keys (create, list, rotate, update, revoke, delete, stats)
"""

import sys
import os
import signal
from pathlib import Path

import click
from dotenv import load_dotenv

from tcadai_cli import __version__, _build_info
from tcadai_cli.config import (
    get_api_key as _get_stored_api_key,
    get_api_url as _get_stored_api_url,
    load_config,
    validate_config,
)
from tcadai_cli.log import setup_logging, logger
from tcadai_cli.exit_codes import EXIT_GENERAL, EXIT_SIGINT, EXIT_SIGTERM
from tcadai_cli.update_check import UpdateChecker

PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


def _make_client(ctx):
    from tcadai_cli.client import BoltzmannClient
    return BoltzmannClient(
        api_url=ctx.obj["API_URL"],
        token=ctx.obj.get("AUTH_TOKEN"),
        api_key=ctx.obj.get("API_KEY"),
    )


def _print_version(ctx, _param, value):
    """--version: evaluated at call time so the stamped commit shows (R1103-BINARY-CLI-NO-COMMIT-STALE-MANIFEST)."""
    if not value or ctx.resilient_parsing:
        return
    click.echo(_build_info.version_message().replace("%(prog)s", "tcadai"))
    ctx.exit()


@click.group()
@click.option("--version", is_flag=True, is_eager=True, expose_value=False, callback=_print_version,
              help="Show the version and build commit, then exit.")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), default="table",
              help="Output format (default: table)")
@click.option("--no-color", is_flag=True, default=False, envvar="NO_COLOR",
              help="Disable colored output")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show informational messages (INFO level)")
@click.option("--debug", is_flag=True, default=False,
              help="Show debug messages including HTTP requests")
@click.option("--ci", is_flag=True, default=False,
              help="CI mode: no color, no spinners, no interactive prompts")
@click.pass_context
def cli(ctx, output, no_color, verbose, debug, ci):
    """TCAD AI CLI - Multiphysics Simulation Platform"""
    ctx.ensure_object(dict)

    # Auto-detect CI environment
    if not ci and (os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or os.getenv("GITLAB_CI")):
        ci = True
    if ci:
        no_color = True

    ctx.obj["output"] = output
    ctx.obj["no_color"] = no_color
    ctx.obj["verbose"] = verbose
    ctx.obj["debug"] = debug
    ctx.obj["DEBUG"] = debug
    ctx.obj["ci"] = ci
    setup_logging(verbose=verbose, debug=debug)

    ctx.obj["API_URL"] = os.getenv("API_URL") or _get_stored_api_url()
    ctx.obj["AUTH_TOKEN"] = os.getenv("AUTH_TOKEN")
    ctx.obj["API_KEY"] = os.getenv("BOLTZMANN_API_KEY") or _get_stored_api_key()

    # Validate config and warn about issues
    config = load_config()
    if config:
        for w in validate_config(config):
            click.echo(f"Warning: {w}", err=True)


# ─── login ────────────────────────────────────────────────────────────────────

from tcadai_cli.commands.login import login
cli.add_command(login)

from tcadai_cli.commands.doctor import doctor
cli.add_command(doctor)

from tcadai_cli.commands.completion import completion
cli.add_command(completion)


# ─── simulations ──────────────────────────────────────────────────────────────

@cli.group()
def simulations():
    """Manage simulations"""
    pass


@simulations.command("list")
@click.option("--status", help="Filter by status")
@click.option("--limit", default=20, help="Number of results")
@click.option("--offset", default=0, help="Offset for pagination")
@click.pass_context
def simulations_list(ctx, status, limit, offset):
    """List user simulations"""
    from tcadai_cli.commands.simulations import list_simulations
    list_simulations(_make_client(ctx), status, limit, offset, ctx=ctx)


@simulations.command("create")
@click.argument("name")
@click.option("--solution-id", "--solution", "solution_id", default=None,
              help="Solution UUID (HOW to run). Required unless set in --config.")
@click.option("--project-id", "--project", "project_id", default=None,
              help="Project UUID (WHAT to run). Required unless set in --config. See: tcadai projects list")
@click.option("--description", default=None, help="Simulation description")
@click.option("--type", "sim_type", default="electromagnetic", help="Simulation type")
@click.option("--config", type=click.Path(exists=True),
              help="JSON file; top-level solution_id, project_id, description, streaming_mode, "
                   "data_resolution_hz, visualization_refresh_hz are sent")
@click.pass_context
def simulations_create(ctx, name, solution_id, project_id, description, sim_type, config):
    """Create a new simulation from a solution and a project

    \b
    Example:
        tcadai simulations create run1 --solution-id <uuid> --project-id <uuid>
    """
    from tcadai_cli.commands.simulations import create_simulation
    create_simulation(_make_client(ctx), name, sim_type, config,
                      solution_id=solution_id, project_id=project_id,
                      description=description, ctx=ctx)


@simulations.command("status")
@click.argument("simulation_id")
@click.pass_context
def simulations_status(ctx, simulation_id):
    """Get simulation status"""
    from tcadai_cli.commands.simulations import get_simulation_status
    get_simulation_status(_make_client(ctx), simulation_id, ctx=ctx)


@simulations.command("wait")
@click.argument("simulation_id")
@click.option("--timeout", type=int, default=3600, show_default=True, help="Give up after this many seconds")
@click.option("--interval", type=int, default=5, show_default=True, help="Seconds between checks")
@click.pass_context
def simulations_wait(ctx, simulation_id, timeout, interval):
    """Wait for a simulation to finish (exit 0 completed, 8 failed/cancelled, 9 timed out)"""
    from tcadai_cli.commands.simulations import wait_for_simulation
    wait_for_simulation(_make_client(ctx), simulation_id, timeout=timeout, interval=max(1, interval), ctx=ctx)


@simulations.command("stop")
@click.argument("simulation_id")
@click.pass_context
def simulations_stop(ctx, simulation_id):
    """Stop a running simulation"""
    from tcadai_cli.commands.simulations import stop_simulation
    stop_simulation(_make_client(ctx), simulation_id, ctx=ctx)


# ─── projects ─────────────────────────────────────────────────────────────────

@cli.group()
def projects():
    """Manage projects"""
    pass


@projects.command("list")
@click.option("--visibility", type=click.Choice(["public", "private"], case_sensitive=False),
              help="Filter by visibility (public/private)")
@click.option("--limit", default=20, help="Number of results")
@click.pass_context
def projects_list(ctx, visibility, limit):
    """List user projects"""
    from tcadai_cli.commands.projects import list_projects
    list_projects(_make_client(ctx), visibility, limit, ctx=ctx)


@projects.command("create")
@click.argument("name")
@click.option("--description", help="Project description")
@click.option("--visibility", default="private", help="Visibility (public/private)")
@click.pass_context
def projects_create(ctx, name, description, visibility):
    """Create a new project"""
    from tcadai_cli.commands.projects import create_project
    create_project(_make_client(ctx), name, description, visibility, ctx=ctx)


# ─── jobs ─────────────────────────────────────────────────────────────────────

@cli.group()
def jobs():
    """Manage background jobs"""
    pass


@jobs.command("list")
@click.option("--status", help="Filter by status (pending/running/completed/failed)")
@click.option("--limit", default=20, help="Number of results")
@click.pass_context
def jobs_list(ctx, status, limit):
    """List background jobs"""
    from tcadai_cli.commands.jobs import list_jobs
    list_jobs(_make_client(ctx), status, limit, ctx=ctx)


@jobs.command("status")
@click.argument("job_id")
@click.pass_context
def jobs_status(ctx, job_id):
    """Get job status"""
    from tcadai_cli.commands.jobs import get_job_status
    get_job_status(_make_client(ctx), job_id, ctx=ctx)


# ─── config ───────────────────────────────────────────────────────────────────

@cli.group()
def config():
    """Configuration management"""
    pass


@config.command("show")
@click.option("--section", help="Show specific section (api, auth, database)")
def config_show(section):
    """Show current configuration"""
    from tcadai_cli.commands.config import show_config
    show_config(section)


@config.command("validate")
@click.pass_context
def config_validate(ctx):
    """Validate configuration by checking API health"""
    from tcadai_cli.commands.config import validate_config
    validate_config(ctx.obj["API_URL"], ctx=ctx)


# ─── auth ─────────────────────────────────────────────────────────────────────

@cli.group()
def auth():
    """Authentication commands"""
    pass


@auth.command("status")
@click.pass_context
def auth_status(ctx):
    """Check authentication status"""
    from tcadai_cli.commands.auth import check_auth_status
    check_auth_status(_make_client(ctx), ctx=ctx)


@auth.command("token")
@click.option("--email", default=None, help="User email (not supported; see below)")
@click.option("--password", default=None, hide_input=True, help="User password (not supported; see below)")
@click.pass_context
def auth_token(ctx, email, password):
    """Get a token (email/password is not supported; use an API key)

    The TCAD AI API signs users in through the browser and authenticates the
    CLI with API keys. Run: tcadai login --key <key>
    """
    from tcadai_cli.commands.auth import get_token
    get_token(ctx.obj["API_URL"], email, password)


# ─── api-keys ─────────────────────────────────────────────────────────────────

@cli.group("api-keys")
def api_keys_group():
    """Manage API keys for programmatic access"""
    pass


@api_keys_group.command("list")
@click.pass_context
def api_keys_list(ctx):
    """List your API keys"""
    from tcadai_cli.commands.api_keys import list_api_keys
    list_api_keys(_make_client(ctx), ctx=ctx)


@api_keys_group.command("create")
@click.argument("name")
@click.option("--scope", "scopes", multiple=True, default=("read",),
              help="Scopes (repeatable, e.g. --scope read --scope write)")
@click.option("--expires-in-days", type=int, default=None,
              help="Expiration in days (default: never expires)")
@click.pass_context
def api_keys_create(ctx, name, scopes, expires_in_days):
    """Create a new API key"""
    from tcadai_cli.commands.api_keys import create_api_key
    create_api_key(_make_client(ctx), name, scopes, expires_in_days, ctx=ctx)


@api_keys_group.command("rotate")
@click.argument("key_id")
@click.pass_context
def api_keys_rotate(ctx, key_id):
    """Rotate (regenerate) an API key: the old key stops working immediately"""
    from tcadai_cli.commands.api_keys import rotate_api_key
    rotate_api_key(_make_client(ctx), key_id, ctx=ctx)


@api_keys_group.command("update")
@click.argument("key_id")
@click.option("--name", default=None, help="New name for the key")
@click.pass_context
def api_keys_update(ctx, key_id, name):
    """Update an API key's name"""
    from tcadai_cli.commands.api_keys import update_api_key
    update_api_key(_make_client(ctx), key_id, name, ctx=ctx)


@api_keys_group.command("revoke")
@click.argument("key_id")
@click.confirmation_option(prompt="Revoke this key? It will stop working immediately.")
@click.pass_context
def api_keys_revoke(ctx, key_id):
    """Revoke an API key (soft delete, keeps the audit record)"""
    from tcadai_cli.commands.api_keys import revoke_api_key
    revoke_api_key(_make_client(ctx), key_id, ctx=ctx)


@api_keys_group.command("delete")
@click.argument("key_id")
@click.confirmation_option(prompt="Permanently delete this key? This cannot be undone.")
@click.pass_context
def api_keys_delete(ctx, key_id):
    """Permanently delete an API key (hard delete, removed from the database)"""
    from tcadai_cli.commands.api_keys import delete_api_key_permanent
    delete_api_key_permanent(_make_client(ctx), key_id, ctx=ctx)


@api_keys_group.command("stats")
@click.pass_context
def api_keys_stats(ctx):
    """Show API key usage statistics"""
    from tcadai_cli.commands.api_keys import show_stats
    show_stats(_make_client(ctx), ctx=ctx)


# ─── entry point ──────────────────────────────────────────────────────────────

_update_checker = UpdateChecker()


def main():
    """Entry point with top-level signal and exception handling."""
    signal.signal(signal.SIGTERM, lambda sig, frame: sys.exit(EXIT_SIGTERM))
    _update_checker.start()
    try:
        cli(obj={}, standalone_mode=False)
    except click.exceptions.Exit as e:
        raise SystemExit(e.exit_code)
    except (KeyboardInterrupt, click.Abort):
        raise SystemExit(EXIT_SIGINT)
    except SystemExit:
        raise
    except click.ClickException as e:
        e.show()
        raise SystemExit(EXIT_GENERAL)
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        if os.getenv("DEBUG"):
            raise
        raise SystemExit(EXIT_GENERAL)
    finally:
        _update_checker.notify_if_outdated()


if __name__ == "__main__":
    main()
