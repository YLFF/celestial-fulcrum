from pathlib import Path
import json
import os

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct,
)

root = Path(SPECPATH).parent
prepared = Path(os.environ["FULCRUM_BUILD_INPUT"])
project = json.loads((root / "data/project_info.json").read_text(encoding="utf-8"))
version = tuple(int(part) for part in project["version"].split(".")) + (0,)
version_resource = VSVersionInfo(ffi=FixedFileInfo(filevers=version, prodvers=version, fileType=1),
    kids=[StringFileInfo([StringTable("080404b0", [
        StringStruct("ProductName", project["name"]),
        StringStruct("FileDescription", project["englishName"]),
        StringStruct("FileVersion", project["version"]),
        StringStruct("ProductVersion", project["version"]),
        StringStruct("InternalName", project["executableName"]),
        StringStruct("OriginalFilename", project["executableName"] + ".exe"),
    ])]), VarFileInfo([VarStruct("Translation", [2052, 1200])])])
datas = [(str(path), "data") for path in (root / "data").glob("*.json")
         if path.name not in {"arkrog_blackflowmap_findings.json", "lubiao_reference_catalog.v1.json"}]
datas += [(str(path), str(path.relative_to(root).parent))
          for path in (root / "assets").rglob("*")
          if path.is_file() and path.suffix in {".png", ".npz"}]
datas += [(str(root / "frontend/dist"), "frontend/dist"),
          (str(root / "scripts/ocr_hud_batch.mjs"), "scripts"),
          (str(root / "eng.traineddata"), "."),
          (str(prepared / "runtime"), "runtime"),
          (str(prepared / "build-info.json"), ".")]
a = Analysis([str(root / "desktop_launcher.py")], pathex=[str(root)],
             datas=datas, binaries=[],
             hiddenimports=collect_submodules("fulcrum") + [
                 "webview.platforms.winforms", "webview.platforms.edgechromium",
                 "uvicorn.logging", "uvicorn.loops.asyncio",
                 "uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.on"],
             excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "cefpython3", "matplotlib"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [("X utf8", None, "OPTION")], exclude_binaries=True,
          name=project["executableName"], version=version_resource,
          console=False, debug=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name=project["executableName"], upx=False)
