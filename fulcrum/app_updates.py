"""Opt-in, checksum-verified whole-package updates from this project's Releases."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import sys
from threading import Event, RLock
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4
import zipfile

from .product import PROJECT

REPOSITORY = "YLFF/celestial-fulcrum"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=100"
MAX_ARCHIVE_BYTES = 600 * 1024 * 1024
MAX_EXTRACT_BYTES = 2 * 1024 * 1024 * 1024


def version_tuple(value):
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", str(value))
    return tuple(map(int, match.groups())) if match else None


def platform_key():
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "win-x64"
    if sys.platform == "darwin" and machine == "arm64":
        return "mac-arm64"
    return None


def trusted_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("更新链接不是可信的 HTTPS 地址")
    if parsed.hostname == "api.github.com" and parsed.path.startswith(f"/repos/{REPOSITORY}/"):
        return url
    if parsed.hostname == "github.com" and parsed.path.startswith(f"/{REPOSITORY}/releases/download/"):
        return url
    if parsed.hostname in {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}:
        return url
    raise ValueError("更新链接不属于本项目的 GitHub 发行源")


class TrustedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_release_url(url):
    return build_opener(TrustedRedirect()).open(Request(trusted_url(url), headers={
        "User-Agent": f"CFARA/{PROJECT['version']}", "Accept": "application/vnd.github+json" if "api.github.com/" in url else "application/octet-stream",
    }), timeout=30)


def release_candidate(releases, current_version, target):
    current = version_tuple(current_version)
    if current is None:
        raise ValueError("当前版本格式不支持自动更新")
    stable = [row for row in releases if not row.get("draft") and not row.get("prerelease")
              and version_tuple(row.get("tag_name")) is not None]
    newer = [row for row in stable if version_tuple(row["tag_name"]) > current]
    if not newer:
        return None
    release = max(newer, key=lambda row: version_tuple(row["tag_name"]))
    packages = [asset for asset in release.get("assets", []) if re.fullmatch(
        rf"CelestialFulcrum-[a-f0-9]{{8}}-{re.escape(target or 'unsupported')}.zip", asset.get("name", ""))]
    if len(packages) != 1:
        raise ValueError("最新版本尚无适合本机的唯一发行包，请稍后重试")
    asset = packages[0]
    trusted_url(asset["browser_download_url"])
    size = asset.get("size")
    if type(size) is not int or not 0 < size <= MAX_ARCHIVE_BYTES:
        raise ValueError("发行包大小异常")
    digest = asset.get("digest", "") or ""
    checksum = next((row for row in release.get("assets", []) if row.get("name") == asset["name"] + ".sha256"), None)
    if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest) and not checksum:
        raise ValueError("发行包缺少 SHA-256 校验信息，暂不自动下载")
    return {"version": release["tag_name"].lstrip("v"), "notes": str(release.get("body") or "")[:20000],
            "name": asset["name"], "size": size, "url": asset["browser_download_url"],
            "digest": digest[7:].lower() if digest.startswith("sha256:") else None,
            "checksumUrl": checksum["browser_download_url"] if checksum else None}


def unpack_package(archive, destination, version, target):
    expected_root = "CelestialFulcrum" if target == "win-x64" else "CelestialFulcrum.app"
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 80000 or sum(row.file_size for row in members) > MAX_EXTRACT_BYTES:
            raise ValueError("发行包展开大小异常")
        seen, links = set(), []
        for member in members:
            name = member.filename
            path = PurePosixPath(name)
            if "\\" in name or ":" in name or path.is_absolute() or any(part in {"..", "."} for part in name.split("/")):
                raise ValueError("发行包包含越界路径")
            if not path.parts or path.parts[0] not in {expected_root, "__MACOSX"}:
                raise ValueError("发行包目录结构不符合要求")
            key = name.rstrip("/").casefold()
            if key in seen or member.flag_bits & 1:
                raise ValueError("发行包存在重复路径或加密文件")
            seen.add(key)
            if path.parts[0] == "__MACOSX":
                continue
            output = destination.joinpath(*path.parts)
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                if target != "mac-arm64" or member.file_size > 4096:
                    raise ValueError("发行包包含不允许的符号链接")
                link = bundle.read(member).decode("utf-8")
                resolved = (output.parent / link).resolve()
                if Path(link).is_absolute() or not resolved.is_relative_to(destination / expected_root):
                    raise ValueError("发行包符号链接越界")
                links.append((output, link))
                continue
            if member.is_dir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, output.open("xb") as sink:
                    shutil.copyfileobj(source, sink)
                if target == "mac-arm64":
                    output.chmod(mode & 0o777 or 0o644)
        # Extract regular files before links, so archive order cannot redirect a write.
        for output, link in links:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.symlink_to(link)
    app = destination / expected_root
    info_path = app / ("build-info.json" if target == "win-x64" else "Contents/Resources/build-info.json")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    expected = ("win32", "x64") if target == "win-x64" else ("darwin", "arm64")
    if (info.get("platform"), info.get("architecture")) != expected or info.get("project", {}).get("version") != version:
        raise ValueError("发行包版本或平台与更新信息不一致")
    if info.get("project", {}).get("executableName") != "CelestialFulcrum" or info.get("dirty"):
        raise ValueError("发行包不是已提交的正式应用构建")
    executable = app / ("CelestialFulcrum.exe" if target == "win-x64" else "Contents/MacOS/CelestialFulcrum")
    if not executable.is_file():
        raise ValueError("发行包缺少主程序")
    return app


class AppUpdater:
    def __init__(self, root, *, install=None):
        self.root = Path(root).resolve()
        self.install = install
        self.lock = RLock()
        self.stopping = Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cfara-update")
        self.target, self.candidate, self.staged = platform_key(), None, None
        self.state = {"status": "idle", "currentVersion": PROJECT["version"], "platform": self.target,
                      "canInstall": bool(install and self.target), "releasePage": RELEASES_URL}

    def snapshot(self):
        with self.lock:
            return deepcopy(self.state)

    def action(self, action):
        with self.lock:
            if self.state["status"] in {"checking", "downloading", "installing"}:
                raise ValueError("更新任务正在进行，请稍候")
            if action == "check":
                self.state.update(status="checking", error=None, downloadedBytes=0)
                self.pool.submit(self._run, self._check)
            elif action == "download" and self.candidate and self.state["status"] == "available":
                self.state.update(status="downloading", error=None, downloadedBytes=0)
                self.pool.submit(self._run, self._download)
            elif action == "install" and self.staged and self.state["status"] == "ready" and self.install:
                self.install(self.staged)
                self.state.update(status="installing")
            else:
                raise ValueError("当前不能执行该更新操作，请重新检查版本")
        return self.snapshot()

    def _set(self, **values):
        with self.lock:
            self.state.update(values)

    def _run(self, operation):
        try:
            operation()
        except Exception as error:
            logging.getLogger(__name__).exception("应用更新失败")
            text = "检查或下载失败，请检查网络后重试。"
            if isinstance(error, ValueError):
                text = str(error)
            elif isinstance(error, HTTPError) and error.code == 404:
                text = "未找到公开发行版；私有仓库需先公开发行资源，本应用不保存 GitHub 登录凭据。"
            self._set(status="error", error=text)

    def _check(self):
        if self.stopping.is_set():
            return
        if not self.target:
            raise ValueError("当前平台暂不支持整包更新")
        with open_release_url(API_URL) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("发行信息过大")
        releases = json.loads(raw)
        if not isinstance(releases, list):
            raise ValueError("发行信息格式不正确")
        candidate = release_candidate(releases, PROJECT["version"], self.target)
        with self.lock:
            self.candidate, self.staged = candidate, None
            self.state.pop("release", None)
            self.state.update(status="available" if candidate else "upToDate")
            if candidate:
                self.state["release"] = {key: candidate[key] for key in ("version", "name", "size", "notes")}

    def _download(self):
        if self.stopping.is_set():
            return
        candidate = deepcopy(self.candidate)
        digest = candidate["digest"]
        if not digest:
            with open_release_url(candidate["checksumUrl"]) as response:
                checksum = response.read(4097).decode("utf-8").strip()
            if not re.fullmatch(rf"[a-fA-F0-9]{{64}}\s+\*?{re.escape(candidate['name'])}", checksum):
                raise ValueError("SHA-256 校验文件不匹配")
            digest = checksum[:64].lower()
        attempt = self.root / uuid4().hex
        attempt.mkdir(parents=True)
        archive = attempt / "package.zip"
        sha, count = hashlib.sha256(), 0
        with open_release_url(candidate["url"]) as response, archive.open("xb") as sink:
            while chunk := response.read(1024 * 1024):
                if self.stopping.is_set():
                    return
                count += len(chunk)
                if count > candidate["size"] or count > MAX_ARCHIVE_BYTES:
                    raise ValueError("下载内容超出发行包大小")
                sha.update(chunk)
                sink.write(chunk)
                self._set(downloadedBytes=count)
        if count != candidate["size"] or sha.hexdigest() != digest:
            raise ValueError("下载内容未通过 SHA-256 校验，请重新检查更新")
        if self.stopping.is_set():
            return
        staged = unpack_package(archive, attempt / "expanded", candidate["version"], self.target)
        with self.lock:
            self.staged = staged
            self.state.update(status="ready")

    def close(self):
        self.stopping.set()
        self.pool.shutdown(wait=True)
