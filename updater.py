# -*- coding: utf-8 -*-
"""Windows portable Swing Inspector launcher with verified GitHub updates.

The launcher is a PyInstaller --windowed EXE: never rely on sys.stdout/stderr.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO = "mk-1100111/auto_swing"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
APP_FILENAME = "SwingInspector.exe"
MANIFEST_FILENAME = "update_manifest.json"
MAX_APP_BYTES = 250 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024
NETWORK_TIMEOUT = 15
LAUNCHER_VERSION = "1.3.0"

# Windows MessageBox result codes and styles
IDABORT, IDRETRY, IDIGNORE = 3, 4, 5
IDCANCEL, IDTRYAGAIN = 2, 10
MB_OK = 0x0
MB_ICONERROR, MB_ICONWARNING, MB_ICONINFORMATION = 0x10, 0x30, 0x40
MB_RETRYCANCEL = 0x5
MB_ABORTRETRYIGNORE = 0x2


class UpdateError(Exception):
    pass


def local_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Swing_UIA_Inspector" / "launcher.log"
    return local_dir() / "launcher.log"


def write_log(message: str) -> None:
    """Best-effort local diagnostics; an inaccessible log must not break launch."""
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 1024 * 1024:
            # Retain recent diagnostic history without unlimited disk growth.
            data = path.read_bytes()[-128 * 1024:]
            path.write_bytes(data)
        with path.open("a", encoding="utf-8") as output:
            output.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except OSError:
        pass


def message_box(message: str, flags: int) -> int:
    try:
        import ctypes
        return ctypes.windll.user32.MessageBoxW(
            None, message, f"Swing UIA Inspector · Launcher {LAUNCHER_VERSION}", flags
        )
    except Exception:
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        return IDABORT  # Headless fallback: fail closed.


def safe_asset_url(url: str) -> bool:
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


def request_url(url: str) -> Request:
    return Request(url, headers={
        "User-Agent": f"auto-swing-launcher/{LAUNCHER_VERSION}",
        "Accept": "application/json" if url.startswith("https://api.github.com/") else "application/octet-stream",
        "Cache-Control": "no-cache",
    })


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
    matches = [a for a in assets if isinstance(a, dict) and a.get("name") == filename]
    if len(matches) != 1:
        raise UpdateError(f"GitHub Release에 {filename} 파일이 없습니다.")
    asset = matches[0]
    url = asset.get("browser_download_url")
    if not isinstance(url, str) or not safe_asset_url(url):
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


def ask_to_close_app(error: PermissionError, attempt: int) -> bool:
    """Only retry after user closes the already-running old EXE."""
    write_log(f"EXE 교체 실패: {error!r}; 대기 {attempt}/5")
    response = message_box(
        "최신 버전을 다운로드했지만 기존 SwingInspector.exe를 교체할 수 없습니다.\n\n"
        "실행 중인 Swing UIA Inspector 창을 모두 종료한 후 [다시 시도]를 선택하세요.\n"
        "[취소]를 누르면 업데이트를 중단합니다.\n\n"
        f"상세 오류: {error}",
        MB_RETRYCANCEL | MB_ICONWARNING,
    )
    return response == IDRETRY


def update_program(folder: Path, on_file_locked: Callable[[PermissionError, int], bool] | None = None) -> str:
    """Return '최신 버전' or '업데이트 완료 (...)'; raise on failure."""
    release = read_json(RELEASE_API, 1024 * 1024)
    manifest_asset = release_asset(release, MANIFEST_FILENAME)
    manifest = read_json(manifest_asset["browser_download_url"], MAX_MANIFEST_BYTES)
    expected_sha, expected_bytes = validate_manifest(manifest)
    exe_asset = release_asset(release, APP_FILENAME)
    asset_digest = exe_asset.get("digest")
    if asset_digest and asset_digest != "sha256:" + expected_sha:
        raise UpdateError("Release 파일 해시가 업데이트 목록과 다릅니다.")
    if exe_asset.get("size") != expected_bytes:
        raise UpdateError("Release 파일 크기가 업데이트 목록과 다릅니다.")

    current = folder / APP_FILENAME
    version = str(manifest.get("version") or release.get("tag_name") or "latest")
    if current.is_file() and digest_file(current) == expected_sha:
        return f"최신 버전 ({version})"

    # Download only once. On Windows an open EXE cannot be replaced; keep the
    # verified temp file ready while the user closes that application.
    tmp = folder / f".{APP_FILENAME}.{os.getpid()}.part"
    try:
        stream_verified_exe(exe_asset["browser_download_url"], tmp, expected_sha, expected_bytes)
        for attempt in range(1, 7):
            try:
                os.replace(tmp, current)
                return f"업데이트 완료 ({version})"
            except PermissionError as exc:
                if attempt >= 6 or on_file_locked is None or not on_file_locked(exc, attempt):
                    raise UpdateError("실행 중인 앱 또는 폴더 권한 때문에 EXE 교체가 차단됐습니다.") from exc
        raise UpdateError("파일 교체 재시도 횟수를 초과했습니다.")
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def choose_after_failure(exc: Exception) -> str:
    """Never silently launch a stale binary when update checking failed."""
    msg = (
        "GitHub에서 최신 버전을 확인하거나 설치하지 못했습니다.\n\n"
        f"오류: {exc}\n\n"
        "[다시 시도]: GitHub 업데이트 다시 확인\n"
        "[무시]: 기존 버전으로 실행\n"
        "[중단]: 프로그램 종료\n\n"
        f"오류 기록: {log_path()}"
    )
    selected = message_box(msg, MB_ABORTRETRYIGNORE | MB_ICONWARNING)
    return "retry" if selected == IDRETRY else "old" if selected == IDIGNORE else "abort"


def run_app(folder: Path, args: list[str] | None = None) -> int:
    exe = folder / APP_FILENAME
    if not exe.is_file():
        message_box("실행할 SwingInspector.exe 파일이 없습니다.\nRelease ZIP을 다시 압축 해제하세요.", MB_ICONERROR)
        return 1
    try:
        subprocess.Popen([str(exe), *(args or [])], cwd=str(folder), close_fds=True)
        write_log(f"앱 실행: {exe}")
    except OSError as exc:
        write_log(f"앱 실행 오류: {exc!r}")
        message_box(f"SwingInspector.exe 실행 실패:\n\n{exc}", MB_ICONERROR)
        return 1
    return 0


def main() -> int:
    folder = local_dir()
    write_log(f"런처 시작 v{LAUNCHER_VERSION} 경로: {folder}")
    # Explicit retry/cancel decisions ensure an old app never appears as if it
    # were successfully updated. Repeated network retries are bounded.
    for attempt in range(1, 4):
        try:
            outcome = update_program(folder, on_file_locked=ask_to_close_app)
            write_log(outcome)
            if outcome.startswith("업데이트 완료"):
                message_box(f"{outcome}\n\n최신 Swing UIA Inspector를 실행합니다.", MB_ICONINFORMATION)
            return run_app(folder, sys.argv[1:])
        except (OSError, HTTPError, URLError, ValueError, KeyError, UpdateError) as exc:
            write_log(f"업데이트 오류 {attempt}/3: {type(exc).__name__}: {exc}")
            decision = choose_after_failure(exc)
            if decision == "retry" and attempt < 3:
                continue
            if decision == "old":
                write_log("사용자 선택: 이전 버전 실행")
                return run_app(folder, sys.argv[1:])
            if decision == "retry":
                message_box("업데이트 재시도 횟수를 초과했습니다. 런처를 종료합니다.", MB_ICONERROR)
            return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
