"""Resolve the local OCR runtime without relying on a user's development tools."""

from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def node_runtime() -> tuple[str, str]:
    bundled = ROOT / "runtime/node/bin" / ("node.exe" if sys.platform == "win32" else "node")
    if bundled.is_file():
        return str(bundled), str(bundled.parent.parent / "node_modules")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("本地资源文字识别需要 Node.js 运行环境")
    local_modules = ROOT / "node_modules"
    modules = local_modules if local_modules.is_dir() else Path(node).resolve().parent.parent / "node_modules"
    return node, str(modules)


def ocr_available() -> bool:
    try:
        node_runtime()
    except RuntimeError:
        return False
    return (ROOT / "eng.traineddata").is_file()
