# -*- coding: utf-8 -*-
"""Portable Windows launcher: update SwingInspector.exe before opening it.

Only the public, fixed GitHub repository is contacted. Notes and settings are
stored by the app in LOCALAPPDATA and never touched by this launcher.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO = "mk-1100111/auto_swing"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
APP_FILENAME = "SwingInspector.exe"
MANIFEST_FILENAME = "update_manifest.json"
MAX_APP_BYTES = 250 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024
NETWORK_TIMEOUT = 10


class UpdateError(Exception):
    pass


def local_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def safe_asset_url(url: str) -> bool:
    """Restrict initial download URLs to *this* repo's release assets."""
    u = urlparse(url)
    return (
        u.scheme == "https"
        and u.hostname == "github.com"
        and u.username is None
        and u.password is None
        and u.port in (None, 443)
        and u.path.startswith(f"/{REPO}/releases/download/")
        and not u.fragment
    )


def request_url(url: str):
    return Request(url, headers={"User-Agent": "auto-swing-launcher/1.0", "Accept": "application/json"})


def read_json(url: str, limit: int) -> dict:
    with urlopen(request_url(url), timeout=NETWORK_TIMEOUT) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("서버 응답이 허용된 크기를 초과했습니다.")
    result = json.loads(data.decode("utf-8-sig"))
    if not isinstance(result, dict):
        raise UpdateError("서버 응답 형식이 올바르지 않습니다.")
    return result


def digest_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def validate_manifest(m: dict) -> tuple[str, int]:
    if m.get("schema") != 1 or m.get("app_asset") != APP_FILENAME:
        raise UpdateError("지원하지 않는 업데이트 목록입니다.")
    sha = str(m.get("sha256", ""))
    size = m.get("bytes")
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise UpdateError("업데이트 파일의 SHA256 값이 유효하지 않습니다.")
    if type(size) is not int or not 0 < size <= MAX_APP_BYTES:
        raise UpdateError("업데이트 파일의 크기가 유효하지 않습니다.")
    return sha, size


def release_asset(release: dict, filename: str) -> dict:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("GitHub Release 파일 목록을 읽을 수 없습니다.")
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == filename]
    if len(matches) != 1:
        raise UpdateError(f"GitHub Release에 {filename} 파일이 없습니다.")
    asset = matches[0]
    if not isinstance(asset.get("browser_download_url"), str) or not safe_asset_url(asset["browser_download_url"]):
        raise UpdateError("업데이트 다운로드 주소가 허용되지 않았습니다.")
    return asset


def stream_verified_exe(url: str, destination: Path, expected_sha: str, expected_bytes: int) -> None:
    downloaded = 0
    sha = hashlib.sha256()
    with urlopen(request_url(url), timeout=NETWORK_TIMEOUT) as source, destination.open("xb") as target:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            downloaded += len(block)
            if downloaded > expected_bytes or downloaded > MAX_APP_BYTES:
                raise UpdateError("다운로드 크기가 예상 크기보다 큽니다.")
            sha.update(block)
            target.write(block)
        target.flush()
        os.fsync(target.fileno())
    if downloaded != expected_bytes or sha.hexdigest() != expected_sha:
        raise UpdateError("업데이트 파일 SHA256 또는 크기 검증 실패. 기존 버전을 유지합니다.")


def update_program(folder: Path) -> str:
    """Get latest release and install safely. Raises, caller runs old binary."""
    release = read_json(RELEASE_API, 1024 * 1024)
    manifest_asset = release_asset(release, MANIFEST_FILENAME)
    manifest = read_json(manifest_asset["browser_download_url"], MAX_MANIFEST_BYTES)
    expected_sha, expected_bytes = validate_manifest(manifest)
    exe_asset = release_asset(release, APP_FILENAME)
    # GitHub's own digest is optional. If published, enforce agreement.
    asset_digest = exe_asset.get("digest")
    if asset_digest and asset_digest != "sha256:" + expected_sha:
        raise UpdateError("Release 파일 해시가 업데이트 목록과 다릅니다.")
    if exe_asset.get("size") != expected_bytes:
        raise UpdateError("Release 파일 크기가 업데이트 목록과 다릅니다.")
    current = folder / APP_FILENAME
    if current.is_file() and digest_file(current) == expected_sha:
        return "최신 버전"
    # Download to unique sidecar file on the same volume, then atomically swap.
    tmp = folder / f".{APP_FILENAME}.{os.getpid()}.part"
    try:
        stream_verified_exe(exe_asset["browser_download_url"], tmp, expected_sha, expected_bytes)
        # This will fail on Windows if another instance is using the .exe.
        # In that case the previous verified executable remains untouched.
        os.replace(tmp, current)
        return f"업데이트 완료 ({manifest.get('version', 'latest')})"
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def show_error(message: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "Swing UIA Inspector", 0x10)
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    folder = local_dir()
    exe = folder / APP_FILENAME
    try:
        outcome = update_program(folder)
        print(outcome)
    except (OSError, HTTPError, URLError, ValueError, KeyError, UpdateError) as exc:
        # An offline workstation must be able to open its installed version.
        print(f"업데이트 확인 실패. 기존 버전으로 실행합니다: {exc}", file=sys.stderr)
        if not exe.is_file():
            show_error("최초 설치에 필요한 인터넷 연결을 확인하세요.\n\n" + str(exc))
            return 1
    if not exe.is_file():
        show_error("실행할 SwingInspector.exe 파일을 찾을 수 없습니다.")
        return 1
    try:
        subprocess.Popen([str(exe), *sys.argv[1:]], cwd=str(folder), close_fds=True)
    except OSError as exc:
        show_error(f"SwingInspector.exe 실행에 실패했습니다.\n\n{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
