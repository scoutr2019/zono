"""Shared test setup: make `src/` importable and keep every test's app data in a temporary folder."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("ZONO_SRC") or ROOT / "src")  # ZONO_SRC: test a compiled build instead
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Zono stores its data under %LOCALAPPDATA%\Zono. Tests must never touch a real installation.
TEMP = Path(tempfile.mkdtemp(prefix="zono-tests-"))
os.environ["LOCALAPPDATA"] = str(TEMP)
os.environ.setdefault("APPDATA", str(TEMP))
# Tests read Dutch texts unless a run asks for another language (ZONO_LANGUAGE=fr …).
os.environ.setdefault("ZONO_LANGUAGE", "nl")
