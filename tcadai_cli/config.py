"""Configuration management: reads and writes ~/.tcadai/config.yaml."""

import os
import stat
from pathlib import Path
from typing import Optional

import yaml

from tcadai_cli._lab_login import write_private_file

CONFIG_DIR = Path.home() / ".tcadai"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

DEFAULT_API_URL = os.getenv("BOLTZMANN_API_URL", "https://api.tcadai.com")


def _ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict):
    # Owner-only from the first byte (temp file 0600 then atomic rename; dir 0700): the
    # file holds the API key, so there is no window where a loose umask makes it 0644.
    write_private_file(CONFIG_FILE, yaml.safe_dump(config, default_flow_style=False))


def get_api_key() -> Optional[str]:
    return os.environ.get("BOLTZMANN_API_KEY") or load_config().get("api_key")


def normalize_api_url(url: str) -> str:
    """Return the API origin the CLI joins its request paths onto.

    Every request path already starts with /v1 (the backend mounts the API at /v1 and
    /health at the root), so a base URL ending in /v1 (BOLTZMANN_API_URL, config
    api_url or login --url) produced /v1/v1/... and every command 404'd, login
    included (HQ2-API-PREFIX). A trailing /v1 is dropped; any other path is kept.
    """
    url = (url or "").strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[: -len("/v1")].rstrip("/")
    return url


def get_api_url() -> str:
    return normalize_api_url(
        os.environ.get("BOLTZMANN_API_URL") or load_config().get("api_url", DEFAULT_API_URL)
    )


def set_api_key(key: str):
    config = load_config()
    config["api_key"] = key
    save_config(config)


def set_api_url(url: str):
    config = load_config()
    config["api_url"] = url
    save_config(config)


KNOWN_CONFIG_KEYS = {"api_key", "api_url", "timeout", "last_update_check"}


def validate_config(config: dict) -> list:
    """Return a list of warning messages for invalid config entries."""
    warnings = []
    for key in config:
        if key not in KNOWN_CONFIG_KEYS:
            from difflib import get_close_matches
            matches = get_close_matches(key, KNOWN_CONFIG_KEYS, n=1, cutoff=0.5)
            msg = f"Unknown config key: '{key}'"
            if matches:
                msg += f" (did you mean '{matches[0]}'?)"
            warnings.append(msg)
    if "api_url" in config:
        url = config["api_url"]
        if isinstance(url, str) and not (url.startswith("http://") or url.startswith("https://")):
            warnings.append("api_url should start with http:// or https://")
        elif isinstance(url, str) and url.strip().rstrip("/").endswith("/v1"):
            warnings.append(
                "api_url should not end in /v1 (the CLI adds /v1 itself; the trailing /v1 is ignored)"
            )
    return warnings
