"""Config loader — reads config.yaml, validates env vars, model, and endpoint fields."""

import csv
import logging
import os
import sys
from typing import Any

import yaml
from dotenv import load_dotenv

from backend.chat.paths import ALLOWED_MODELS_PATH, CONFIG_PATH, PROJECT_ROOT

log = logging.getLogger(__name__)

PROVIDER_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _require_env(var_name: str) -> None:
    if not os.environ.get(var_name):
        sys.exit(f"Missing env var: {var_name}")


def load_config() -> dict[str, Any]:
    """Load config.yaml and validate env vars and model compatibility."""
    load_dotenv(PROJECT_ROOT / ".env")
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    model: str = cfg["llm"]["model_name"]
    with open(ALLOWED_MODELS_PATH) as f:
        allowed = {row["model"]: row for row in csv.DictReader(f)}

    if model not in allowed:
        sys.exit(f"Model {model!r} is not in allowed_models.csv")

    row = allowed[model]
    if row.get("type") != "text":
        sys.exit(f"Model {model!r} is type={row.get('type')!r}, but backend.chat requires a text model")

    provider = row.get("provider", "")
    if provider not in PROVIDER_ENV:
        sys.exit(f"Model {model!r} has unsupported provider={provider!r} (need openai or anthropic)")

    _require_env(PROVIDER_ENV[provider])
    _require_env(cfg["elyos_api"]["api_key_env"])

    _validate_endpoints(cfg)

    log.info("Config loaded: model=%s provider=%s endpoints=%s", model, provider,
             list(cfg["elyos_api"]["endpoints"].keys()))
    return cfg


def _validate_endpoints(cfg: dict) -> None:
    """Fail fast if any endpoint resilience config is missing or malformed."""
    endpoints = cfg.get("elyos_api", {}).get("endpoints", {})
    if not endpoints:
        sys.exit("config.yaml: elyos_api.endpoints is missing or empty")

    rules: list[tuple[str, type, object]] = [
        ("path",                    str,   None),
        ("timeout_s",               (int, float), 0),
        ("max_concurrent",          int,   1),
        ("rate_limit_group",        str,   None),
        ("max_requests_per_window", int,   1),
        ("window_s",                (int, float), 0),
        ("max_throttle_retries",    int,   0),
        ("max_timeout_retries",     int,   0),
        ("rate_limit_safety_s",     (int, float), 0),
        ("retry_jitter_s",          (int, float), 0),
    ]

    for ep_name, ep_cfg in endpoints.items():
        for field, expected_type, min_val in rules:
            if field not in ep_cfg:
                sys.exit(f"config.yaml: endpoints.{ep_name} missing required field '{field}'")
            val = ep_cfg[field]
            if not isinstance(val, expected_type):
                sys.exit(f"config.yaml: endpoints.{ep_name}.{field} must be {expected_type}, got {type(val)}")
            if isinstance(min_val, (int, float)) and val < min_val:
                sys.exit(f"config.yaml: endpoints.{ep_name}.{field} must be >= {min_val}, got {val}")
            if expected_type is str and not val:
                sys.exit(f"config.yaml: endpoints.{ep_name}.{field} must be non-empty")
