"""Copy an explicit publication allowlist, without development history or saves."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from export_macos_source import FILES, EXCLUDED_DATA

ROOT = Path(__file__).resolve().parents[1]
EXTRA_FILES = (
    ".gitignore", ".github/workflows/desktop-release.yml",
    "packaging/fulcrum.spec", "requirements-desktop-windows.txt",
    "scripts/export_release_source.py", "scripts/new_run.py",
    "experiments/__init__.py", "experiments/node_prediction_beta.py",
)
TREES = {
    "fulcrum": {".py"},
    "frontend/src": None,
    "frontend/tests": {".mjs"},
    "frontend/public": {".png", ".jpg", ".jpeg", ".webp", ".ico"},
    "assets": {".png", ".npz"},
    "tests": {".py"},
    "scripts": {".py", ".mjs"},
}


def publication_files(root=ROOT):
    root = Path(root)
    paths = {root / name for name in (*FILES, *EXTRA_FILES)}
    for folder, extensions in TREES.items():
        paths.update(path for path in (root / folder).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts
                     and (extensions is None or path.suffix.lower() in extensions))
    paths.update(path for path in (root / "data").glob("*.json") if path.name not in EXCLUDED_DATA)
    missing = [str(path.relative_to(root)) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"Required publication inputs are missing: {missing}")
    return sorted(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--refresh", action="store_true", help="Refresh an existing managed publication checkout")
    args = parser.parse_args()
    destination = args.destination.resolve()
    if not destination.is_relative_to((ROOT / "work").resolve()):
        parser.error("The publication checkout must be inside this project's work directory")
    managed = (destination / "publication-manifest.json").is_file()
    if destination.exists() and any(destination.iterdir()) and not (args.refresh and managed):
        parser.error("Use a new, empty publication directory")
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for source in publication_files():
        relative = source.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest[relative.as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    # The manifest is an audit of exported content, not a replacement Git revision.
    (destination / "publication-manifest.json").write_text(
        json.dumps({"sourceDigest": digest, "fileSHA256": manifest}, indent=2), encoding="utf-8")
    print(json.dumps({"destination": str(destination), "fileCount": len(manifest) + 1,
                      "sourceDigest": digest}, indent=2))


if __name__ == "__main__":
    main()
