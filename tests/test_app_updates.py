from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import stat
import os
import base64
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient

from fulcrum.app_updates import AppUpdater, release_candidate, trusted_url, unpack_package, version_tuple
from fulcrum.service.app import create_app
from fulcrum.update_install import prepare_install, WINDOWS_HELPER


def release(version="0.2.0"):
    name = "CelestialFulcrum-1234abcd-win-x64.zip"
    return {"tag_name": "v" + version, "assets": [{"name": name, "size": 123,
            "digest": "sha256:" + "a" * 64,
            "browser_download_url": "https://github.com/YLFF/celestial-fulcrum/releases/download/v" + version + "/" + name}]}


def package(extra=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('CelestialFulcrum/CelestialFulcrum.exe', b'test executable')
        archive.writestr('CelestialFulcrum/build-info.json', json.dumps({"platform": "win32", "architecture": "x64", "dirty": False,
                         "project": {"version": "0.2.0", "executableName": "CelestialFulcrum"}}))
        if extra:
            archive.writestr(*extra)
    return data.getvalue()


class UpdateSafetyTests(unittest.TestCase):
    def test_stable_versions_no_equal_version_or_downgrade(self):
        self.assertIsNone(version_tuple('1.2.3-preview'))
        self.assertEqual(version_tuple('v1.2.3'), (1, 2, 3))
        self.assertIsNone(release_candidate([release('0.1.0')], '0.1.0', 'win-x64'))
        self.assertIsNone(release_candidate([release('0.0.9')], '0.1.0', 'win-x64'))
        preview = release('9.0.0')
        preview['prerelease'] = True
        self.assertEqual(release_candidate([preview, release()], '0.1.0', 'win-x64')['version'], '0.2.0')

    def test_missing_checksum_platform_and_multiple_assets_rejected(self):
        for target, modifier in [('mac-arm64', lambda row: None), ('win-x64', lambda row: row['assets'][0].pop('digest')),
                                 ('win-x64', lambda row: row['assets'].append(deepcopy(row['assets'][0])))]:
            row = release()
            modifier(row)
            with self.assertRaises(ValueError):
                release_candidate([row], '0.1.0', target)

    def test_only_project_release_urls_and_known_github_redirect_hosts(self):
        for url in ['http://github.com/YLFF/celestial-fulcrum/releases/download/v1/a',
                    'https://github.com/other/repo/releases/download/v1/a', 'https://localhost/update',
                    'https://github.com.evil.test/a', 'https://user@github.com/YLFF/celestial-fulcrum/releases/download/v1/a']:
            with self.assertRaises(ValueError):
                trusted_url(url)
        self.assertTrue(trusted_url(release()['assets'][0]['browser_download_url']))

    def test_valid_archive_and_version_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'bundle.zip'
            archive.write_bytes(package())
            app = unpack_package(archive, Path(temp) / 'out', '0.2.0', 'win-x64')
            self.assertTrue((app / 'CelestialFulcrum.exe').is_file())
            with self.assertRaises(ValueError):
                unpack_package(archive, Path(temp) / 'wrong', '0.3.0', 'win-x64')

    def test_mac_package_metadata_and_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bundle.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('CelestialFulcrum.app/Contents/MacOS/CelestialFulcrum', 'test binary')
                archive.writestr('CelestialFulcrum.app/Contents/Resources/build-info.json', json.dumps({
                    'platform': 'darwin', 'architecture': 'arm64', 'dirty': False,
                    'project': {'version': '0.2.0', 'executableName': 'CelestialFulcrum'}}))
                archive.writestr('__MACOSX/._CelestialFulcrum.app', 'resource fork')
            result = unpack_package(path, Path(temp) / 'out', '0.2.0', 'mac-arm64')
            self.assertTrue((result / 'Contents/MacOS/CelestialFulcrum').is_file())
            self.assertFalse((Path(temp) / 'out/__MACOSX').exists())

    def test_archive_traversal_duplicate_case_and_symlink_rejected(self):
        for name in ['../outside', '/outside', 'CelestialFulcrum/../../outside', 'CelestialFulcrum/evil:stream',
                     'CelestialFulcrum/..\\outside', 'CelestialFulcrum/celestialfulcrum.EXE']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'bundle.zip'
                path.write_bytes(package((name, b'bad')))
                with self.assertRaises(ValueError):
                    unpack_package(path, Path(temp) / 'out', '0.2.0', 'win-x64')
                self.assertFalse((Path(temp) / 'outside').exists())
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bundle.zip'
            info = zipfile.ZipInfo('CelestialFulcrum/link')
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            path.write_bytes(package((info, '../outside')))
            with self.assertRaises(ValueError):
                unpack_package(path, Path(temp) / 'out', '0.2.0', 'win-x64')

    def test_download_digest_and_content_length(self):
        for valid in (True, False):
            with tempfile.TemporaryDirectory() as temp:
                updater = AppUpdater(temp)
                self.addCleanup(updater.close)
                data = package()
                updater.target = 'win-x64'
                updater.candidate = release_candidate([release()], '0.1.0', 'win-x64')
                updater.candidate.update(size=len(data), digest=hashlib.sha256(data).hexdigest() if valid else '0' * 64)
                with patch('fulcrum.app_updates.open_release_url', return_value=io.BytesIO(data)):
                    updater._run(updater._download)
                self.assertEqual(updater.snapshot()['status'], 'ready' if valid else 'error')
                self.assertEqual(bool(updater.staged), valid)

    def test_prepare_install_never_touches_saves_or_current_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current, data, updates = root / 'installed', root / 'CFARA', root / 'CFARA/updates'
            current.mkdir()
            data.mkdir()
            (current / 'old').write_text('old')
            (data / 'save').write_text('keep')
            staged = updates / 'attempt/expanded/CelestialFulcrum'
            staged.mkdir(parents=True)
            (staged / 'new').write_text('new')
            plan = json.loads(prepare_install(staged, data, updates, current=current).read_text(encoding='utf-8'))
            self.assertEqual((current / 'old').read_text(), 'old')
            self.assertEqual((data / 'save').read_text(), 'keep')
            self.assertTrue((Path(plan['prepared']) / 'new').is_file())
            self.assertEqual(Path(plan['prepared']).parent.resolve(), current.parent.resolve())
            with self.assertRaises(ValueError):
                prepare_install(staged, current / 'saves', updates, current=current)

    def test_api_requires_auth_and_dev_cannot_install(self):
        with tempfile.TemporaryDirectory() as temp, TestClient(create_app(temp)) as client:
            self.assertEqual(client.get('/api/app-updates').status_code, 401)
            headers = {'X-Fulcrum-Token': client.get('/api/session').json()['token']}
            state = client.get('/api/app-updates', headers=headers).json()
            self.assertFalse(state['canInstall'])
            self.assertEqual(client.post('/api/app-updates', headers=headers, json={'action': 'install'}).status_code, 422)
            self.assertEqual(client.post('/api/app-updates', headers=headers, json={'action': 'delete', 'url': 'x'}).status_code, 422)

    @unittest.skipUnless(sys.platform == 'win32', 'PowerShell helper integration is Windows-only')
    def test_replacement_and_rollback_with_isolated_fake_processes(self):
        stub = r'''
function Start-Process {
  param($FilePath, $ArgumentList, [switch]$PassThru, $WindowStyle)
  if ($PassThru) {
    $ok = $env:CFARA_FAKE_TEST -eq 'ok'
    @{ok=$ok} | ConvertTo-Json | Out-File -LiteralPath $p.report -Encoding UTF8
    $proc = [PSCustomObject]@{ ExitCode = $(if ($ok) {0} else {1}) }
    $proc | Add-Member ScriptMethod WaitForExit { param($timeout) return $true }
    $proc | Add-Member ScriptMethod Refresh { }
    return $proc
  }
}
'''
        for healthy in (True, False):
            with self.subTest(healthy=healthy), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                current, data = root / 'installed app', root / 'CFARA data'
                current.mkdir()
                data.mkdir()
                (data / 'save.json').write_text('original save')
                (current / 'CelestialFulcrum.exe').write_text('old')
                updates = data / 'updates'
                staged = updates / 'candidate'
                staged.mkdir(parents=True)
                (staged / 'CelestialFulcrum.exe').write_text('new')
                plan_path = prepare_install(staged, data, updates, current=current)
                plan = json.loads(plan_path.read_text(encoding='utf-8'))
                plan['parentPid'] = 2147483646
                plan_path.write_text(json.dumps(plan), encoding='utf-8')
                env = {**os.environ, 'CFARA_UPDATE_PLAN': str(plan_path), 'CFARA_FAKE_TEST': 'ok' if healthy else 'failed'}
                script = base64.b64encode((stub + WINDOWS_HELPER).encode('utf-16-le')).decode('ascii')
                result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', script],
                                        env=env, capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((current / 'CelestialFulcrum.exe').read_text(), 'new' if healthy else 'old')
                self.assertEqual((data / 'save.json').read_text(), 'original save')
                self.assertTrue(Path(plan['backup'] if healthy else plan['failed']).is_dir())


if __name__ == '__main__':
    unittest.main()
