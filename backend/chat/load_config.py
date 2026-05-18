import csv
import os
import sys

import yaml
from dotenv import load_dotenv

from backend.chat.paths import ALLOWED_MODELS_PATH, CONFIG_PATH, PROJECT_ROOT


def load_config():
    load_dotenv(PROJECT_ROOT / ".env")
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    model = cfg["llm"]["model_name"]
    with open(ALLOWED_MODELS_PATH) as f:
        rows = {row["model"]: row for row in csv.DictReader(f)}
    if model not in rows:
        sys.exit(f"Model {model!r} not in allowed_models.csv")
    if rows[model].get("type") != "text":
        sys.exit(f"Model {model!r} is type={rows[model].get('type')!r}, not 'text'")
    if rows[model].get("provider") != "openai":
        sys.exit(f"Model {model!r} is provider={rows[model].get('provider')!r}; only OpenAI models supported")
    api_key_var = cfg["elyos_api"]["api_key_env"]
    if not os.environ.get(api_key_var):
        sys.exit(f"Missing env var: {api_key_var}")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("Missing env var: OPENAI_API_KEY")
    return cfg
