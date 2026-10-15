"""Deferred desktop replacement. Never replaces the separately stored player data."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

WINDOWS_HELPER = r'''
$ErrorActionPreference = 'Stop'
$p = Get-Content -LiteralPath $env:CFARA_UPDATE_PLAN -Raw -Encoding UTF8 | ConvertFrom-Json
$moved = $false
try {
  for ($i = 0; $i -lt 180; $i++) {
    if (-not (Get-Process -Id $p.parentPid -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Seconds 1
  }
  if (Get-Process -Id $p.parentPid -ErrorAction SilentlyContinue) { throw 'Application did not close' }
  if (Test-Path -LiteralPath $p.backup) { throw 'Backup already exists' }
  Move-Item -LiteralPath $p.current -Destination $p.backup
  $moved = $true
  Move-Item -LiteralPath $p.prepared -Destination $p.current
  $exe = Join-Path $p.current $p.executable
  $testArgs = @('--self-test', '--data-dir', ('"' + $p.testData + '"'), '--report', ('"' + $p.report + '"'))
  $test = Start-Process -FilePath $exe -ArgumentList $testArgs -PassThru -WindowStyle Hidden
  if (-not $test.WaitForExit(120000)) { $test.Kill(); $test.WaitForExit(); throw 'New package self-test timed out' }
  $test.Refresh()
  if ($test.ExitCode -ne 0) { throw 'New package self-test failed' }
  $result = Get-Content -LiteralPath $p.report -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $result.ok) { throw 'New package self-test failed' }
  Start-Process -FilePath $exe -ArgumentList @('--data-dir', ('"' + $p.data + '"')) -WindowStyle Hidden
  'Update succeeded; previous package retained at ' + $p.backup | Out-File -LiteralPath $p.log -Encoding UTF8
} catch {
  $_ | Out-File -LiteralPath $p.log -Encoding UTF8
  if ($moved) {
    if (Test-Path -LiteralPath $p.current) { Move-Item -LiteralPath $p.current -Destination $p.failed }
    Move-Item -LiteralPath $p.backup -Destination $p.current
    Start-Process -FilePath (Join-Path $p.current $p.previousExecutable) -ArgumentList @('--data-dir', ('"' + $p.data + '"')) -WindowStyle Hidden
  }
}
'''

MAC_HELPER = r'''
parent=$1; current=$2; prepared=$3; backup=$4; failed=$5; data=$6; testData=$7; report=$8; log=$9
executable=${10}; previousExecutable=${11}
exec >> "$log" 2>&1
i=0
while kill -0 "$parent" 2>/dev/null; do
  i=$((i+1)); [ "$i" -lt 180 ] || exit 1
  sleep 1
done
[ ! -e "$backup" ] || exit 1
mv "$current" "$backup" || exit 1
rollback() {
  [ ! -e "$current" ] || mv "$current" "$failed"
  mv "$backup" "$current" || exit 1
  "$current/Contents/MacOS/$previousExecutable" --data-dir "$data" >/dev/null 2>&1 &
  exit 1
}
mv "$prepared" "$current" || rollback
"$current/Contents/MacOS/$executable" --self-test --data-dir "$testData" --report "$report" &
probe=$!
i=0
while kill -0 "$probe" 2>/dev/null; do
  i=$((i+1))
  if [ "$i" -ge 120 ]; then kill "$probe"; wait "$probe"; rollback; fi
  sleep 1
done
wait "$probe" || rollback
"$current/Contents/MacOS/$executable" --data-dir "$data" >/dev/null 2>&1 &
echo "Update succeeded; previous package retained at $backup"
'''


def installed_directory():
    executable = Path(sys.executable).resolve()
    return executable.parents[2] if sys.platform == "darwin" else executable.parent


def prepare_install(staged, data, updates, *, current=None):
    current = Path(current or installed_directory()).resolve()
    staged, data, updates = Path(staged).resolve(), Path(data).resolve(), Path(updates).resolve()
    if not staged.is_relative_to(updates) or not staged.is_dir():
        raise ValueError("更新候选目录不合法，请重新下载")
    if current == data or data.is_relative_to(current) or current.is_relative_to(data):
        raise ValueError("程序和存档目录相互包含，请先将程序移至独立文件夹")
    if not current.is_dir() or current.parent == current or current.is_symlink():
        raise ValueError("无法确认当前程序的安装目录")
    identifier = uuid4().hex
    # Prepare on the installation volume so the two final renames remain local.
    prepared = current.with_name(f".CFARA-update-{identifier}" + (".app" if sys.platform == "darwin" else ""))
    try:
        shutil.copytree(staged, prepared, symlinks=True)
    except OSError as error:
        raise ValueError("无法在程序旁准备更新；请将程序移到可写文件夹，或手动安装发行包") from error
    attempt = updates / identifier
    attempt.mkdir(parents=True)
    from .product import PROJECT
    names = [PROJECT["executableName"], "CelestialFulcrum"]
    def executable_name(folder):
        return next((name for name in names if (folder / (f"{name}.exe" if sys.platform == "win32" else f"Contents/MacOS/{name}")).is_file()), "CelestialFulcrum")
    executable = executable_name(staged)
    previous_executable = executable_name(current)
    plan = {"parentPid": os.getpid(), "current": str(current), "prepared": str(prepared),
            "executable": executable + (".exe" if sys.platform == "win32" else ""),
            "previousExecutable": previous_executable + (".exe" if sys.platform == "win32" else ""),
            "backup": str(current.with_name(current.name + ".previous-" + identifier)),
            "failed": str(current.with_name(current.name + ".failed-" + identifier)), "data": str(data),
            "testData": str(attempt / "self-test-data"), "report": str(attempt / "self-test.json"),
            "log": str(attempt / "install.log")}
    path = attempt / "install.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def launch_install(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if sys.platform == "win32":
        env = os.environ.copy()
        env["CFARA_UPDATE_PLAN"] = str(plan_path)
        script = base64.b64encode(WINDOWS_HELPER.encode("utf-16-le")).decode("ascii")
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", script],
                         env=env, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    elif sys.platform == "darwin":
        subprocess.Popen(["/bin/sh", "-c", MAC_HELPER, "cfara-update", str(plan["parentPid"]),
                          *[plan[key] for key in ("current", "prepared", "backup", "failed", "data", "testData", "report", "log", "executable", "previousExecutable")]],
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        raise ValueError("当前平台暂不支持重启更新")
