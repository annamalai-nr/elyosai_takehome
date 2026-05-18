import csv
import os
import sys
from typing import Any

import yaml
from dotenv import load_dotenv

from backend.chat.paths import ALLOWED_MODELS_PATH, CONFIG_PATH, PROJECT_ROOT

PROVIDER_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def load_config() -> dict[str, Any]:
    """Load config.yaml and validate env vars and model compatibility."""
    load_dotenv(PROJECT_ROOT / ".env")
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    model = cfg["llm"]["model_name"]
    with open(ALLOWED_MODELS_PATH) as f:
        rows = {row["model"]: row for row in csv.DictReader(f)}
    if model not in rows:
        sys.exit(f"Model {model!r} is not in allowed_models.csv")
    row = rows[model]
    if row.get("type") != "text":
        sys.exit(f"Model {model!r} is type={row.get('type')!r}, but backend.chat currently requires a text model")
    provider = row.get("provider")
    if provider not in PROVIDER_ENV:
        sys.exit(
            f"Model {model!r} is provider={provider!r}, but backend.chat currently supports only "
            f"OpenAI and Anthropic through LiteLLM"
        )
    env_var = PROVIDER_ENV[provider]
    if not os.environ.get(env_var):
        sys.exit(f"Missing env var: {env_var}")
    api_key_var = cfg["elyos_api"]["api_key_env"]
    if not os.environ.get(api_key_var):
        sys.exit(f"Missing env var: {api_key_var}")
    return cfg
