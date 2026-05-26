"""Unit tests for ArtifactStore implementations and CacheSync — M7.

Tests use mocked HTTP responses so no real server is needed.

Run:
    python src/tests/test_store.py
    python -m pytest src/tests/test_store.py -v
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch, call

_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from netos_build.store import ArtifactStore, LocalStore, HttpStore
from netos_build.store_factory import StoreFactory
from netos_build.cache_sync import CacheSync


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_response(status: int, body: bytes = b"") -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__  = MagicMock(return_value=False)
    resp.read      = MagicMock(side_effect=[body, b""])
    return resp


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://fake/", code=code, msg="Fake", hdrs=None, fp=None  # type: ignore
    )


# ---------------------------------------------------------------------------
# LocalStore
# ---------------------------------------------------------------------------

class TestLocalStore(unittest.TestCase):

    def setUp(self):
        self.store = LocalStore()

    def test_is_local(self):
        self.assertTrue(self.store.is_local)

    def test_exists_always_false(self):
        self.assertFalse(self.store.exists("any/key.tar.gz"))

    def test_download_always_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.store.download("key", Path(tmp) / "out.tar.gz")
        self.assertFalse(result)

    def test_upload_always_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "file.tar.gz"
            f.write_bytes(b"data")
            result = self.store.upload("key", f)
        self.assertFalse(result)

    def test_repr(self):
        self.assertIn("LocalStore", repr(self.store))


# ---------------------------------------------------------------------------
# HttpStore — exists
# ---------------------------------------------------------------------------

class TestHttpStoreExists(unittest.TestCase):

    def setUp(self):
        self.store = HttpStore("http://cache.local:9000", timeout=10)

    def test_exists_true_on_200(self):
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = _fake_response(200)
            self.assertTrue(self.store.exists("toolchains/arm64.tar.gz"))

    def test_exists_false_on_404(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(404)):
            self.assertFalse(self.store.exists("toolchains/missing.tar.gz"))

    def test_exists_raises_on_500(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(500)):
            with self.assertRaises(urllib.error.HTTPError):
                self.store.exists("toolchains/bad.tar.gz")

    def test_exists_false_on_oserror(self):
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            self.assertFalse(self.store.exists("toolchains/unreachable.tar.gz"))


# ---------------------------------------------------------------------------
# HttpStore — download
# ---------------------------------------------------------------------------

class TestHttpStoreDownload(unittest.TestCase):

    def setUp(self):
        self.store = HttpStore("http://cache.local:9000", timeout=10)

    def test_download_success(self):
        content = b"fake-archive-bytes"
        resp = _fake_response(200, content)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "archive.tar.gz"
            with patch("urllib.request.urlopen", return_value=resp):
                result = self.store.download("toolchains/arm64.tar.gz", dest)
            self.assertTrue(result)
            self.assertEqual(dest.read_bytes(), content)

    def test_download_returns_false_on_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "archive.tar.gz"
            with patch("urllib.request.urlopen", side_effect=_http_error(404)):
                result = self.store.download("toolchains/missing.tar.gz", dest)
            self.assertFalse(result)
            self.assertFalse(dest.exists())

    def test_download_no_tmp_left_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "archive.tar.gz"
            with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
                with self.assertRaises(OSError):
                    self.store.download("toolchains/x.tar.gz", dest)
            tmp_files = list(Path(tmp).glob("*.dl"))
            self.assertEqual(tmp_files, [])

    def test_download_url_composed_correctly(self):
        resp = _fake_response(200, b"data")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.tar.gz"
            with patch("urllib.request.urlopen", return_value=resp) as mock_open:
                self.store.download("toolchains/key.tar.gz", dest)
            req = mock_open.call_args[0][0]
            self.assertEqual(req.full_url, "http://cache.local:9000/toolchains/key.tar.gz")


# ---------------------------------------------------------------------------
# HttpStore — upload
# ---------------------------------------------------------------------------

class TestHttpStoreUpload(unittest.TestCase):

    def setUp(self):
        self.store = HttpStore("http://cache.local:9000", timeout=10)

    def test_upload_success(self):
        resp = _fake_response(200)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "archive.tar.gz"
            f.write_bytes(b"archive-content")
            with patch("urllib.request.urlopen", return_value=resp):
                result = self.store.upload("toolchains/arm64.tar.gz", f)
            self.assertTrue(result)

    def test_upload_skipped_when_file_missing(self):
        result = self.store.upload("key", Path("/nonexistent/file.tar.gz"))
        self.assertFalse(result)

    def test_upload_raises_on_http_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.tar.gz"
            f.write_bytes(b"data")
            with patch("urllib.request.urlopen", side_effect=_http_error(403)):
                with self.assertRaises(urllib.error.HTTPError):
                    self.store.upload("key", f)

    def test_upload_uses_put_method(self):
        resp = _fake_response(200)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.tar.gz"
            f.write_bytes(b"bytes")
            with patch("urllib.request.urlopen", return_value=resp) as mock_open:
                self.store.upload("toolchains/x.tar.gz", f)
            req = mock_open.call_args[0][0]
            self.assertEqual(req.get_method(), "PUT")

    def test_upload_auth_header(self):
        store = HttpStore("http://cache.local", token="secret-token", timeout=10)
        resp = _fake_response(200)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.tar.gz"
            f.write_bytes(b"bytes")
            with patch("urllib.request.urlopen", return_value=resp) as mock_open:
                store.upload("key", f)
            req = mock_open.call_args[0][0]
            self.assertEqual(req.get_header("Authorization"), "Bearer secret-token")


# ---------------------------------------------------------------------------
# HttpStore — not_local
# ---------------------------------------------------------------------------

class TestHttpStoreNotLocal(unittest.TestCase):

    def test_is_not_local(self):
        self.assertFalse(HttpStore("http://cache.local").is_local)

    def test_repr(self):
        s = repr(HttpStore("http://cache.local:9000"))
        self.assertIn("cache.local:9000", s)


# ---------------------------------------------------------------------------
# StoreFactory
# ---------------------------------------------------------------------------

class TestStoreFactory(unittest.TestCase):

    def test_empty_url_returns_local(self):
        store = StoreFactory.from_url("")
        self.assertIsInstance(store, LocalStore)

    def test_file_scheme_returns_local(self):
        store = StoreFactory.from_url("file:///tmp/cache")
        self.assertIsInstance(store, LocalStore)

    def test_http_url_returns_http_store(self):
        store = StoreFactory.from_url("http://cache.local:9000")
        self.assertIsInstance(store, HttpStore)
        self.assertEqual(store.base_url, "http://cache.local:9000")

    def test_https_url_returns_http_store(self):
        store = StoreFactory.from_url("https://cache.example.com/netos")
        self.assertIsInstance(store, HttpStore)

    def test_http_trailing_slash_stripped(self):
        store = StoreFactory.from_url("http://cache.local/")
        self.assertIsInstance(store, HttpStore)
        self.assertFalse(store.base_url.endswith("/"))

    def test_unknown_scheme_raises(self):
        with self.assertRaises(ValueError) as ctx:
            StoreFactory.from_url("ftp://old-server/cache")
        self.assertIn("ftp://", str(ctx.exception))

    def test_from_env_no_var_returns_local(self):
        with patch.dict("os.environ", {}, clear=True):
            store = StoreFactory.from_env()
        self.assertIsInstance(store, LocalStore)

    def test_from_env_http_var(self):
        env = {"NETOS_ARTIFACT_STORE": "http://build-cache.local:9000"}
        with patch.dict("os.environ", env):
            store = StoreFactory.from_env()
        self.assertIsInstance(store, HttpStore)

    def test_push_enabled_default_true(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(StoreFactory.push_enabled())

    def test_push_enabled_false_when_zero(self):
        with patch.dict("os.environ", {"NETOS_STORE_PUSH": "0"}):
            self.assertFalse(StoreFactory.push_enabled())

    def test_push_enabled_true_when_one(self):
        with patch.dict("os.environ", {"NETOS_STORE_PUSH": "1"}):
            self.assertTrue(StoreFactory.push_enabled())

    def test_http_token_from_env(self):
        env = {
            "NETOS_ARTIFACT_STORE": "http://cache.local",
            "NETOS_ARTIFACT_STORE_TOKEN": "mytoken",
        }
        with patch.dict("os.environ", env):
            store = StoreFactory.from_env()
        self.assertIsInstance(store, HttpStore)
        self.assertEqual(store.token, "mytoken")

    def test_timeout_from_env(self):
        env = {
            "NETOS_ARTIFACT_STORE": "http://cache.local",
            "NETOS_STORE_TIMEOUT": "60",
        }
        with patch.dict("os.environ", env):
            store = StoreFactory.from_env()
        self.assertIsInstance(store, HttpStore)
        self.assertEqual(store.timeout, 60)


# ---------------------------------------------------------------------------
# S3 URL parsing (no boto3 needed — just tests factory parsing)
# ---------------------------------------------------------------------------

class TestStoreFactoryS3Parsing(unittest.TestCase):

    def _make_s3_store(self, url: str):
        """Parse S3 url and return the S3Store (mocking boto3 import)."""
        from netos_build.store_s3 import S3Store
        # Just test the factory parses correctly — don't actually connect
        with patch.dict("os.environ", {}):
            store = StoreFactory._make_s3(url, timeout=30)
        return store

    def test_s3_bucket_parsed(self):
        from netos_build.store_s3 import S3Store
        store = self._make_s3_store("s3://my-bucket")
        self.assertIsInstance(store, S3Store)
        self.assertEqual(store.bucket, "my-bucket")
        self.assertEqual(store.prefix, "")

    def test_s3_bucket_and_prefix(self):
        store = self._make_s3_store("s3://my-bucket/netos/caches")
        self.assertEqual(store.bucket, "my-bucket")
        self.assertEqual(store.prefix, "netos/caches")

    def test_s3_key_with_prefix(self):
        from netos_build.store_s3 import S3Store
        store = S3Store(bucket="b", prefix="netos")
        self.assertEqual(store._s3_key("arm64.tar.gz"), "netos/arm64.tar.gz")

    def test_s3_key_without_prefix(self):
        from netos_build.store_s3 import S3Store
        store = S3Store(bucket="b")
        self.assertEqual(store._s3_key("arm64.tar.gz"), "arm64.tar.gz")

    def test_s3_endpoint_from_env(self):
        env = {
            "NETOS_STORE_S3_ENDPOINT_URL": "http://localhost:9000",
            "NETOS_STORE_S3_ACCESS_KEY": "key",
            "NETOS_STORE_S3_SECRET_KEY": "secret",
        }
        with patch.dict("os.environ", env):
            store = StoreFactory._make_s3("s3://bucket", timeout=30)
        self.assertEqual(store.endpoint_url, "http://localhost:9000")
        self.assertEqual(store.access_key, "key")

    def test_s3_repr(self):
        from netos_build.store_s3 import S3Store
        r = repr(S3Store(bucket="mybucket", prefix="netos"))
        self.assertIn("mybucket", r)
        self.assertIn("netos", r)


# ---------------------------------------------------------------------------
# CacheSync
# ---------------------------------------------------------------------------

class TestCacheSync(unittest.TestCase):

    def _local_sync(self) -> CacheSync:
        return CacheSync(LocalStore(), push_enabled=True)

    # pull

    def test_pull_returns_true_if_file_exists_locally(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "archive.tar.gz"
            f.write_bytes(b"data")
            sync = self._local_sync()
            self.assertTrue(sync.pull("key", f))

    def test_pull_returns_false_for_local_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            sync = self._local_sync()
            self.assertFalse(sync.pull("key", Path(tmp) / "missing.tar.gz"))

    def test_pull_downloads_from_remote(self):
        store = MagicMock(spec=HttpStore)
        store.is_local = False
        store.download = MagicMock(return_value=True)
        sync = CacheSync(store, push_enabled=True)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "archive.tar.gz"
            result = sync.pull("toolchains/arm64.tar.gz", dest)
        self.assertTrue(result)
        store.download.assert_called_once()

    def test_pull_returns_false_on_store_miss(self):
        store = MagicMock(spec=HttpStore)
        store.is_local = False
        store.download = MagicMock(return_value=False)
        sync = CacheSync(store, push_enabled=True)
        with tempfile.TemporaryDirectory() as tmp:
            result = sync.pull("key", Path(tmp) / "missing.tar.gz")
        self.assertFalse(result)

    def test_pull_non_fatal_on_exception(self):
        store = MagicMock(spec=HttpStore)
        store.is_local = False
        store.download = MagicMock(side_effect=OSError("network down"))
        sync = CacheSync(store, push_enabled=True)
        with tempfile.TemporaryDirectory() as tmp:
            result = sync.pull("key", Path(tmp) / "missing.tar.gz")
        self.assertFalse(result)  # must not raise

    # push

    def test_push_skipped_for_local_store(self):
        sync = self._local_sync()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.tar.gz"
            f.write_bytes(b"data")
            result = sync.push("key", f)
        self.assertFalse(result)

    def test_push_skipped_when_disabled(self):
        store = MagicMock(spec=HttpStore)
        store.is_local = False
        sync = CacheSync(store, push_enabled=False)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.tar.gz"
            f.write_bytes(b"data")
            sync.push("key", f)
        store.upload.assert_not_called()

    def test_push_skipped_when_remote_already_has_key(self):
        store = MagicMock(spec=HttpStore)
        store.is_local = False
        store.exists = MagicMock(return_value=True)
        sync = CacheSync(store, push_enabled=True)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.tar.gz"
            f.write_bytes(b"data")
            sync.push("key", f)
        store.upload.assert_not_called()

    def test_push_uploads_when_remote_missing(self):
        store = MagicMock(spec=HttpStore)
        store.is_local = False
        store.exists = MagicMock(return_value=False)
        store.upload = MagicMock(return_value=True)
        sync = CacheSync(store, push_enabled=True)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.tar.gz"
            f.write_bytes(b"data")
            sync.push("key.tar.gz", f)
        store.upload.assert_called_once()

    def test_push_skipped_when_file_missing(self):
        store = MagicMock(spec=HttpStore)
        store.is_local = False
        sync = CacheSync(store, push_enabled=True)
        result = sync.push("key", Path("/nonexistent/file.tar.gz"))
        self.assertFalse(result)
        store.upload.assert_not_called()

    def test_push_non_fatal_on_exception(self):
        store = MagicMock(spec=HttpStore)
        store.is_local = False
        store.exists = MagicMock(return_value=False)
        store.upload = MagicMock(side_effect=OSError("network error"))
        sync = CacheSync(store, push_enabled=True)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.tar.gz"
            f.write_bytes(b"data")
            result = sync.push("key", f)   # must not raise
        self.assertFalse(result)

    def test_active_true_for_remote_store(self):
        store = MagicMock(spec=HttpStore)
        store.is_local = False
        sync = CacheSync(store)
        self.assertTrue(sync.active)

    def test_active_false_for_local_store(self):
        self.assertFalse(self._local_sync().active)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
