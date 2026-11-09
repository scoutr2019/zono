"""Build Zono.exe by putting the current source files into an existing Zono release.

A Zono release is a small Windows launcher with an embedded Python, Pillow and the VLC engine, plus a zip with
Zono's own files. This script swaps that zip for the files in `src/`, sets the version number, and (optionally)
writes the app icons from `src/zono_mark.png`. It runs on any OS:

    pip install pefile pillow
    python tools/build_exe.py --base Zono-2_1_1.exe --old-version 2.1.1 --version 2.1.2 --python <python3.14>

The base exe is any earlier release (see the GitHub Releases page); it is not stored in this repository.

The app ships as compiled Python (.pyc) instead of readable source: `--python` must point at the same Python
version as the one inside the exe (3.14), because .pyc files only load in the version that made them.
`--readable` ships the plain .py files instead (for debugging).
"""
import argparse
import io
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
MODULES = ["app.py", "ui.py", "catalogue.py", "player.py", "qr.py", "remote.py", "cast.py", "tmdb.py", "webview.py",
           "countries.py", "i18n.py", "netfix.py", "updater.py"]
ASSETS = ["Zono.ico", "zono_logo.png", "zono_mark.png", "locale/en.json", "locale/fr.json", "locale/de.json"]
RUNTIME_PYTHON = "3.14"
STUB = ('# Zono. The app itself is in zono_main.pyc; the source code is at github (see the README).\n'
        'import runpy\nrunpy.run_module("zono_main", run_name="__main__")\n')
COMPILE = """
import py_compile, sys
for source, target in zip(sys.argv[1::2], sys.argv[2::2]):
    name = "zono/" + source.replace(chr(92), "/").rsplit("/", 1)[-1]  # no build-machine paths in error reports
    py_compile.compile(source, cfile=target, dfile=name, doraise=True, optimize=2)
"""
ZIP_SIZE_AT = 1360  # the launcher stores the size of its zip here, the zip itself follows


def package_name(version):
    return "ZonoPackage" + version.replace(".", "")


def replace_once(buffer, old, new):
    old_bytes, new_bytes = old.encode("utf-16-le"), new.encode("utf-16-le")
    if buffer.count(old_bytes) != 1:
        sys.exit(f"'{old}' komt niet precies één keer voor in de basis-exe (verkeerde --old-version?)")
    if len(old_bytes) != len(new_bytes):
        # the launcher stores these strings in fixed-size slots: pad a shorter version with spaces is not safe
        sys.exit(f"Versie '{new}' moet even lang zijn als '{old}' (bijvoorbeeld 2.1.1 -> 2.1.2).")
    index = buffer.index(old_bytes)
    buffer[index:index + len(old_bytes)] = new_bytes


def app_files(python, readable):
    """{name in the exe: bytes} for Zono's own files."""
    files = {name: (SRC / name).read_bytes() for name in ASSETS}
    if readable:
        files.update({name: (SRC / name).read_bytes() for name in MODULES})
        return files
    version = subprocess.run([python, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], capture_output=True,
                             text=True, check=True).stdout.strip()
    if version != RUNTIME_PYTHON:
        sys.exit(f"--python is Python {version}; de exe gebruikt Python {RUNTIME_PYTHON}.")
    with tempfile.TemporaryDirectory() as folder:
        pairs = []
        for name in MODULES:
            target = "zono_main.pyc" if name == "app.py" else name[:-3] + ".pyc"
            pairs += [str(SRC / name), str(Path(folder) / target)]
        subprocess.run([python, "-c", COMPILE, *pairs], check=True)
        for target in pairs[1::2]:
            files[Path(target).name] = Path(target).read_bytes()
    files["app.py"] = STUB.encode("utf-8")  # the launcher runs app.py
    return files


def swap_files(base, files):
    size = struct.unpack("<I", base[ZIP_SIZE_AT:ZIP_SIZE_AT + 4])[0]
    old = zipfile.ZipFile(io.BytesIO(bytes(base[ZIP_SIZE_AT + 4:ZIP_SIZE_AT + 4 + size])))
    # The zip is a resource of the .NET launcher. Earlier builds may have left it smaller than its slot: the
    # free room is the run of zero bytes up to the launcher's metadata that follows it.
    end = ZIP_SIZE_AT + 4 + size
    while end < len(base) and base[end] == 0:
        end += 1
    room = max(size, end - (ZIP_SIZE_AT + 4) - 4)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as new:
        for name, content in files.items():
            new.writestr(name, content)
        ours = {info.filename for info in old.infolist()
                if "/" not in info.filename or info.filename.startswith("locale/")}  # Zono's files of the old build
        for info in old.infolist():  # Python, Pillow, VLC: unchanged
            if info.filename not in files and info.filename not in ours:
                new.writestr(info, old.read(info.filename))
    packed = output.getvalue()
    if len(packed) > room:
        sys.exit(f"De nieuwe bestanden passen niet in de basis-exe ({len(packed)} > {room} bytes).")
    base[ZIP_SIZE_AT:ZIP_SIZE_AT + 4] = struct.pack("<I", len(packed))
    base[ZIP_SIZE_AT + 4:ZIP_SIZE_AT + 4 + room] = packed + b"\0" * (room - len(packed))


def _pad4(raw):
    return raw + b"\0" * ((-len(raw)) % 4)


def _block(key, value=b"", text=True, children=()):
    """One node of a Windows VS_VERSIONINFO tree: length, value length, type, key, value, children (4-byte aligned)."""
    value_length = len(value) // 2 if text else len(value)
    raw = _pad4(struct.pack("<HHH", 0, value_length, 1 if text else 0) + (key + "\0").encode("utf-16-le")) + value
    for child in children:
        raw = _pad4(raw) + child
    return struct.pack("<H", len(raw)) + raw[2:]


def version_info(version):
    """VS_VERSIONINFO with Zono's name and version: Task Manager and file properties show "Zono"."""
    numbers = [int(n) for n in (version.split(".") + ["0", "0", "0"])[:4]]
    high, low = numbers[0] << 16 | numbers[1], numbers[2] << 16 | numbers[3]
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x00010000, high, low, high, low, 0x3F, 0, 0x00040004, 1, 0, 0, 0)
    strings = {"CompanyName": "Zono TV", "FileDescription": "Zono", "FileVersion": version,
               "InternalName": "Zono", "LegalCopyright": "\u00a9 2026 Zono TV", "OriginalFilename": "Zono.exe",
               "ProductName": "Zono", "ProductVersion": version}
    table = [_block(k, (v + "\0").encode("utf-16-le")) for k, v in strings.items()]
    string_info = _block("StringFileInfo", children=[_block("000004b0", children=table)])
    var_info = _block("VarFileInfo", children=[_block("Translation", struct.pack("<HH", 0, 0x04B0), text=False)])
    return _block("VS_VERSION_INFO", fixed, text=False, children=[string_info, var_info])


def write_resources(data, icons=False, version=None):
    """Append new resources to the resource section and point the resource table at them:
    PNG icons (16-256 px) from src/zono_mark.png and/or a version block with the name "Zono"."""
    import pefile
    pe = pefile.PE(data=bytes(data))
    section = pe.sections[-1]
    if not section.Name.startswith(b".rsrc"):
        sys.exit("De laatste sectie van de exe is geen .rsrc: bronnen niet aangepast.")
    file_align, section_align = pe.OPTIONAL_HEADER.FileAlignment, pe.OPTIONAL_HEADER.SectionAlignment
    blob, base_raw = bytearray(), section.SizeOfRawData
    base_rva = section.VirtualAddress + base_raw

    def add(record, raw):
        nonlocal blob
        record.OffsetToData, record.Size = base_rva + len(blob), len(raw)
        blob += raw + b"\0" * ((-len(raw)) % 8)
    lengths, group = {}, None
    if icons:
        from PIL import Image
        mark = Image.open(SRC / "zono_mark.png").convert("RGBA")
        sizes = {2: 16, 3: 24, 4: 32, 5: 48, 6: 64, 7: 128, 8: 256}
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if icons and entry.id == 3:  # RT_ICON
            for icon in entry.directory.entries:
                png = io.BytesIO()
                mark.resize((sizes[icon.id],) * 2, Image.LANCZOS).save(png, "PNG", optimize=True)
                lengths[icon.id] = len(png.getvalue())
                add(icon.directory.entries[0].data.struct, png.getvalue())
        if icons and entry.id == 14:  # RT_GROUP_ICON
            record = entry.directory.entries[0].directory.entries[0].data.struct
            group = pe.get_offset_from_rva(record.OffsetToData)
        if version and entry.id == 16:  # RT_VERSION
            add(entry.directory.entries[0].directory.entries[0].data.struct, version_info(version))
    blob += b"\0" * ((-len(blob)) % file_align)
    for k in range(len(lengths)):
        at = group + 6 + k * 14
        icon_id = struct.unpack("<H", pe.__data__[at + 12:at + 14])[0]
        pe.set_dword_at_offset(at + 8, lengths[icon_id])
    section.SizeOfRawData = base_raw + len(blob)
    section.Misc_VirtualSize = section.SizeOfRawData
    pe.OPTIONAL_HEADER.SizeOfImage = (section.VirtualAddress + section.Misc_VirtualSize + section_align - 1) \
        // section_align * section_align
    pe.OPTIONAL_HEADER.DATA_DIRECTORY[2].Size = section.Misc_VirtualSize
    return bytearray(pe.write()) + blob


def checksum(data):
    import pefile
    pe = pefile.PE(data=bytes(data))
    pe.OPTIONAL_HEADER.CheckSum = pe.generate_checksum()
    return pe.write()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="an earlier Zono release (.exe)")
    parser.add_argument("--old-version", required=True, help="version of the base exe, e.g. 2.1.1")
    parser.add_argument("--version", required=True, help="new version, e.g. 2.1.2 (same length as the old one)")
    parser.add_argument("--icons", action="store_true", help="also write the icons from src/zono_mark.png")
    parser.add_argument("--python", help=f"Python {RUNTIME_PYTHON} used to compile the app (default: this Python)")
    parser.add_argument("--readable", action="store_true", help="ship readable .py files instead of compiled ones")
    parser.add_argument("--out", help="output file (default: dist/Zono-<version>.exe)")
    args = parser.parse_args()

    source_version = next((line.split('"')[1] for line in (SRC / "app.py").read_text(encoding="utf-8").splitlines()
                           if line.startswith("VERSION = ")), "")
    if source_version != args.version:
        sys.exit(f"src/app.py heeft VERSION = \"{source_version}\", niet {args.version}. Pas dat eerst aan.")
    data = bytearray(Path(args.base).read_bytes())
    swap_files(data, app_files(args.python or sys.executable, args.readable))
    replace_once(data, args.old_version, args.version)
    replace_once(data, package_name(args.old_version), package_name(args.version))
    data = write_resources(data, icons=args.icons, version=args.version)
    data = checksum(data)
    out = Path(args.out) if args.out else ROOT / "dist" / f"Zono-{args.version.replace('.', '_')}.exe"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"{out}  ({len(data) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
