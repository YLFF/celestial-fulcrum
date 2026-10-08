"""Local session authentication and target-scoped native capture grants."""

import secrets
from threading import RLock
import time

from fastapi import HTTPException


def local_client(request):
    return request.client is not None and request.client.host in {"127.0.0.1", "::1", "testclient"}


class AccessPolicy:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.grants = {}
        self.lock = RLock()

    def valid_host(self, host):
        return host in {"localhost", "127.0.0.1", "::1", "testserver"}

    def authorize(self, request, value):
        if value and local_client(request) and secrets.compare_digest(value, self.token):
            return "local"
        raise HTTPException(401, "session token required")

    def grant_capture(self, pid, window_id):
        key = secrets.token_urlsafe(24)
        with self.lock:
            self.grants[key] = (pid, window_id, time.monotonic() + 600)
        return {"authorizationId": key, "pid": pid, "windowId": window_id, "expiresInSeconds": 600}

    def check_capture(self, key, pid, window_id):
        with self.lock:
            saved = self.grants.get(key)
        if not saved or saved[:2] != (pid, window_id) or saved[2] <= time.monotonic():
            raise HTTPException(403, "authorize this window before capture")

    def revoke_capture(self, key):
        with self.lock:
            self.grants.pop(key, None)
