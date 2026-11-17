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


def get_smart_model() -> str:
    """The stronger model the agent switches to WHEN NEEDED: SMART_MODEL if set, else OPENAI_MODEL.

    Everyday questions use the cheap OPENAI_MODEL. The planner switches to this model
    for multi-step requests, or retries with it when a cheap attempt fails a check
    (see planner.choose_model and planner.retry_reason). If SMART_MODEL is not set,
    everything simply runs on OPENAI_MODEL.
    """
    return os.getenv("SMART_MODEL") or get_model()


def get_judge_model() -> str:
    """Model used by the LLM-as-judge: JUDGE_MODEL if set, otherwise OPENAI_MODEL.

    A different (ideally stronger) judge model reduces "self-preference": a model
    tends to rate its own style of answer a little too kindly.
    """
    return os.getenv("JUDGE_MODEL") or get_model()
