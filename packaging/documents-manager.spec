# PyInstaller recipe: one windowed executable, DocumentsManager.exe. Build it with packaging/build_windows.bat (on Windows).
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent
datas = [(str(root / "frontend" / "dist"), "frontend/dist"), (str(root / "config"), "config"),
         (str(root / "CHANGELOG.md"), "."), (str(root / "LICENSE"), ".")]
binaries, hiddenimports = [], []
for package in ("django", "rest_framework", "pypdfium2", "pypdfium2_raw", "webview", "waitress"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("triage") + collect_submodules("webapp") + collect_submodules("docflow")

a = Analysis([str(root / "packaging" / "entry.py")], pathex=[str(root / "backend")], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=["tkinter", "pytest", "mypy", "pymupdf"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="DocumentsManager", console=False, upx=False,
          icon=None, disable_windowed_traceback=False)
