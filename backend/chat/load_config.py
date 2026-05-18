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
    log.info("Config loaded: model=%s provider=%s", model, provider)
    return cfg
