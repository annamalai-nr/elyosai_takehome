import csv
import os
import sys
from typing import Any

import yaml
from dotenv import load_dotenv

from backend.chat.paths import ALLOWED_MODELS_PATH, CONFIG_PATH, PROJECT_ROOT


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
    if row.get("provider") != "openai":
        sys.exit(
            f"Model {model!r} is provider={row.get('provider')!r}, but backend.chat currently uses the OpenAI SDK "
            f"path only. Add an Anthropic/Gemini client path before selecting this model."
        )
    api_key_var = cfg["elyos_api"]["api_key_env"]
    if not os.environ.get(api_key_var):
        sys.exit(f"Missing env var: {api_key_var}")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("Missing env var: OPENAI_API_KEY")
    return cfg
