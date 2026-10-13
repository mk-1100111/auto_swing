# -*- coding: utf-8 -*-
"""Tests for security checks and update safety (offline on any OS)."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import updater


class MemoryResponse:
    def __init__(self, data):
        from io import BytesIO
        self.data = BytesIO(data)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.data.close()
    def read(self, count=-1):
        return self.data.read(count)


class LauncherTests(unittest.TestCase):
    def test_manifest_rejection(self):
        for malformed in ({}, {"schema": 1, "app_asset": "evil.exe", "sha256": "a"*64, "bytes": 4},
                          {"schema": 1, "app_asset": updater.APP_FILENAME, "sha256": "f"*64, "bytes": -1}):
            with self.assertRaises(updater.UpdateError):
                updater.validate_manifest(malformed)

    def test_url_restricted_to_repo(self):
        self.assertTrue(updater.safe_asset_url("https://github.com/mk-1100111/auto_swing/releases/download/v1/SwingInspector.exe"))
        self.assertFalse(updater.safe_asset_url("https://example.com/mk-1100111/auto_swing/releases/download/v1/SwingInspector.exe"))
        self.assertFalse(updater.safe_asset_url("http://github.com/mk-1100111/auto_swing/releases/download/v1/SwingInspector.exe"))
        self.assertFalse(updater.safe_asset_url("https://github.com/other/repo/releases/download/v1/SwingInspector.exe"))

    def test_integrity_and_no_partial_replace(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            data = b"test-binary" * 100
            url = "https://github.com/mk-1100111/auto_swing/releases/download/v1/SwingInspector.exe"
            sha = hashlib.sha256(data).hexdigest()
            release = {"assets": [
                {"name": updater.MANIFEST_FILENAME, "browser_download_url": url.replace("SwingInspector.exe", updater.MANIFEST_FILENAME)},
                {"name": updater.APP_FILENAME, "browser_download_url": url, "size": len(data), "digest": "sha256:" + sha}
            ]}
            manifest = {"schema": 1, "app_asset": updater.APP_FILENAME, "sha256": sha, "bytes": len(data), "version": "test"}
            old = root / updater.APP_FILENAME
            old.write_bytes(b"old version")
            with patch.object(updater, "read_json", side_effect=[release, manifest]), patch.object(updater, "urlopen", return_value=MemoryResponse(data)):
                self.assertIn("업데이트 완료", updater.update_program(root))
            self.assertEqual(old.read_bytes(), data)
            with patch.object(updater, "read_json", side_effect=[release, manifest]), patch.object(updater, "urlopen", side_effect=AssertionError("should not download")):
                self.assertEqual(updater.update_program(root), "최신 버전 (test)")
            old.write_bytes(b"old version")
            with patch.object(updater, "read_json", side_effect=[release, manifest]), patch.object(updater, "urlopen", return_value=MemoryResponse(b"corrupt")):
                with self.assertRaises(updater.UpdateError):
                    updater.update_program(root)
            self.assertEqual(old.read_bytes(), b"old version")
            self.assertEqual(list(root.glob("*.part")), [])

    def test_launcher_handles_windowed_mode_without_stdio(self):
        """PyInstaller --windowed sets stdout and stderr to None."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / updater.APP_FILENAME).write_bytes(b"app")
            with (patch.object(updater, "local_dir", return_value=root),
                  patch.object(updater, "update_program", return_value="최신 버전 (build-test)"),
                  patch.object(updater, "run_app", return_value=0) as launch,
                  patch.object(updater, "write_log"),
                  patch.object(updater.sys, "stdout", None),
                  patch.object(updater.sys, "stderr", None)):
                self.assertEqual(updater.main(), 0)
                launch.assert_called_once()

    def test_locked_executable_can_retry_without_redownload(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            data = b"new-version" * 50
            sha = hashlib.sha256(data).hexdigest()
            url = "https://github.com/mk-1100111/auto_swing/releases/download/build-test/SwingInspector.exe"
            release = {"tag_name": "build-test", "assets": [
                {"name": updater.MANIFEST_FILENAME, "browser_download_url": url.replace("SwingInspector.exe", updater.MANIFEST_FILENAME)},
                {"name": updater.APP_FILENAME, "browser_download_url": url, "size": len(data), "digest": "sha256:" + sha}
            ]}
            manifest = {"schema": 1, "app_asset": updater.APP_FILENAME, "sha256": sha, "bytes": len(data), "version": "build-test"}
            old = root / updater.APP_FILENAME
            old.write_bytes(b"old")
            original_replace = updater.os.replace
            events = []
            def replace_once_locked(src, dst):
                events.append((src, dst))
                if len(events) == 1:
                    raise PermissionError("File in use")
                return original_replace(src, dst)
            with (patch.object(updater, "read_json", side_effect=[release, manifest]),
                  patch.object(updater, "urlopen", return_value=MemoryResponse(data)) as download,
                  patch.object(updater.os, "replace", side_effect=replace_once_locked),
                  patch.object(updater, "log_path", return_value=root / "launcher.log")):
                result = updater.update_program(root, on_file_locked=lambda e, n: True)
            self.assertIn("업데이트 완료", result)
            self.assertEqual(len(events), 2)
            self.assertEqual(download.call_count, 1)
            self.assertEqual(old.read_bytes(), data)

    def test_update_error_requires_explicit_user_choice(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / updater.APP_FILENAME).write_bytes(b"old")
            with (patch.object(updater, "local_dir", return_value=root),
                  patch.object(updater, "update_program", side_effect=updater.UpdateError("network denied")),
                  patch.object(updater, "choose_after_failure", return_value="abort") as prompt,
                  patch.object(updater, "run_app") as app,
                  patch.object(updater, "write_log")):
                self.assertEqual(updater.main(), 1)
                prompt.assert_called_once()
                app.assert_not_called()


if __name__ == "__main__":
    unittest.main()
