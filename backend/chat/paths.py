from pathlib import Path

PACKAGE_DIR: Path = Path(__file__).resolve().parent
PROJECT_ROOT: Path = PACKAGE_DIR.parent.parent
CONFIG_PATH: Path = PACKAGE_DIR / "config.yaml"
ALLOWED_MODELS_PATH: Path = PROJECT_ROOT / "backend" / "reference_docs" / "allowed_models.csv"
