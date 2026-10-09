"""Explicit Windows window capture; never focus, inject into or operate a game."""

import ctypes
from ctypes import wintypes as w
import multiprocessing as mp
from pathlib import Path
import sys
import math


class CaptureUnavailable(RuntimeError):
    pass


def _apis():
    if sys.platform != "win32":
        raise CaptureUnavailable("window capture currently requires Windows")
    user = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    signatures = {
        "EnumWindows": ([callback, w.LPARAM], w.BOOL), "IsWindow": ([w.HWND], w.BOOL),
        "IsWindowVisible": ([w.HWND], w.BOOL), "IsIconic": ([w.HWND], w.BOOL),
        "GetWindowTextW": ([w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
        "GetWindowThreadProcessId": ([w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
        "GetClientRect": ([w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
        "GetWindowRect": ([w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
        "ClientToScreen": ([w.HWND, ctypes.POINTER(w.POINT)], w.BOOL),
        "GetDC": ([w.HWND], w.HDC), "ReleaseDC": ([w.HWND, w.HDC], ctypes.c_int),
        "PrintWindow": ([w.HWND, w.HDC, w.UINT], w.BOOL),
        "GetSystemMetrics": ([ctypes.c_int], ctypes.c_int),
        "GetForegroundWindow": ([], w.HWND),
        "SetThreadDpiAwarenessContext": ([w.HANDLE], w.HANDLE),
    }
    for name, (args, result) in signatures.items():
        function = getattr(user, name)
        function.argtypes, function.restype = args, result
    for name, args, result in (
        ("CreateCompatibleDC", [w.HDC], w.HDC),
        ("CreateCompatibleBitmap", [w.HDC, ctypes.c_int, ctypes.c_int], w.HBITMAP),
        ("SelectObject", [w.HDC, w.HANDLE], w.HANDLE),
        ("BitBlt", [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    w.HDC, ctypes.c_int, ctypes.c_int, w.DWORD], w.BOOL),
        ("GetDIBits", [w.HDC, w.HBITMAP, w.UINT, w.UINT, ctypes.c_void_p, ctypes.c_void_p, w.UINT], ctypes.c_int),
        ("DeleteObject", [w.HANDLE], w.BOOL), ("DeleteDC", [w.HDC], w.BOOL),
    ):
        function = getattr(gdi, name)
        function.argtypes, function.restype = args, result
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = w.BOOL
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    return user, gdi, kernel, callback


def _window_info(user, kernel, hwnd):
    pid = w.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    title = ctypes.create_unicode_buffer(2048)
    user.GetWindowTextW(hwnd, title, len(title))
    rect, point = w.RECT(), w.POINT()
    if not user.GetClientRect(hwnd, ctypes.byref(rect)) or not user.ClientToScreen(hwnd, ctypes.byref(point)):
        raise CaptureUnavailable("window client rectangle unavailable")
    process = None
    handle = kernel.OpenProcess(0x1000, False, pid.value)
    if handle:
        try:
            size = w.DWORD(32768)
            name = ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
                process = Path(name.value).name
        finally:
            kernel.CloseHandle(handle)
    return {"windowId": str(int(hwnd)), "pid": pid.value, "title": title.value, "process": process,
            "foreground": int(user.GetForegroundWindow() or 0) == int(hwnd),
            "minimized": bool(user.IsIconic(hwnd)),
            "clientRect": {"x": point.x, "y": point.y, "width": rect.right, "height": rect.bottom}}


def list_windows(pid=None):
    if pid is not None and (type(pid) is not int or pid < 1):
        raise ValueError("PID must be a positive integer")
    user, _, kernel, callback = _apis()
    previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    rows = []
    @callback
    def visit(hwnd, _):
        if user.IsWindowVisible(hwnd):
            try:
                info = _window_info(user, kernel, hwnd)
                rect = info["clientRect"]
                if info["title"] and rect["width"] > 0 and rect["height"] > 0 and (pid is None or pid == info["pid"]):
                    rows.append(info)
            except CaptureUnavailable:
                pass
        return True
    try:
        if not user.EnumWindows(visit, 0):
            raise CaptureUnavailable(f"could not enumerate windows (WinError {ctypes.get_last_error()}); run outside an isolated desktop")
    finally:
        if previous:
            user.SetThreadDpiAwarenessContext(previous)
    return rows


def select_window(pid, window_id=None):
    rows = list_windows(pid)
    if window_id is not None:
        rows = [row for row in rows if row["windowId"] == str(window_id)]
    if len(rows) != 1:
        raise CaptureUnavailable("select one visible window from the requested process; selection is missing or ambiguous")
    if rows[0]["minimized"]:
        raise CaptureUnavailable("restore the selected window before capture")
    return rows[0]


class _BitmapHeader(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG), ("planes", w.WORD),
                ("bits", w.WORD), ("compression", w.DWORD), ("imageSize", w.DWORD),
                ("xppm", w.LONG), ("yppm", w.LONG), ("colors", w.DWORD), ("important", w.DWORD)]


def _crop_client_frame(image, client, window_bounds):
    height, width = image.shape[:2]
    if (width, height) == (client["width"], client["height"]):
        return image.copy()
    for left, top, right, bottom in window_bounds:
        if abs(right - left - width) > 2 or abs(bottom - top - height) > 2:
            continue
        x, y = client["x"] - left, client["y"] - top
        cw, ch = client["width"], client["height"]
        if min(x, y) >= 0 and x + cw <= width and y + ch <= height:
            return image[y:y + ch, x:x + cw].copy()
    raise CaptureUnavailable("captured window size changed or client area could not be located; retry capture")


def _capture_graphics(user, kernel, hwnd, selected):
    try:
        from windows_capture import WindowsCapture
    except ImportError as error:
        raise CaptureUnavailable("Windows Graphics Capture dependency is not installed") from error
    capture = WindowsCapture(cursor_capture=False, draw_border=True, secondary_window=False, window_hwnd=hwnd)
    result = {}

    @capture.event
    def on_frame_arrived(frame, capture_control):
        try:
            info = _window_info(user, kernel, hwnd)
            if info["pid"] != selected["pid"] or info["clientRect"] != selected["clientRect"]:
                raise CaptureUnavailable("selected window changed during capture; retry")
            bounds = []
            rect = w.RECT()
            if user.GetWindowRect(hwnd, ctypes.byref(rect)):
                bounds.append((rect.left, rect.top, rect.right, rect.bottom))
            dwm = ctypes.WinDLL("dwmapi")
            dwm.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, ctypes.c_void_p, w.DWORD]
            dwm.DwmGetWindowAttribute.restype = ctypes.c_long
            if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) == 0:
                bounds.append((rect.left, rect.top, rect.right, rect.bottom))
            result["image"] = _crop_client_frame(frame.frame_buffer[..., :3], info["clientRect"], bounds)
        except Exception as error:
            result["error"] = str(error)
        finally:
            capture_control.stop()

    @capture.event
    def on_closed():
        pass

    capture.start()
    if "error" in result:
        raise CaptureUnavailable(result["error"])
    if "image" not in result:
        raise CaptureUnavailable("selected window closed before a frame arrived")
    return result["image"]


def _capture_gdi(user, gdi, hwnd, rect, method):
    import numpy as np
    width, height = rect["width"], rect["height"]
    dc = user.GetDC(None)
    memory = bitmap = old = None
    try:
        memory = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
        if not dc or not memory or not bitmap:
            raise CaptureUnavailable("could not allocate capture bitmap")
        old = gdi.SelectObject(memory, bitmap)
        success = (user.PrintWindow(hwnd, memory, 3) if method == "printwindow" else
                   gdi.BitBlt(memory, 0, 0, width, height, dc, rect["x"], rect["y"], 0x40CC0020))
        if not success:
            raise CaptureUnavailable("PrintWindow failed; choose Windows Graphics Capture or explicitly select screen capture"
                                     if method == "printwindow" else "screen capture API failed")
        gdi.SelectObject(memory, old)
        old = None
        header = _BitmapHeader(ctypes.sizeof(_BitmapHeader), width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
        buffer = (ctypes.c_ubyte * (width * height * 4))()
        if gdi.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(header), 0) != height:
            raise CaptureUnavailable("could not read capture pixels")
        return np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
    finally:
        if old and memory:
            gdi.SelectObject(memory, old)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        if dc:
            user.ReleaseDC(None, dc)


def _capture_worker(connection, selected, method, crop):
    try:
        import cv2
        import numpy as np
        user, gdi, kernel, _ = _apis()
        user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        hwnd = int(selected["windowId"])
        if not user.IsWindow(hwnd) or not user.IsWindowVisible(hwnd) or user.IsIconic(hwnd):
            raise CaptureUnavailable("selected window is no longer visible")
        info = _window_info(user, kernel, hwnd)
        if info["pid"] != selected["pid"]:
            raise CaptureUnavailable("window handle was reused by a different process")
        rect = info["clientRect"]
        width, height = rect["width"], rect["height"]
        if width <= 0 or height <= 0 or width * height > 16000000:
            raise CaptureUnavailable("unsupported window dimensions")
        if method == "screen":
            vx, vy, vw, vh = [user.GetSystemMetrics(i) for i in (76, 77, 78, 79)]
            if rect["x"] < vx or rect["y"] < vy or rect["x"] + width > vx + vw or rect["y"] + height > vy + vh:
                raise CaptureUnavailable("screen capture requires the entire client area to be on screen")
        image = (_capture_graphics(user, kernel, hwnd, info) if method == "graphics" else
                 _capture_gdi(user, gdi, hwnd, rect, method))
        if crop is not None:
            x, y, cw, ch = crop
            if min(x, y) < 0 or min(cw, ch) < 1 or x + cw > width or y + ch > height:
                raise ValueError("crop must be within the selected window client area")
            image = image[y:y + ch, x:x + cw].copy()
        if float(image.std()) < 1:
            raise CaptureUnavailable("capture is blank; GPU windows may need explicit screen capture")
        success, encoded = cv2.imencode(".png", image)
        if not success:
            raise CaptureUnavailable("could not encode capture")
        connection.send({"image": encoded.tobytes(), "window": info, "method": method,
                         "warnings": ["屏幕截图可能包含其他窗口的遮挡；请核对预览。"] if method == "screen" else []})
    except Exception as error:
        connection.send({"error": str(error)})
    finally:
        connection.close()


def capture_window(pid, window_id=None, *, method="graphics", crop=None, timeout=6):
    if method not in {"graphics", "printwindow", "screen"}:
        raise ValueError("capture method must be graphics, printwindow or screen")
    if crop is not None and (not isinstance(crop, (list, tuple)) or len(crop) != 4 or any(type(v) is not int for v in crop)):
        raise ValueError("crop is [x,y,width,height] in physical pixels")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ValueError("capture timeout must be within (0,30] seconds")
    if crop is not None and (min(crop[:2]) < 0 or min(crop[2:]) < 1):
        raise ValueError("invalid crop rectangle")
    selected = select_window(pid, window_id)
    context = mp.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_capture_worker, args=(child, selected, method, crop))
    try:
        process.start()
    except Exception:
        parent.close()
        child.close()
        raise
    child.close()
    try:
        if not parent.poll(timeout):
            raise CaptureUnavailable("window capture timed out")
        result = parent.recv()
        if "error" in result:
            raise CaptureUnavailable(result["error"])
        return result
    except EOFError as error:
        raise CaptureUnavailable("capture worker exited without an image") from error
    finally:
        parent.close()
        process.join(.2)
        if process.is_alive():
            process.terminate()
            process.join(1)
