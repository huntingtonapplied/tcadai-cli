# TCAD AI CLI

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](#license)
[![Status](https://img.shields.io/badge/status-active-success.svg)](#)

-----------------

**TCAD AI CLI** is the command-line client for the TCAD AI multiphysics simulation platform: authenticate with an API key and drive simulations, projects, and jobs from your terminal or CI pipeline.

It is a thin client: it talks to the hosted TCAD AI API (`https://api.tcadai.com`), so no local physics engine or database is required to manage simulations.

## Scope

A thin command-line client for the TCAD AI API: authenticate with an API key, then manage simulations, projects and jobs from a terminal or CI. It has no engine or database of its own. The hosted service at [tcadai.com](https://tcadai.com) runs this code with accounts, managed compute and plan capacity. It is a paid service: every plan has the same features, and plans differ only by capacity. The source is open, so you can build and run it yourself. Against the hosted API the CLI needs an account on a paid plan (an account without one has no capacity); it can also be pointed at a self-hosted backend.

## Status

Version 1.0.4 (`pyproject.toml`). The downloads CDN serves the latest published binary; `tcadai --version` shows which one you have.

## Install

Standalone binary (no Python required; verifies SHA256 before installing):

```bash
curl -fsSL https://downloads.tcadai.com/cli/install.sh | bash
```

Prebuilt binaries: Apple Silicon macOS (darwin-arm64) and x86_64 Linux (linux-x86_64). On other platforms the installer stops with an "Unsupported platform" message; install from source instead (below).

Pin a release, or install without sudo into `~/.local/bin`:

```bash
curl -fsSL https://downloads.tcadai.com/cli/install.sh | bash -s -- --version 1.0.4
curl -fsSL https://downloads.tcadai.com/cli/install.sh | bash -s -- --install-dir ~/.local/bin
```

From source (a clone of this repo):

```bash
pip install -e .
```

## Quick Start

```bash
# Authenticate: paste the API key from app.tcadai.com → Account → Developer
tcadai login

# Diagnose setup & connectivity
tcadai doctor

# Manage simulations
tcadai simulations list
tcadai simulations create my-sim --solution-id <solution_uuid> --project-id <project_uuid>
tcadai simulations status <simulation_id>
```

## Commands

| Command | Description |
|---------|-------------|
| `tcadai login` | Authenticate and save your API key |
| `tcadai simulations list/create/status/stop` | Manage simulations |
| `tcadai projects list/create` | Manage projects |
| `tcadai jobs list/status` | Manage background jobs |
| `tcadai api-keys list/create/rotate/update/revoke/delete/stats` | Manage API keys |
| `tcadai auth status/token` | Authentication commands |
| `tcadai config show/validate` | Configuration management |
| `tcadai doctor` | Diagnose CLI setup and connectivity |
| `tcadai completion <shell>` | Generate / install shell completion |

### Global options

- `--output/-o {table,json,yaml}`: output format (default: `table`)
- `--no-color`: disable colored output (also honors `NO_COLOR`)
- `--verbose/-v`: INFO-level logging to stderr
- `--debug`: DEBUG-level logging (HTTP requests)
- `--ci`: CI mode: no color, no spinners, no prompts (auto-detected from `CI`, `GITHUB_ACTIONS`, `GITLAB_CI`)

## Configuration

Config is stored in `~/.tcadai/config.yaml`:

```yaml
api_key: bz_live_abc123...
api_url: https://api.tcadai.com   # optional; this is the default
```

Environment variables override config:

- `BOLTZMANN_API_KEY`: API key
- `BOLTZMANN_API_URL`: API base URL (the origin, without `/v1`; a trailing `/v1` is dropped)
- `BOLTZMANN_MAX_RETRIES`: retry attempts for transient failures (default: 3)
- `BOLTZMANN_TIMEOUT`: request timeout in seconds (default: 30)
- `BOLTZMANN_NO_UPDATE_CHECK`: disable the background version check

### Exit codes

| Code | Meaning | | Code | Meaning |
|------|---------|-|------|---------|
| 0 | Success | | 5 | Network error |
| 1 | General error | | 6 | Server error |
| 2 | Authentication error | | 7 | Duplicate |
| 3 | Not found | | 130 | Interrupted (SIGINT) |
| 4 | Validation error | | 143 | Terminated (SIGTERM) |

## Development

```bash
cd cli/                        # from the repo root
pip install -e ".[test]"       # install in dev mode with test extras
pytest -q                      # tests
ruff check tcadai_cli/      # lint
```

### Distribution

```bash
make build-binary   # standalone binary into dist/ (PyInstaller)
make build-wheel    # wheel/sdist into dist/
make smoke          # build binary and run --help
```

## Documentation & resources

- [Root README](../README.md): platform overview
- [Backend README](../backend/README.md): the API this CLI talks to
- Hosted app: [app.tcadai.com](https://app.tcadai.com)

## License

MIT License; see [LICENSE](../LICENSE).
