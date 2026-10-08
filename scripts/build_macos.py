"""Build an Apple Silicon test app locally; no remote builder or signing account."""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys

from build_desktop import collect_licenses, run

ROOT = Path(__file__).resolve().parents[1]
PROJECT = json.loads((ROOT / "data/project_info.json").read_text(encoding="utf-8"))


def source_info():
    manifest = ROOT / "source-info.json"
    if manifest.is_file():
        return json.loads(manifest.read_text(encoding="utf-8"))
    revision = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    changed = run(["git", "status", "--porcelain"], capture=True).stdout.splitlines()
    return {"revision": revision, "dirty": bool(changed), "changedFiles": changed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, help="Native arm64 Node.js 24 executable, default: PATH")
    parser.add_argument("--skip-install", action="store_true", help="Reuse installed frontend/OCR packages")
    args = parser.parse_args(argv)
    if sys.platform != "darwin" or platform.machine() != "arm64" or sys.version_info[:2] != (3, 11):
        parser.error("Use native arm64 Python 3.11 on an Apple Silicon Mac (not Rosetta)")
    node, pnpm = args.node or shutil.which("node"), shutil.which("pnpm")
    if not node or not pnpm:
        parser.error("Install native Node.js 24 and pnpm 11 on the build Mac first")
    node = Path(node).resolve()
    env = os.environ.copy()
    env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    info = {**source_info(), "project": PROJECT, "platform": "darwin", "architecture": "arm64",
            "builtAt": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0]}
    info["node"] = run([node, "--version"], capture=True, env=env).stdout.strip()
    info["pnpm"] = run([pnpm, "--version"], capture=True, env=env).stdout.strip()
    if not info["node"].startswith("v24.") or not info["pnpm"].startswith("11."):
        parser.error("Use Node.js 24 and pnpm 11 for this test build")
    if run([node, "-p", "process.platform + '/' + process.arch"], capture=True, env=env).stdout.strip() != "darwin/arm64":
        parser.error("Node.js must also be native macOS arm64")
    info["pythonPackages"] = {dist.metadata["Name"]: dist.version for dist in metadata.distributions()}
    prepared = ROOT / "build/macos-input"
    runtime, ocr = prepared / "runtime/node", prepared / "ocr"
    (runtime / "bin").mkdir(parents=True, exist_ok=True)
    shutil.copy2(node, runtime / "bin/node")
    (runtime / "bin/node").chmod(0o755)
    ocr.mkdir(parents=True, exist_ok=True)
    for filename in ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"):
        shutil.copy2(ROOT / filename, ocr / filename)
    if not args.skip_install:
        run([pnpm, "install", "--frozen-lockfile"], cwd=ROOT / "frontend", env=env)
        run([pnpm, "install", "--prod", "--frozen-lockfile", "--node-linker=hoisted"], cwd=ocr, env=env)
    if not (ocr / "node_modules/tesseract.js/package.json").is_file():
        parser.error("OCR packages are missing; run once without --skip-install")
    target = (runtime / "node_modules").resolve()
    if not target.is_relative_to((ROOT / "build").resolve()):
        raise RuntimeError("OCR output escapes the build directory")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ocr / "node_modules", target)
    run([node, "node_modules/vite/bin/vite.js", "build"], cwd=ROOT / "frontend", env=env)
    (prepared / "build-info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    env["FULCRUM_BUILD_INPUT"] = str(prepared)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--workpath", ROOT / "build/pyinstaller-macos", "--distpath", ROOT / "dist",
         ROOT / "packaging/fulcrum-macos.spec"], env=env)
    name = PROJECT["executableName"]
    app = ROOT / "dist" / (name + ".app")
    resources = app / "Contents/Resources"
    shutil.copy2(prepared / "build-info.json", resources / "build-info.json")
    collect_licenses(resources, info["node"])
    shutil.copy2(ROOT / "packaging/MACOS_TEST.md", resources / "MACOS_TEST.md")
    # Extra license files are added after PyInstaller's ad-hoc signature.
    run(["codesign", "--force", "--deep", "--sign", "-", app])
    run(["codesign", "--verify", "--deep", "--strict", app])
    binary = app / "Contents/MacOS" / name
    run([binary, "--self-test", "--data-dir", ROOT / "work/macos-self-test",
         "--report", ROOT / "work/macos-self-test.json"], env=env)
    suffix = info["revision"][:8] + ("-dirty" if info.get("dirty") else "")
    output = ROOT / "dist" / f"{name}-{suffix}-mac-arm64.zip"
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, output])
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="ascii")
    print(f"Ready: {app}\nArchive: {output}\nSelf-test: {ROOT / 'work/macos-self-test.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
