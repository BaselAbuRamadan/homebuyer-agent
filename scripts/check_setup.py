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

for pkg in ["openai", "pydantic", "dotenv", "pandas", "rank_bm25", "phoenix", "pytest"]:
    try:
        importlib.import_module(pkg)
        report(True, f"package: {pkg}")
    except ImportError:
        report(False, f"package: {pkg}", "Activate .venv and run: pip install -r requirements.txt")

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

listings = json.loads((ROOT / "data/listings.json").read_text())["listings"]
report(len(listings) > 0, f"data/listings.json ({len(listings)} fictional listings)")
kb = list((ROOT / "data/knowledge_base").glob("*.md"))
report(len(kb) > 0, f"knowledge base ({len(kb)} guides)")

try:
    urllib.request.urlopen(os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006"), timeout=3)
    report(True, "Phoenix reachable at http://localhost:6006")
except Exception:
    report(False, "Phoenix reachable", "In another terminal run: phoenix serve")

if key.startswith("sk-") and "--skip-api" not in sys.argv:
    try:
        from openai import OpenAI
        r = OpenAI().chat.completions.create(
            model=os.getenv("OPENAI_MODEL"),
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            max_tokens=5,
        )
        report(True, f"OpenAI API call works → {r.choices[0].message.content!r}")
    except Exception as e:
        report(False, "OpenAI API call", f"{type(e).__name__}: {e}. Check the key, billing credit and model name.")

print("\nAll good. Start Milestone 1." if ok else "\nFix the ❌ items above, then re-run.")
