"""Capture a self-created test window; never photograph user apps."""

import ctypes
import argparse
from ctypes import wintypes as w
import json
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=("printwindow", "graphics"), default="printwindow")
    args = parser.parse_args()
    import cv2
    import numpy as np
    from fulcrum.window_capture import _apis
    user, _, kernel, _ = _apis()
    previous_dpi = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    kernel.GetModuleHandleW.argtypes, kernel.GetModuleHandleW.restype = [w.LPCWSTR], w.HMODULE
    user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p]
    user.CreateWindowExW.restype = w.HWND
    user.DestroyWindow.argtypes, user.DestroyWindow.restype = [w.HWND], w.BOOL
    user.UpdateWindow.argtypes, user.UpdateWindow.restype = [w.HWND], w.BOOL
    user.PeekMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    user.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
    # GPU capture needs an on-screen surface; this small probe never takes focus.
    location = 100 if args.method == "graphics" else -30000
    hwnd = user.CreateWindowExW(0x08000080, "STATIC", "Fulcrum capture probe", 0x90000000,
                               location, location, 320, 180, None, None, kernel.GetModuleHandleW(None), None)
    if not hwnd:
        raise RuntimeError(f"test window creation failed: {ctypes.get_last_error()}")
    try:
        user.UpdateWindow(hwnd)
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        worker = context.Process(target=probe_worker, args=(child, str(int(hwnd)), args.method))
        worker.start()
        child.close()
        message = w.MSG()
        import time
        deadline = time.monotonic() + 12
        while not parent.poll(.01):
            if time.monotonic() > deadline:
                worker.terminate()
                raise TimeoutError("native probe timeout")
            while user.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                user.DispatchMessageW(ctypes.byref(message))
        result = parent.recv()
        worker.join(2)
        parent.close()
        if "error" in result:
            raise RuntimeError(result["error"])
        image = cv2.imdecode(np.frombuffer(result["image"], dtype=np.uint8), cv2.IMREAD_COLOR)
        assert image.shape[:2] == (180, 320), image.shape
        output = ROOT / "work/service_smoke/window-probe.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(result["image"])
        print(json.dumps({"dimensions": [320, 180], "pixelStd": round(float(image.std()), 3),
                          "method": result["method"], "capturedUserApplication": False}))
    finally:
        user.DestroyWindow(hwnd)
        if previous_dpi:
            user.SetThreadDpiAwarenessContext(previous_dpi)


def probe_worker(connection, hwnd, method):
    from fulcrum.window_capture import capture_window, _apis
    try:
        # Parent owns the test window; the probe process has a different PID.
        user, _, _, _ = _apis()
        pid = w.DWORD()
        user.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        connection.send(capture_window(pid.value, hwnd, method=method, timeout=6))
    except Exception as error:
        connection.send({"error": str(error)})
    finally:
        connection.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
