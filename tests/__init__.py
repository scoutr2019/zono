"""Shared test setup: make `src/` importable and keep every test's app data in a temporary folder."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Zono stores its data under %LOCALAPPDATA%\Zono. Tests must never touch a real installation.
TEMP = Path(tempfile.mkdtemp(prefix="zono-tests-"))
os.environ["LOCALAPPDATA"] = str(TEMP)
os.environ.setdefault("APPDATA", str(TEMP))
