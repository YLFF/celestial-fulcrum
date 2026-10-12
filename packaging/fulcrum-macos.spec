from pathlib import Path
import json
import os

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
prepared = Path(os.environ["FULCRUM_BUILD_INPUT"])
project = json.loads((root / "data/project_info.json").read_text(encoding="utf-8"))
data_paths = [*(root / "data").glob("*.json"), *(root / "data/scoring").rglob("*.json"),
              *(root / "data/relic_effects").rglob("*.json")]
datas = [(str(path), str(path.relative_to(root).parent)) for path in data_paths
         if path.name not in {"arkrog_blackflowmap_findings.json", "lubiao_reference_catalog.v1.json"}]
datas += [(str(path), str(path.relative_to(root).parent))
          for path in (root / "assets").rglob("*")
          if path.is_file() and path.suffix in {".png", ".npz"}]
datas += [(str(root / "frontend/dist"), "frontend/dist"),
          (str(root / "scripts/ocr_hud_batch.mjs"), "scripts"),
          (str(root / "scripts/ocr_node_labels.mjs"), "scripts"),
          (str(root / "eng.traineddata"), "."),
          (str(root / "chi_sim.traineddata"), "."),
          (str(root / "packaging/tessdata_fast.LICENSE"), "licenses"),
          (str(prepared / "runtime/node/node_modules"), "runtime/node/node_modules"),
          (str(prepared / "build-info.json"), ".")]

a = Analysis([str(root / "desktop_launcher.py")], pathex=[str(root)], datas=datas,
             binaries=[(str(prepared / "runtime/node/bin/node"), "runtime/node/bin")],
             hiddenimports=collect_submodules("fulcrum") + ["webview.platforms.cocoa",
                 "uvicorn.logging", "uvicorn.loops.asyncio",
                 "uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.on"],
             excludes=["webview.platforms.winforms", "webview.platforms.edgechromium",
                 "windows_capture", "PyQt5", "PyQt6", "PySide2", "PySide6", "cefpython3", "matplotlib"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [("X utf8", None, "OPTION")], exclude_binaries=True,
          name=project["executableName"], console=False, debug=False, upx=False,
          target_arch="arm64", codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, name=project["executableName"], upx=False)
app = BUNDLE(coll, name=project["executableName"] + ".app", icon=None,
             bundle_identifier="local.celestialfulcrum.assistant", info_plist={
                 "CFBundleDisplayName": project["shortName"],
                 "CFBundleShortVersionString": project["version"],
                 "CFBundleVersion": project["version"],
                 "NSHighResolutionCapable": True,
             })
