"""Own a native window and its loopback service; keep saves outside the bundle."""

import argparse
from configparser import ConfigParser, Error as ConfigError
from contextlib import contextmanager
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
from threading import Thread, Timer
import time
from urllib.request import urlopen, Request

from .runtime import ROOT
from .product import PROJECT
from .compat import configured_app_data, default_data_directory
from .diagnostics import public_error


def data_directory(override=None):
    if override:
        return Path(override).expanduser().resolve()
    configured = configured_app_data()
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share"))
    return default_data_directory(base)


def desktop_engine():
    return "cocoa" if sys.platform == "darwin" else "edgechromium" if sys.platform == "win32" else None


def check_windows_bundle_trust(root=ROOT):
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    assemblies = ("pythonnet/runtime/Python.Runtime.dll",
                  "webview/lib/Microsoft.Web.WebView2.Core.dll",
                  "webview/lib/Microsoft.Web.WebView2.WinForms.dll",
                  "webview/lib/WebBrowserInterop.x64.dll")
    for name in assemblies:
        path = Path(root) / name
        if not path.is_file():
            continue
        try:
            with Path(str(path) + ":Zone.Identifier").open(encoding="utf-8", errors="replace") as stream:
                text = stream.read(4096)
        except FileNotFoundError:
            continue
        except OSError:
            logging.warning("Could not inspect download zone for %s", path, exc_info=True)
            continue
        zone = ConfigParser(interpolation=None)
        try:
            zone.read_string(text.rstrip("\x00"))
            blocked = zone.getint("ZoneTransfer", "ZoneId", fallback=0) in (3, 4)
        except (ConfigError, ValueError):
            continue
        if blocked:
            raise RuntimeError(
                "下载的程序文件带有互联网标记，可能被 Windows 阻止加载桌面窗口组件。\n"
                "请关闭程序，在原 ZIP 文件上右键 → 属性 → 勾选“解除锁定” → 应用，然后重新完整解压。\n"
                "仅对确认来自本项目 GitHub 的程序包执行此操作，不必因本提示重装 WebView2。\n"
                f"受影响组件：{path.name}")


def startup_message(error, directory):
    text = public_error(error)
    if "Failed to resolve Python.Runtime.Loader.Initialize" in str(error):
        text = "桌面 .NET 桥接组件加载失败，请确认完整解压程序包、文件未被锁定，且系统已安装 .NET Framework 4.8。"
    elif "WebView2" in str(error) and not any("\u4e00" <= char <= "\u9fff" for char in str(error)):
        text = "WebView2 窗口组件加载失败，请确认系统已安装 Microsoft WebView2 Runtime，并查看日志。"
    return f"{text}\n\n日志位置：{directory / 'logs/desktop.log'}"


@contextmanager
def single_instance(directory):
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / "desktop.lock").open("a+b")
    locked = False
    unlock = None
    try:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RuntimeError("此存档目录已被另一个助手窗口使用，请先关闭它。") from error
            unlock = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RuntimeError("此存档目录已被另一个助手窗口使用，请先关闭它。") from error
            unlock = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        locked = True
        yield
    finally:
        if locked:
            lock.seek(0)
            unlock()
        lock.close()


class LocalServer:
    def __init__(self, directory, port=8767, *, update_install=None):
        import uvicorn
        from .service.app import create_app
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.bind(("127.0.0.1", port))
        except OSError:
            self.socket.close()
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        app = create_app(directory, allowed_origins=[self.url], update_install=update_install)
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port,
                                log_config=None, access_log=False)
        self.server = uvicorn.Server(config)
        self.thread = Thread(target=self.server.run, kwargs={"sockets": [self.socket]},
                             name="fulcrum-service", daemon=True)

    def start(self):
        self.thread.start()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.server.started:
                return self
            if not self.thread.is_alive():
                break
            time.sleep(.05)
        self.close()
        raise RuntimeError("本地服务启动失败，请查看 logs/desktop.log。")

    def close(self):
        self.server.should_exit = True
        if self.thread.ident is not None:
            self.thread.join(timeout=70)
            if self.thread.is_alive():
                raise RuntimeError("本地任务未能及时退出，请查看 logs/desktop.log。")
        self.socket.close()


def configure_logging(directory):
    logs = directory / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logs / "desktop.log", maxBytes=2_000_000,
                                 backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def self_test(server):
    import cv2
    import numpy as np
    from .service.catalog import editor_catalog
    from .service.store import RunStore
    from .vision_resources import _run_ocr
    from tempfile import TemporaryDirectory
    with urlopen(server.url + "/api/health", timeout=10) as response:
        health = json.load(response)
    with urlopen(server.url, timeout=10) as response:
        assert b"<html" in response.read().lower(), "frontend is missing"
    with urlopen(server.url + "/api/session", timeout=10) as response:
        token = json.load(response)["token"]
    with urlopen(Request(server.url + "/api/catalog", headers={"X-Fulcrum-Token": token}), timeout=20) as response:
        catalog = json.load(response)
    assert catalog["operators"] and editor_catalog()["relic"], "catalog is incomplete"
    image_count = 0
    for rows in catalog.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not row.get("imageUrl"):
                continue
            request = Request(server.url + row["imageUrl"], headers={"X-Fulcrum-Token": token})
            with urlopen(request, timeout=10) as response:
                pixels = cv2.imdecode(np.frombuffer(response.read(), np.uint8), cv2.IMREAD_UNCHANGED)
                assert pixels is not None and pixels.size, f"invalid catalog image: {row['id']}"
                image_count += 1
    with TemporaryDirectory() as temporary:
        store = RunStore(Path(temporary) / "runs")
        store.create("packaging-check")
        assert "## 3." in store.markdown("packaging-check"), "Markdown export failed"
    crop = np.full((100, 220), 255, dtype=np.uint8)
    cv2.putText(crop, "25", (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 2, 0, 3)
    ocr = _run_ocr({"digits": crop})["digits"]
    assert ocr["text"] == "25", f"offline OCR failed: {ocr}"
    capture_import = False
    if sys.platform == "win32":
        import windows_capture
        capture_import = bool(windows_capture)
    from .map_catalog import TemplateCatalog
    from .vision_relics import relic_atlas
    assert TemplateCatalog().templates, "map templates are missing"
    assert relic_atlas(), "relic templates are missing"
    return {"ok": True, "health": health, "offlineOCR": ocr,
            "operatorCount": len(catalog["operators"]), "nativeCaptureImport": capture_import,
            "platform": sys.platform, "windowCaptureSupported": sys.platform == "win32",
            "frontend": True, "markdownExport": True, "recognitionAssets": True,
            "catalogImageCount": image_count, "project": dict(PROJECT)}


def window_probe(window, result):
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready = window.evaluate_js("Boolean(document.querySelector('.app-header'))")
            if ready:
                result.update(ok=True, engine=desktop_engine(), frontendMounted=True)
                return
            time.sleep(.2)
        raise RuntimeError("桌面页面未能在30秒内加载，请查看日志并重试。")
    except Exception as error:
        result.update(ok=False, error=str(error))
    finally:
        window.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=PROJECT["englishName"])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--window-test", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.window_test and not args.report:
        parser.error("--window-test requires --report")
    directory = data_directory(args.data_dir)
    pending_update = []
    try:
        configure_logging(directory)
        with single_instance(directory):
            check_windows_bundle_trust()
            if not (ROOT / "frontend/dist/index.html").is_file():
                raise RuntimeError("前端尚未构建，请先执行打包脚本。")
            def install_update(staged):
                from .update_install import prepare_install
                plan = prepare_install(staged, directory, directory / "updates")
                pending_update.append(plan)
                Timer(.8, window.destroy).start()
            updater_enabled = getattr(sys, "frozen", False) and not args.self_test and not args.window_test
            server = LocalServer(directory, update_install=install_update if updater_enabled else None).start()
            try:
                if args.self_test:
                    result = self_test(server)
                    if args.report:
                        args.report.parent.mkdir(parents=True, exist_ok=True)
                        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                    return 0
                import webview
                webview.settings["ALLOW_DOWNLOADS"] = True
                version_path = ROOT / "build-info.json"
                revision = json.loads(version_path.read_text(encoding="utf-8")).get("revision", "dev") if version_path.is_file() else "dev"
                window = webview.create_window(f"{PROJECT['name']} · {revision[:8]}", server.url,
                                               width=1440, height=960, min_size=(1000, 700),
                                               hidden=args.window_test)
                probe = {}
                def check_window():
                    window_probe(window, probe)
                webview.start(check_window if args.window_test else None,
                              gui=desktop_engine(), debug=args.debug, private_mode=False,
                              storage_path=str(directory / "webview"))
                if args.window_test:
                    if not probe.get("ok"):
                        raise RuntimeError(probe.get("error", "程序窗口测试未完成。"))
                    args.report.parent.mkdir(parents=True, exist_ok=True)
                    args.report.write_text(json.dumps(probe, indent=2), encoding="utf-8")
            finally:
                server.close()
        if pending_update:
            from .update_install import launch_install
            launch_install(pending_update[0])
        return 0
    except Exception as error:
        logging.exception("Desktop startup or shutdown failed")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), encoding="utf-8")
        if not args.self_test and not args.window_test and sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, startup_message(error, directory), PROJECT["shortName"], 0x10)
        return 1
