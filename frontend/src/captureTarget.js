export function captureTarget(window) {
  return { pid: window.pid, windowId: window.windowId, process: window.process };
}

export function rememberedCaptureWindow(windows, saved) {
  if (!saved || !Number.isInteger(saved.pid) || !saved.process) return null;
  const available = windows.filter(row => row.pid === saved.pid && row.process === saved.process && !row.minimized);
  return available.find(row => row.windowId === saved.windowId) || (available.length === 1 ? available[0] : null);
}
