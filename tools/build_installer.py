"""Build Zono-Setup.exe (the installer) around a built Zono.exe, with NSIS (free; also runs on Linux and macOS).

    python tools/build_installer.py dist/Zono.exe            -> dist/Zono-Setup.exe
    python tools/build_installer.py dist/Zono.exe --out X.exe

Needs `makensis` (Windows: https://nsis.sourceforge.io, Linux: apt install nsis). The version is read from src/app.py.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exe", help="the built Zono.exe")
    parser.add_argument("--out", help="output file (default: Zono-Setup.exe next to the exe)")
    args = parser.parse_args()
    makensis = shutil.which("makensis")
    if not makensis:
        sys.exit("makensis niet gevonden: installeer NSIS (Windows: nsis.sourceforge.io, Linux: apt install nsis).")
    version = next(line.split('"')[1] for line in (ROOT / "src" / "app.py").read_text(encoding="utf-8").splitlines()
                   if line.startswith("VERSION = "))
    exe = Path(args.exe).resolve()
    out = Path(args.out).resolve() if args.out else exe.with_name("Zono-Setup.exe")
    subprocess.run([makensis, "-V2", "-INPUTCHARSET", "UTF8", f"-DVERSION={version}", f"-DAPP_EXE={exe}",
                    f"-DOUT={out}", "zono.nsi"], cwd=ROOT / "installer", check=True)
    print(f"{out}  ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
