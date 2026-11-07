"""Build Zono.exe by putting the current source files into an existing Zono release.

A Zono release is a small Windows launcher with an embedded Python, Pillow and the VLC engine, plus a zip with
Zono's own files. This script swaps that zip for the files in `src/`, sets the version number, and (optionally)
writes the app icons from `src/zono_mark.png`. It runs on any OS:

    pip install pefile pillow
    python tools/build_exe.py --base Zono-2_1_1.exe --old-version 2.1.1 --version 2.1.2 --icons

The base exe is any earlier release (see the GitHub Releases page); it is not stored in this repository.
"""
import argparse
import io
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FILES = ["app.py", "ui.py", "catalogue.py", "player.py", "qr.py", "remote.py", "cast.py", "tmdb.py", "webview.py",
         "countries.py", "Zono.ico", "zono_logo.png", "zono_mark.png"]
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


def swap_files(base):
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
        for name in FILES:
            new.write(SRC / name, name)
        for info in old.infolist():  # Python, Pillow, VLC: unchanged
            if info.filename not in FILES:
                new.writestr(info, old.read(info.filename))
    packed = output.getvalue()
    if len(packed) > room:
        sys.exit(f"De nieuwe bestanden passen niet in de basis-exe ({len(packed)} > {room} bytes).")
    base[ZIP_SIZE_AT:ZIP_SIZE_AT + 4] = struct.pack("<I", len(packed))
    base[ZIP_SIZE_AT + 4:ZIP_SIZE_AT + 4 + room] = packed + b"\0" * (room - len(packed))


def write_icons(data):
    """Append new PNG icons (16-256 px) to the resource section and point the icon group at them."""
    import pefile
    from PIL import Image
    pe = pefile.PE(data=bytes(data))
    section = pe.sections[-1]
    if not section.Name.startswith(b".rsrc"):
        sys.exit("De laatste sectie van de exe is geen .rsrc: iconen niet aangepast.")
    mark = Image.open(SRC / "zono_mark.png").convert("RGBA")
    file_align, section_align = pe.OPTIONAL_HEADER.FileAlignment, pe.OPTIONAL_HEADER.SectionAlignment
    blob, base_raw = bytearray(), section.SizeOfRawData
    base_rva = section.VirtualAddress + base_raw
    sizes = {2: 16, 3: 24, 4: 32, 5: 48, 6: 64, 7: 128, 8: 256}
    lengths, group = {}, None
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.id == 3:  # RT_ICON
            for icon in entry.directory.entries:
                png = io.BytesIO()
                mark.resize((sizes[icon.id],) * 2, Image.LANCZOS).save(png, "PNG", optimize=True)
                png = png.getvalue()
                record = icon.directory.entries[0].data.struct
                record.OffsetToData, record.Size = base_rva + len(blob), len(png)
                lengths[icon.id] = len(png)
                blob += png + b"\0" * ((-len(png)) % 8)
        if entry.id == 14:  # RT_GROUP_ICON
            record = entry.directory.entries[0].directory.entries[0].data.struct
            group = pe.get_offset_from_rva(record.OffsetToData)
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
    parser.add_argument("--out", help="output file (default: dist/Zono-<version>.exe)")
    args = parser.parse_args()

    source_version = next((line.split('"')[1] for line in (SRC / "app.py").read_text(encoding="utf-8").splitlines()
                           if line.startswith("VERSION = ")), "")
    if source_version != args.version:
        sys.exit(f"src/app.py heeft VERSION = \"{source_version}\", niet {args.version}. Pas dat eerst aan.")
    data = bytearray(Path(args.base).read_bytes())
    swap_files(data)
    replace_once(data, args.old_version, args.version)
    replace_once(data, package_name(args.old_version), package_name(args.version))
    if args.icons:
        data = write_icons(data)
    data = checksum(data)
    out = Path(args.out) if args.out else ROOT / "dist" / f"Zono-{args.version.replace('.', '_')}.exe"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"{out}  ({len(data) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
