"""Configuration: load .env once and expose the model name and project paths.

Everything else imports from here, so paths and settings live in one place.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# src/homebuyer_agent/config.py -> parents[2] is the repo root.
ROOT: Path = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR: Path = ROOT / "data"
EVAL_DIR: Path = DATA_DIR / "eval"
KB_DIR: Path = DATA_DIR / "knowledge_base"
LISTINGS_PATH: Path = DATA_DIR / "listings.json"
RESULTS_DIR: Path = ROOT / "results"
PROMPTS_DIR: Path = Path(__file__).resolve().parent / "prompts"


def get_model() -> str:
    """Return the OpenAI model name from the OPENAI_MODEL env var.

    Raises a clear error instead of silently falling back to a hard-coded model.
    """
    model = os.getenv("OPENAI_MODEL")
    if not model:
        raise RuntimeError("OPENAI_MODEL is not set. Add it to your .env file (see .env.example).")
    return model
