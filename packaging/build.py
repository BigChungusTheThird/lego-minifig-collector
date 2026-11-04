"""Build a stand-alone app with PyInstaller.

    python packaging/build.py

Windows -> dist/DC-Minifig-Checkliste.exe   (one file)
macOS   -> dist/DC-Minifig-Checkliste.app   (app bundle)
Linux   -> dist/DC-Minifig-Checkliste       (one file)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dcchecklist.config import APP_SLUG, APP_VERSION  # noqa: E402
from dcchecklist.icon import make_icon  # noqa: E402


def main() -> int:
    pk = ROOT / "packaging"
    icon_png = pk / "icon.png"
    make_icon(1024).save(icon_png)
    icon = icon_png
    if sys.platform == "win32":
        icon = pk / "icon.ico"
        make_icon(256).save(icon, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                         (128, 128), (256, 256)])

    args = [
        sys.executable, "-m", "PyInstaller", str(ROOT / "app.py"),
        "--name", APP_SLUG,
        "--noconfirm", "--clean", "--windowed",
        "--icon", str(icon),
        "--collect-data", "customtkinter",
        "--hidden-import", "PIL._tkinter_finder",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    try:
        import curl_cffi  # noqa: F401
        args += ["--collect-all", "curl_cffi"]
    except Exception:
        pass
    if sys.platform == "darwin":
        args += ["--osx-bundle-identifier", "de.dcchecklist.app"]
    else:
        args += ["--onefile"]
    print(" ".join(args), flush=True)
    subprocess.check_call(args)

    if sys.platform == "darwin":
        plist = ROOT / "dist" / f"{APP_SLUG}.app" / "Contents" / "Info.plist"
        if plist.exists():
            import plistlib
            data = plistlib.loads(plist.read_bytes())
            data.update({"CFBundleShortVersionString": APP_VERSION, "CFBundleVersion": APP_VERSION,
                         "CFBundleDisplayName": "DC Minifiguren-Checkliste",
                         "NSHighResolutionCapable": True})
            plist.write_bytes(plistlib.dumps(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
