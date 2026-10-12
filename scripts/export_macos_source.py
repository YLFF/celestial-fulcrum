"""Export the current source and offline assets, without user saves or README edits."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ("fulcrum", "frontend/src", "frontend/tests", "frontend/public", "assets")
FILES = (
    "LICENSE", "NOTICE",
    "desktop_launcher.py", "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "eng.traineddata", "chi_sim.traineddata",
    "packaging/tessdata_fast.LICENSE",
    "requirements-vision.txt", "requirements-service.txt", "requirements-desktop.txt", "requirements-desktop-macos.txt",
    "frontend/package.json", "frontend/pnpm-lock.yaml", "frontend/pnpm-workspace.yaml", "frontend/index.html", "frontend/vite.config.js",
    "packaging/fulcrum-macos.spec", "packaging/MACOS_TEST.md",
    "scripts/build_macos.py", "scripts/build_desktop.py", "scripts/ocr_hud_batch.mjs", "scripts/ocr_node_labels.mjs", "scripts/export_macos_source.py",
)
EXCLUDED_DATA = {"arkrog_blackflowmap_findings.json", "lubiao_reference_catalog.v1.json"}


def source_files(root=ROOT):
    root = Path(root)
    paths = {root / filename for filename in FILES}
    for folder in FOLDERS:
        paths.update(path for path in (root / folder).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"})
    data_paths = [*(root / "data").glob("*.json"), *(root / "data/scoring").rglob("*.json"),
                  *(root / "data/relic_effects").rglob("*.json")]
    paths.update(path for path in data_paths if path.name not in EXCLUDED_DATA)
    missing = [str(path.relative_to(root)) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"Required source inputs are missing: {missing}")
    return sorted(paths)


def main():
    paths = source_files()
    files = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    changed = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True, encoding="utf-8").splitlines()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    info = {"revision": revision, "dirty": bool(changed), "createdAt": datetime.now(timezone.utc).isoformat(),
            "sourceDigest": digest, "fileSHA256": files, "purpose": "personal Apple Silicon local build"}
    destination = ROOT / "dist" / f"CelestialFulcrum-mac-source-{digest[:12]}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    prefix = "CelestialFulcrum-source/"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in paths:
            archive.write(path, prefix + path.relative_to(ROOT).as_posix())
        archive.writestr(prefix + "source-info.json", json.dumps(info, ensure_ascii=False, indent=2))
    with destination.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    destination.with_suffix(".zip.sha256").write_text(f"{checksum}  {destination.name}\n", encoding="ascii")
    print(json.dumps({"archive": str(destination), "fileCount": len(paths) + 1,
                      "bytes": destination.stat().st_size, "sha256": checksum}, indent=2))


if __name__ == "__main__":
    main()
