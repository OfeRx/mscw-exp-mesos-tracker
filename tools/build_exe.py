"""Builds MapleTracker.exe with PyInstaller, so friends can run the tracker without Python:

    .venv\\Scripts\\python.exe -m pip install pyinstaller
    .venv\\Scripts\\python.exe tools\\build_exe.py

The result is dist\\MapleTracker\\ (MapleTracker.exe and what it needs; unzip and run) and
dist\\MapleTracker-<version>-windows.zip to hand out. A folder rather than one big .exe: a
single-file build unpacks itself on every start (slow) and upsets antivirus programs more often."""
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from maple_tracker import __version__  # noqa: E402

BUILD, DIST = ROOT / "build", ROOT / "dist"
NAME = "MapleTracker"

QUICK_START = f"""Maple Tracker {__version__}
=================

An EXP, meso and potion tracker overlay for MapleStory Classic World.

1. Double-click {NAME}.exe. Windows may say "Windows protected your PC" the first time, since
   the program isn't signed: click "More info", then "Run anyway".
2. On its first start it downloads the potion, food and EXP table data (a few seconds).
3. Press Start, open your inventory on the Use tab once, and play.

Play in windowed or borderless mode. Your sessions and settings are kept in the "data" folder
next to {NAME}.exe: keep it when you update to a newer version.

It only reads the screen: it never touches the game's memory, files or network, and never sends
keys or clicks. Not made or reviewed by Nexon: use it at your own risk.
"""


def icon(path):
    """A gold meso coin, like the one in the overlay's header."""
    big = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.ellipse((12, 12, 244, 244), fill=(240, 176, 48, 255), outline=(122, 76, 16, 255), width=14)
    d.ellipse((70, 70, 186, 186), outline=(255, 226, 140, 255), width=14)
    big.save(path, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])


def main():
    import PyInstaller.__main__

    BUILD.mkdir(exist_ok=True)
    ico = BUILD / "icon.ico"
    icon(ico)
    PyInstaller.__main__.run([
        str(ROOT / "tools" / "launch.py"),
        "--name", NAME,
        "--onedir", "--noconsole", "--noconfirm", "--clean",
        "--icon", str(ico),
        "--paths", str(ROOT),
        "--add-data", f"{ROOT / 'maple_tracker' / 'assets'};maple_tracker/assets",
        "--exclude-module", "pytest",
        "--exclude-module", "pyflakes",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
    ])
    app = DIST / NAME
    # OpenCV's video plugin is the biggest file in the build, and the tracker never uses video.
    for dll in app.rglob("opencv_videoio_ffmpeg*.dll"):
        dll.unlink()
    (app / "README.txt").write_text(QUICK_START, "utf-8")

    archive = DIST / f"{NAME}-{__version__}-windows.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(app.rglob("*")):
            if "data" in f.relative_to(app).parts[:1]:
                continue                        # never ship anyone's own sessions or settings
            z.write(f, Path(NAME) / f.relative_to(app))
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
    print(f"\nBuilt {app} ({size / 1e6:.0f} MB) and {archive.name} ({archive.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
