from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

from PIL import Image


OCR_URL = "https://arkrog.com/api/map-recognition/ocr"
LOGIN_URL = "https://arkrog.com/api/user/login"
USER_ID_URL = "https://arkrog.com/api/user/id"


def prepare_image(path: Path, max_dimension: int = 1600, quality: int = 85) -> bytes:
    image = Image.open(path).convert("RGB")
    scale = min(1.0, max_dimension / max(image.size))
    if scale < 1.0:
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def build_opener(cookie_jar: CookieJar | None = None):
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar or CookieJar()))


def post_json(opener, url: str, payload: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://arkrog.com",
            "Referer": "https://arkrog.com/tool/blackflowmap",
        },
    )
    try:
        with opener.open(req, timeout=60) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def get_text(opener, url: str) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://arkrog.com/tool/blackflowmap",
        },
    )
    try:
        with opener.open(req, timeout=60) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def login(opener, username: str, password: str) -> tuple[int, str]:
    password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return post_json(opener, LOGIN_URL, {"username": username, "hash": password_hash})


def post_ocr(opener, image_bytes: bytes) -> tuple[int, str]:
    req = urllib.request.Request(
        OCR_URL,
        data=image_bytes,
        method="POST",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/octet-stream",
            "Referer": "https://arkrog.com/tool/blackflowmap",
        },
    )
    try:
        with opener.open(req, timeout=60) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="Call arkrog blackflowmap OCR for a screenshot.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--username")
    parser.add_argument("--password")
    args = parser.parse_args()

    opener = build_opener()
    if args.username and args.password:
        status, body = login(opener, args.username, args.password)
        print("login status", status)
        try:
            print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            print(body)
        if status >= 400:
            return 1
        status, body = get_text(opener, USER_ID_URL)
        print("user status", status)
        try:
            print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            print(body)

    image_bytes = prepare_image(args.image)
    print(f"prepared JPEG bytes={len(image_bytes)}")
    status, body = post_ocr(opener, image_bytes)
    print("status", status)
    try:
        print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
