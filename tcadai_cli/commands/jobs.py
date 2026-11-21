"""TCAD AI CLI - Jobs commands"""

import click
from tabulate import tabulate

from tcadai_cli.client import BoltzmannClient, AuthError, APIError
from tcadai_cli.errors import fail
from tcadai_cli.output import emit_structured

# The orchestration API serves POST /jobs/submit, GET /jobs/{id} and
# POST /jobs/{id}/cancel. A per-user job listing (GET /v1/orchestration/jobs) is
# not served yet (BZ CLI-02), so a 404/405 from the list call means "no list route
# on this server", not "bad ID".
_JOBS_LIST_UNAVAILABLE = (
    "Listing jobs is not available on this TCAD AI server yet.\n"
    "  Check a job you submitted with: tcadai jobs status <job_id>\n"
    "  Your runs are listed by: tcadai simulations list"
)


def _job_id(j):
    return str(j.get("job_id") or j.get("id") or "")


def _job_type(j):
    return j.get("job_type") or j.get("type") or ""


def list_jobs(client: BoltzmannClient, status, limit, ctx=None):
    try:
        params = {"limit": limit}
        if status:
            params["status"] = status
        data = client.get("/v1/orchestration/jobs", params=params)
    except APIError as e:
        if e.status_code in (404, 405):
            fail(e, _JOBS_LIST_UNAVAILABLE)
        fail(e)
    except AuthError as e:
        fail(e)
    jobs = data if isinstance(data, list) else (data or {}).get("jobs", (data or {}).get("items", []))
    if emit_structured(ctx, jobs):
        return
    if not jobs:
        click.echo("No jobs found.")
        return
    rows = [
        [_job_id(j)[:8], j.get("status", ""), _job_type(j), j.get("created_at", "")]
        for j in jobs
    ]
    click.echo(tabulate(rows, headers=["ID", "Status", "Type", "Created"]))


def get_job_status(client: BoltzmannClient, job_id, ctx=None):
    try:
        data = client.get(f"/v1/orchestration/jobs/{job_id}")
        if emit_structured(ctx, data):
            return
        # JobStatusResponse uses job_id / job_type / error_message; accept the
        # older id / type / error names too.
        click.echo(f"Job:    {_job_id(data) or job_id}")
        click.echo(f"Status: {data.get('status', 'unknown')}")
        click.echo(f"Type:   {_job_type(data) or 'unknown'}")
        if data.get("progress") is not None:
            click.echo(f"Progress: {data['progress']}%")
        if data.get("result"):
            click.echo(f"Result: {data['result']}")
        err = data.get("error_message") or data.get("error")
        if err:
            click.echo(f"Error:  {err}", err=True)
    except (AuthError, APIError) as e:
        fail(e)
