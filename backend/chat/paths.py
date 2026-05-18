from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent.parent
CONFIG_PATH = PACKAGE_DIR / "config.yaml"
ALLOWED_MODELS_PATH = PROJECT_ROOT / "backend" / "reference_docs" / "allowed_models.csv"
