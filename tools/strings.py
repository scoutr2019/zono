"""List every text that goes through T() and check the translation files.

    python tools/strings.py            report missing/unused translations per language
    python tools/strings.py --dump     print all source texts as JSON
"""
import ast
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
EXTRA = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag", "Overige", "Seizoen {}",
         "Aflevering {}"]


def texts():
    found = dict.fromkeys(EXTRA)
    for path in sorted(SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "T" and node.args \
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                found[node.args[0].value] = None
    sys.path.insert(0, str(SRC))
    import countries
    for value in countries.COUNTRIES.values():
        found[value[0]] = None
    return list(found)


def main():
    source = texts()
    if "--dump" in sys.argv:
        print(json.dumps(source, ensure_ascii=True, indent=0))
        return
    bad = 0
    for path in sorted((SRC / "locale").glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        missing = [t for t in source if t not in table]
        unused = [t for t in table if t not in source]
        wrong = [t for t in source if t in table and t.count("{}") != table[t].count("{}")]
        print(f"{path.stem}: {len(table)} vertalingen, {len(missing)} ontbreken, {len(unused)} ongebruikt, "
              f"{len(wrong)} met verkeerde {{}}")
        for t in missing[:20] + wrong[:20]:
            print("   ", repr(t))
        bad += len(missing) + len(wrong)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
