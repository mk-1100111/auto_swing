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
                self.assertEqual(updater.update_program(root), "최신 버전")
            old.write_bytes(b"old version")
            with patch.object(updater, "read_json", side_effect=[release, manifest]), patch.object(updater, "urlopen", return_value=MemoryResponse(b"corrupt")):
                with self.assertRaises(updater.UpdateError):
                    updater.update_program(root)
            self.assertEqual(old.read_bytes(), b"old version")
            self.assertEqual(list(root.glob("*.part")), [])


if __name__ == "__main__":
    unittest.main()
