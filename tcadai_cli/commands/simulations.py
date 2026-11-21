"""TCAD AI CLI - Simulations commands"""

import json
import sys
import click
from tabulate import tabulate

from tcadai_cli.client import BoltzmannClient, AuthError, APIError
from tcadai_cli.errors import fail, fail_with
from tcadai_cli.exit_codes import EXIT_RUN_FAILED, EXIT_TIMEOUT, EXIT_VALIDATION
from tcadai_cli.output import emit_structured

# Fields POST /v1/simulations (SimulationCreate) accepts besides name.
_CREATE_FIELDS = (
    "description",
    "solution_id",
    "project_id",
    "status",
    "streaming_mode",
    "data_resolution_hz",
    "visualization_refresh_hz",
)


def list_simulations(client: BoltzmannClient, status, limit, offset, ctx=None):
    try:
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        data = client.get("/v1/simulations", params=params)
        # /v1/simulations returns a bare List[SimulationListItem]; guard the
        # dict-shaped fallback so `.get()` never runs on a list (U12; mirrors
        # jobs.py/projects.py).
        simulations = data if isinstance(data, list) else data.get("simulations", data.get("items", []))
        if emit_structured(ctx, simulations):
            return
        if not simulations:
            click.echo("No simulations found.")
            return
        rows = [
            [str(s.get("id", ""))[:8], s.get("name", ""), s.get("status", ""), s.get("created_at", "")]
            for s in simulations
        ]
        click.echo(tabulate(rows, headers=["ID", "Name", "Status", "Created"]))
    except (AuthError, APIError) as e:
        fail(e)


def create_simulation(client: BoltzmannClient, name, sim_type, config_file,
                      solution_id=None, project_id=None, description=None, ctx=None):
    """Create a simulation.

    The API (SimulationCreate) requires a solution_id (HOW to run) and a project_id
    (WHAT to run). They come from --solution-id/--project-id or from top-level keys in
    the --config JSON file; the options win over the file.
    """
    payload = {"name": name}
    if sim_type:
        # Not a SimulationCreate field (the solution defines the physics); sent as a
        # hint and ignored by servers that do not use it.
        payload["type"] = sim_type
    if config_file:
        try:
            with open(config_file) as f:
                cfg = json.load(f)
        except (OSError, ValueError) as e:
            fail_with(EXIT_VALIDATION, f"Could not read --config {config_file}: {e}")
        if isinstance(cfg, dict):
            payload["config"] = cfg
            for key in _CREATE_FIELDS:
                if cfg.get(key) is not None:
                    payload[key] = cfg[key]
    if solution_id:
        payload["solution_id"] = solution_id
    if project_id:
        payload["project_id"] = project_id
    if description:
        payload["description"] = description

    missing = [opt for opt, key in (("--solution-id", "solution_id"), ("--project-id", "project_id"))
               if not payload.get(key)]
    if missing:
        fail_with(
            EXIT_VALIDATION,
            "A simulation needs a solution and a project. Missing: " + ", ".join(missing) + ".\n"
            "  Usage: tcadai simulations create NAME --solution-id <uuid> --project-id <uuid>\n"
            "  (or put solution_id / project_id in the --config JSON file).\n"
            "  Find project IDs with: tcadai projects list",
        )

    try:
        data = client.post("/v1/simulations", data=payload)
        if emit_structured(ctx, data):
            return
        click.echo(f"Simulation created: {(data or {}).get('id', 'unknown')}")
    except (AuthError, APIError) as e:
        fail(e)


_TERMINAL = {"completed", "failed", "cancelled", "canceled", "stopped"}
_BAD_END = {"failed", "cancelled", "canceled", "stopped"}


def _norm_status(data) -> str:
    return str((data or {}).get("status") or "unknown").lower()


def _status_lines(data, simulation_id):
    """Human lines for SimulationRead. The API has no `progress`/`error` fields: it reports status,
    error_message/error_code, converged and timing, so print those (and progress only if a server sends it)."""
    lines = [
        f"Simulation: {data.get('name', simulation_id)}",
        f"Status:     {data.get('status', 'unknown')}",
    ]
    if isinstance(data.get("progress"), (int, float)):
        lines.append(f"Progress:   {data['progress']}%")
    for label, key in (("Started", "engine_started_at"), ("Completed", "completed_at"),
                       ("Failed at", "failed_at"), ("Cancelled", "cancelled_at")):
        if data.get(key):
            lines.append(f"{label}:".ljust(12) + str(data[key]))
    if data.get("wall_clock_time_seconds") is not None:
        lines.append(f"Wall time:  {data['wall_clock_time_seconds']}s")
    if data.get("converged") is not None:
        lines.append(f"Converged:  {data['converged']}")
    reason = data.get("error_message") or data.get("error")
    if reason:
        code = data.get("error_code")
        lines.append(f"Error:      {reason}" + (f" ({code})" if code else ""))
    return lines


def get_simulation_status(client: BoltzmannClient, simulation_id, ctx=None):
    try:
        data = client.get(f"/v1/simulations/{simulation_id}")
        if emit_structured(ctx, data):
            return
        for line in _status_lines(data, simulation_id):
            click.echo(line, err=line.startswith("Error:"))
    except (AuthError, APIError) as e:
        fail(e)


def wait_for_simulation(client: BoltzmannClient, simulation_id, timeout=3600, interval=5, ctx=None,
                        _sleep=None, _clock=None):
    """Poll until the run reaches a terminal state. Exit 0 on completed, EXIT_RUN_FAILED on
    failed/cancelled/stopped (reason printed), EXIT_TIMEOUT when --timeout elapses. For CI."""
    import time
    sleep = _sleep or time.sleep
    clock = _clock or time.monotonic
    deadline = clock() + max(0, timeout)
    last = None
    while True:
        try:
            data = client.get(f"/v1/simulations/{simulation_id}")
        except (AuthError, APIError) as e:
            fail(e)
        st = _norm_status(data)
        if st != last:
            click.echo(f"Status: {st}", err=True)
            last = st
        if st in _TERMINAL:
            if emit_structured(ctx, data):
                pass
            else:
                for line in _status_lines(data, simulation_id):
                    click.echo(line, err=line.startswith("Error:"))
            if st in _BAD_END:
                sys.exit(EXIT_RUN_FAILED)
            return
        if clock() >= deadline:
            fail_with(EXIT_TIMEOUT, f"Timed out after {timeout}s; simulation is still {st}.")
        sleep(interval)


def stop_simulation(client: BoltzmannClient, simulation_id, ctx=None):
    try:
        data = client.post(f"/v1/simulations/{simulation_id}/stop")
        if emit_structured(ctx, data if data is not None else {"id": simulation_id, "stopped": True}):
            return
        click.echo(f"Simulation {simulation_id} stopped.")
    except (AuthError, APIError) as e:
        fail(e)
