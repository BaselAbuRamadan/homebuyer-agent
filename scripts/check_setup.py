"""Milestone 0 sanity check. Run: python scripts/check_setup.py"""
import importlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def report(passed: bool, label: str, hint: str = "") -> None:
    global ok
    ok &= passed
    print(("✅ " if passed else "❌ ") + label + ("" if passed or not hint else f"\n   → {hint}"))


report(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]} (need 3.11+)", "Install Python 3.11 or newer")

for pkg in ["openai", "pydantic", "dotenv", "rank_bm25", "streamlit", "pandas", "phoenix", "pytest"]:
    try:
        importlib.import_module(pkg)
        report(True, f"package: {pkg}")
    except ImportError:
        report(False, f"package: {pkg}", "Activate .venv and run: pip install -r requirements-dev.txt")

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

key = os.getenv("OPENAI_API_KEY", "")
report(key.startswith("sk-") and not key.startswith("sk-ant-") and len(key) > 40,
       "OPENAI_API_KEY looks like an OpenAI key",
       "Put your OpenAI key in .env (an Anthropic key starts with sk-ant- and won't work here)")
report(bool(os.getenv("OPENAI_MODEL")), f"OPENAI_MODEL set ({os.getenv('OPENAI_MODEL')})", "Set OPENAI_MODEL in .env")

smart = os.getenv("SMART_MODEL")
print(f"   SMART_MODEL: {smart} (used when needed)" if smart else "   SMART_MODEL not set: everything runs on OPENAI_MODEL")

listings = json.loads((ROOT / "data/listings.json").read_text(encoding="utf-8"))["listings"]
report(len(listings) > 0, f"data/listings.json ({len(listings)} sample listings)")
kb = list((ROOT / "data/knowledge_base").glob("*.md"))
report(len(kb) > 0, f"knowledge base ({len(kb)} guides)")

try:
    urllib.request.urlopen(os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006"), timeout=3)
    report(True, "Phoenix reachable at http://localhost:6006")
except Exception:
    report(False, "Phoenix reachable", "In another terminal run: phoenix serve")

if key.startswith("sk-") and "--skip-api" not in sys.argv:
    from openai import OpenAI
    # Check every model the project uses, so a typo in a model name shows up here, not live.
    models = dict.fromkeys(m for m in (os.getenv("OPENAI_MODEL"), smart, os.getenv("JUDGE_MODEL")) if m)
    for model in models:
        try:
            r = OpenAI().chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with the single word: ready"}],
                max_tokens=5,
            )
            report(True, f"OpenAI API call works with {model} → {r.choices[0].message.content!r}")
        except Exception as e:
            report(False, f"OpenAI API call with {model}",
                   f"{type(e).__name__}: {e}. Check the key, billing credit and model name.")

print("\nAll good." if ok else "\nFix the ❌ items above, then re-run.")
