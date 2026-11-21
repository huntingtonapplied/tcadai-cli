# Changelog

All notable changes to the TCAD AI CLI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `login` shares one browser-assisted flow with the other lab CLIs (`_lab_login.py`): press Enter to open the API-key page, paste the key (hidden), verified before it is saved.

### Fixed
- `~/.tcadai/config.yaml` is created owner-only from the first byte (it could be briefly world-readable under a permissive umask).
- Over SSH or with no display, `login` prints the key-page link instead of launching (or blocking on) a browser.
- A key the API rejects with 403 is reported as rejected; `login` warns when `BOLTZMANN_API_KEY` overrides the saved key.

## [1.0.4] - 2026-11-02

### Fixed
- A base URL ending in `/v1` (`BOLTZMANN_API_URL`, `api_url`, `login --url`) no longer produces `/v1/v1/...` 404s: the trailing `/v1` is dropped and `config validate`/`doctor` warn about it.
- `login --key` with a rejected key names the server's reason (for example "Invalid API key") instead of telling you to run `tcadai login`.
- `-o json|yaml` is honoured by `api-keys create/rotate/update/revoke/delete`, `config validate` and `doctor` (yaml) too. In structured mode `api-keys create/rotate` print the API response and never prompt.
- `config show` points a fresh install at `tcadai login` (it said `api-keys create`, which itself needs a key).
- No em dashes in CLI output, help or docs.
- Errors now exit non-zero. One shared handler maps failures to the documented exit codes (auth 2, not found 3, validation 4, network 5, server 6, duplicate 7) for every command; before, 401/404/422/5xx all exited 0.
- `login --key` verifies the key before saving it. A key that fails verification is not written to `~/.tcadai/config.yaml` (a previously saved key stays) and the command exits non-zero.
- `simulations create` takes `--solution-id/--solution` and `--project-id/--project` (or `solution_id`/`project_id` in the `--config` JSON), which the API requires. Missing IDs give a usage message and exit 4 instead of a server 422.
- `jobs list`: the server has no job-listing route yet; the command now says so and points to `jobs status <job_id>` (exit 3) instead of "Resource not found: check the ID". `jobs status` reads the API's `job_id`/`job_type`/`error_message` fields.
- `-o json|yaml` is honoured by the list and status commands (simulations, projects, jobs, auth status, api-keys list/stats).
- `projects list --visibility public|private` now filters (mapped to the API's `is_public`/`include_public`).
- `auth token`: the API has no email/password login route. The command stays, no longer prompts or sends credentials, and explains how to use an API key (`tcadai login --key`), exiting 2.
- The upgrade notice points to the binary installer instead of a pip command.
- install.sh reads the release's SHA256SUMS before downloading and rejects OS/arch pairs with no published binary (Intel macOS, ARM Linux) with a clear "Unsupported platform" message and the list of available builds, instead of a raw curl 404. An unknown `--version` gets a clear "release not found".
- `config validate` exits non-zero when the API is unreachable or unhealthy.

## [1.0.3] - 2026-10-14

### Fixed
- The update check no longer queries PyPI. `tcadai-cli` is not published there and the PyPI name may belong to an unrelated project, so the old check could report a stranger's version and suggest installing it. It now reads the latest GitHub release of huntingtonapplied/tcadai-cli and suggests `pip install --upgrade git+https://github.com/huntingtonapplied/tcadai-cli`, only when that release is newer.

## [1.0.2] - 2026-10-13

### Changed
- README: describes the hosted API only (removed the self-hosted backend wording; the backend is not distributed).

## [1.1.0] - Unreleased

### Added
- `--output/-o {table,json,yaml}` global flag for output format
- `--no-color` flag (also honors the `NO_COLOR` env var)
- `--verbose/-v` flag for INFO-level logging to stderr
- `--debug` flag for DEBUG-level logging (HTTP requests)
- `--ci` flag for CI/CD usage (no color, no spinners, no prompts); auto-detected from `CI`, `GITHUB_ACTIONS`, `GITLAB_CI`
- `tcadai doctor` command: checks Python, config, API connectivity, auth, and shell completion
- `tcadai completion` command: generate/install shell completion for bash, zsh, fish
- Distinct exit codes: 2 (auth), 3 (not found), 4 (validation), 5 (network), 6 (server), 7 (duplicate), 130 (SIGINT), 143 (SIGTERM)
- Config validation with typo detection (`did you mean 'api_key'?`) on startup
- SIGTERM signal handling across all commands (clean exit with code 143)
- Top-level KeyboardInterrupt handler as a safety net for all commands
- Non-blocking version update check (background thread, 24h throttle, disabled in CI; disable with `BOLTZMANN_NO_UPDATE_CHECK`)
- Infra modules `exit_codes.py`, `log.py`, `output.py`, `update_check.py`
- Standalone binary + wheel packaging (`Makefile`, `scripts/`), SEGA publish docs (`.sega/README.md`)
- Test suite (`tests/`) with pytest

### Changed
- Entry point now wraps the CLI group with signal/exception handling (`tcadai_cli.main:main`)
- Version is derived from package metadata (`importlib.metadata`) instead of being hardcoded
- Logging now routes through the `tcadai` logger to stderr (keeps stdout clean for piped output)

## [1.0.0] - 2026-01-01

### Added
- Initial release with `login`, `simulations`, `projects`, `jobs`, `config`, `auth`, and `api-keys` commands
- Tabular output via `tabulate`
- Retry logic with exponential backoff for transient HTTP errors (429, 500, 502, 503, 504) and network failures; configurable via `BOLTZMANN_MAX_RETRIES`
- Bearer (JWT) and ApiKey authentication schemes
