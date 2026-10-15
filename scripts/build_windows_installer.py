"""Create a per-user installer without changing system download-security settings."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from build_desktop import ROOT, PROJECT, run


def compiler_path():
    candidates = [shutil.which("ISCC.exe"), *[
        f"C:/Program Files (x86)/Inno Setup {version}/ISCC.exe" for version in (6, 7)]]
    return next((Path(value) for value in candidates if value and Path(value).is_file()), None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc", type=Path)
    args = parser.parse_args(argv)
    compiler = args.iscc or compiler_path()
    if not compiler:
        parser.error("Inno Setup ISCC.exe is required to build the Windows installer")
    name = PROJECT["executableName"]
    source = ROOT / "dist" / name
    info = json.loads((source / "build-info.json").read_text(encoding="utf-8"))
    if info["project"] != PROJECT:
        raise ValueError("Installer inputs do not match current project metadata")
    suffix = PROJECT["version"] + ("-dirty" if info["dirty"] else "")
    basename = f"CelestialFulcrum-{suffix}-win-x64-setup"
    run([compiler, "/Qp", f"/DAppVersion={PROJECT['version']}", f"/DAppExecutable={name}",
         f"/DSourceDirectory={source}", f"/O{ROOT / 'dist'}", f"/F{basename}",
         ROOT / "packaging/windows-installer.iss"])
    output = ROOT / "dist" / f"{basename}.exe"
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    output.with_suffix(".exe.sha256").write_text(f"{digest}  {output.name}\n", encoding="ascii")
    # Test installation into an isolated build directory, not the user's installation.
    target = ROOT / "build/installer-test"
    report = ROOT / "build/installer-self-test.json"
    report.unlink(missing_ok=True)
    run([output, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS", "/CFARATest=1", f"/DIR={target}"])
    run([target / f"{name}.exe", "--self-test", "--data-dir", ROOT / "build/installer-test-data",
         "--report", report])
    if not json.loads(report.read_text(encoding="utf-8")).get("ok"):
        raise RuntimeError("Installed package self-test failed")
    print(f"Ready: {output}")


if __name__ == "__main__":
    main()
