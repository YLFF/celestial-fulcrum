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
    "docs/ROADMAP.md",
    "packaging/fulcrum.spec", "requirements-desktop-windows.txt",
    "scripts/export_release_source.py", "scripts/new_run.py",
    "experiments/__init__.py", "experiments/node_prediction_beta.py",
    "tests/fixtures/arkrog_30.json",
    "tests/fixtures/n15_floor2_combat.json",
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
EXCLUDED_FILES = {"tests/test_decision_advisor.py", "tests/test_rolling_route_probe.py"}


def publication_files(root=ROOT):
    root = Path(root)
    paths = {root / name for name in (*FILES, *EXTRA_FILES)}
    for folder, extensions in TREES.items():
        paths.update(path for path in (root / folder).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts
                     and (extensions is None or path.suffix.lower() in extensions))
    data_paths = [*(root / "data").glob("*.json"), *(root / "data/scoring").rglob("*.json"),
                  *(root / "data/relic_effects").rglob("*.json")]
    paths.update(path for path in data_paths if path.name not in EXCLUDED_DATA)
    missing = [str(path.relative_to(root)) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"Required publication inputs are missing: {missing}")
    return sorted(path for path in paths if path.relative_to(root).as_posix() not in EXCLUDED_FILES)


def remove_obsolete_files(destination, current_names):
    destination = Path(destination).resolve()
    previous = json.loads((destination / "publication-manifest.json").read_text(encoding="utf-8"))["fileSHA256"]
    obsolete = []
    for name in previous.keys() - set(current_names):
        relative = Path(name)
        target = (destination / relative).resolve()
        if relative.is_absolute() or ".git" in {part.casefold() for part in relative.parts} or not target.is_relative_to(destination) or target == destination:
            raise RuntimeError(f"Unsafe obsolete publication path: {name}")
        if not target.exists():
            continue
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != previous[name]:
            raise RuntimeError(f"Obsolete publication file has local changes; preserve it before refreshing: {name}")
        obsolete.append(target)
    for target in obsolete:
        target.unlink()


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
    sources = publication_files()
    if managed:
        remove_obsolete_files(destination, [path.relative_to(ROOT).as_posix() for path in sources])
    manifest = {}
    for source in sources:
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
