"""Build a versioned Windows folder/zip, with offline OCR and no player saves."""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PROJECT = json.loads((ROOT / "data/project_info.json").read_text(encoding="utf-8"))


def run(args, *, cwd=ROOT, capture=False, env=None, timeout=None):
    command = [str(value) for value in args]
    if sys.platform == "win32" and command[0].lower().endswith((".cmd", ".bat")):
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c",
                   subprocess.list2cmdline(command)]
    return subprocess.run(command, cwd=cwd, env=env, check=True, text=True,
                          encoding="utf-8", capture_output=capture, timeout=timeout)


def verify_window(folder, name, env):
    report = ROOT / "build/desktop-window-test.json"
    report.unlink(missing_ok=True)
    run([folder / f"{name}.exe", "--window-test", "--data-dir",
         ROOT / "build/desktop-window-test-data", "--report", report], env=env, timeout=120)
    result = json.loads(report.read_text(encoding="utf-8"))
    if not result.get("ok") or result.get("engine") != "edgechromium" or not result.get("frontendMounted"):
        raise RuntimeError(f"Frozen desktop window test failed: {result}")


def version_info(allow_dirty):
    revision = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    changed = run(["git", "diff", "--name-only", "HEAD"], capture=True).stdout.splitlines()
    if changed and not allow_dirty:
        raise RuntimeError("Tracked files have uncommitted changes. Commit first, or use --allow-dirty for a test build.")
    return {"revision": revision, "dirty": bool(changed), "changedFiles": changed, "project": PROJECT,
            "builtAt": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0],
            "platform": sys.platform, "architecture": "x64"}


def collect_licenses(folder, node_version):
    for filename in ("LICENSE", "NOTICE"):
        shutil.copy2(ROOT / filename, folder / filename)
    destination = folder / "licenses"
    destination.mkdir(parents=True, exist_ok=True)
    for dist in metadata.distributions():
        name = dist.metadata["Name"].replace("/", "_")
        for item in dist.files or []:
            if any("license" in part.lower() or "copying" in part.lower() for part in item.parts):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    target = destination / name / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, destination / "Python-LICENSE.txt")
    with urlopen(f"https://raw.githubusercontent.com/nodejs/node/{node_version}/LICENSE", timeout=60) as response:
        (destination / "Node-LICENSE.txt").write_bytes(response.read())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, help="Node.js executable, default: PATH")
    parser.add_argument("--allow-dirty", action="store_true", help="Mark an uncommitted test build as dirty")
    parser.add_argument("--skip-install", action="store_true", help="Reuse already installed build inputs")
    args = parser.parse_args(argv)
    if sys.platform != "win32" or sys.maxsize <= 2**32 or sys.version_info[:2] != (3, 11):
        parser.error("This build script requires Windows x64 and Python 3.11")
    node = args.node or shutil.which("node")
    pnpm = shutil.which("pnpm")
    if not node or not pnpm:
        parser.error("Install Node.js 24 and pnpm 11 on the build computer first")
    node = Path(node).resolve()
    env = os.environ.copy()
    env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    info = version_info(args.allow_dirty)
    info["node"] = run([node, "--version"], capture=True).stdout.strip()
    info["pnpm"] = run([pnpm, "--version"], capture=True).stdout.strip()
    if not info["node"].startswith("v24.") or not info["pnpm"].startswith("11."):
        parser.error("The current build is validated with Node.js 24 and pnpm 11")
    info["pythonPackages"] = {dist.metadata["Name"]: dist.version for dist in metadata.distributions()}
    prepared = ROOT / "build/desktop-input"
    runtime = prepared / "runtime/node"
    (runtime / "bin").mkdir(parents=True, exist_ok=True)
    shutil.copy2(node, runtime / "bin/node.exe")
    ocr = prepared / "ocr"
    ocr.mkdir(parents=True, exist_ok=True)
    for filename in ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"):
        shutil.copy2(ROOT / filename, ocr / filename)
    if not args.skip_install:
        run([pnpm, "install", "--frozen-lockfile"], cwd=ROOT / "frontend", env=env)
        run([pnpm, "install", "--prod", "--frozen-lockfile", "--node-linker=hoisted"], cwd=ocr, env=env)
    if not (ocr / "node_modules/tesseract.js/package.json").is_file():
        parser.error("OCR build inputs are missing; run once without --skip-install")
    # Follow package links into the bundle, never leave links to the build computer.
    modules_target = (runtime / "node_modules").resolve()
    if not modules_target.is_relative_to((ROOT / "build").resolve()):
        raise RuntimeError("OCR build output escapes the build directory")
    if modules_target.exists():
        shutil.rmtree(modules_target)
    shutil.copytree(ocr / "node_modules", runtime / "node_modules", dirs_exist_ok=True)
    run([node, "node_modules/vite/bin/vite.js", "build"], cwd=ROOT / "frontend", env=env)
    (prepared / "build-info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    env["FULCRUM_BUILD_INPUT"] = str(prepared)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--workpath", ROOT / "build/pyinstaller", "--distpath", ROOT / "dist",
         ROOT / "packaging/fulcrum.spec"], env=env)
    name = PROJECT["executableName"]
    folder = ROOT / "dist" / name
    shutil.copy2(prepared / "build-info.json", folder / "build-info.json")
    collect_licenses(folder, info["node"])
    (folder / "START-HERE.txt").write_text(
        f"{PROJECT['name']}\n{PROJECT['englishName']}\n\n"
        f"完整解压后双击 {name}.exe。\n"
        "从 GitHub 下载后，先右键原 ZIP → 属性 → 解除锁定 → 应用，再完整解压。仅解锁确认来源可信的本项目程序包。\n"
        "Requires Windows 10/11 x64, .NET Framework 4.8 and Microsoft WebView2 Runtime.\n"
        f"存档、图片与日志：%LOCALAPPDATA%\\{PROJECT['dataDirectoryName']}；旧版 BlackFlow/Fulcrum 存档需手动导入，不自动迁移。\n"
        "Do not copy only the EXE: _internal contains offline OCR, game data and UI.\n"
        "This is an unsigned development build. No Python or Node install is needed.\n",
        encoding="utf-8")
    report = ROOT / "build/desktop-self-test.json"
    run([folder / f"{name}.exe", "--self-test", "--data-dir",
         ROOT / "build/desktop-self-test-data", "--report", report], env=env)
    result = json.loads(report.read_text(encoding="utf-8"))
    if not result.get("ok"):
        raise RuntimeError(f"Frozen desktop self-test failed: {result}")
    verify_window(folder, name, env)
    suffix = info["revision"][:8] + ("-dirty" if info["dirty"] else "")
    output = ROOT / f"dist/{name}-{suffix}-win-x64.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(folder.parent))
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="ascii")
    print(f"Ready: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
