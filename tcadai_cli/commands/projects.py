"""TCAD AI CLI - Projects commands"""

import click
from tabulate import tabulate

from tcadai_cli.client import BoltzmannClient, AuthError, APIError
from tcadai_cli.errors import fail
from tcadai_cli.output import emit_structured


def _visibility_params(visibility):
    """Map --visibility to the list route's real query params (BZ CLI-05).

    GET /v1/projects has no `visibility` param; it filters with is_public and
    include_public (own projects only unless include_public is true).
    """
    if not visibility:
        return {}
    v = visibility.lower()
    if v == "public":
        return {"is_public": "true", "include_public": "true"}
    if v == "private":
        return {"is_public": "false"}
    return {}


def list_projects(client: BoltzmannClient, visibility, limit, ctx=None):
    try:
        params = {"limit": limit}
        params.update(_visibility_params(visibility))
        data = client.get("/v1/projects", params=params)
        # The API returns a bare list; older deployments wrapped it in
        # {"projects": [...]} / {"items": [...]}; accept both (HQ2 U12).
        if isinstance(data, list):
            projects = data
        else:
            projects = data.get("projects", data.get("items", []))
        if emit_structured(ctx, projects):
            return
        if not projects:
            click.echo("No projects found.")
            return
        rows = [
            [str(p.get("id", ""))[:8], p.get("name", ""), p.get("visibility", ""), p.get("created_at", "")]
            for p in projects
        ]
        click.echo(tabulate(rows, headers=["ID", "Name", "Visibility", "Created"]))
    except (AuthError, APIError) as e:
        fail(e)


def create_project(client: BoltzmannClient, name, description, visibility, ctx=None):
    try:
        payload = {"name": name, "visibility": visibility}
        if description:
            payload["description"] = description
        data = client.post("/v1/projects", data=payload)
        if emit_structured(ctx, data):
            return
        click.echo(f"Project created: {(data or {}).get('id', 'unknown')}")
    except (AuthError, APIError) as e:
        fail(e)
