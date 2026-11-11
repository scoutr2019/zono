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
# never talk to the real zono.be from tests
os.environ["ZONO_SYNC_API"] = "http://127.0.0.1:9/api/sync.php"


def fresh_ui():
    """Each UI test makes its own Tk window: pictures cached for an earlier window cannot be reused."""
    import ui
    for value in vars(ui).values():
        if callable(getattr(value, "cache_clear", None)):
            value.cache_clear()
