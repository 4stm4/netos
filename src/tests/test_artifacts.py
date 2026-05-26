"""Unit tests for src/netos_build/artifacts/

Run from repo root:
    python -m pytest src/tests/test_artifacts.py -v
or:
    python src/tests/test_artifacts.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure src/ is in sys.path when running directly
_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from netos_build.artifacts.verifier import sha256_file, verify
from netos_build.artifacts.downloader import SafeDownloader, DownloadError
from netos_build.artifacts.cache import DownloadCache
from netos_build.artifacts.sources import ArtifactSource
from netos_build.artifacts.manifest import ArtifactManifest
from netos_build.artifacts.manager import ArtifactManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------

class TestVerifier(unittest.TestCase):

    def test_sha256_file_correct(self):
        data = b"hello netos"
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            path = Path(f.name)
        try:
            self.assertEqual(sha256_file(path), _sha256(data))
        finally:
            path.unlink(missing_ok=True)

    def test_verify_true(self):
        data = b"buildroot"
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            path = Path(f.name)
        try:
            self.assertTrue(verify(path, _sha256(data)))
        finally:
            path.unlink(missing_ok=True)

    def test_verify_false_on_mismatch(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"corrupt")
            path = Path(f.name)
        try:
            self.assertFalse(verify(path, _sha256(b"correct")))
        finally:
            path.unlink(missing_ok=True)

    def test_verify_case_insensitive(self):
        data = b"test"
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            path = Path(f.name)
        try:
            self.assertTrue(verify(path, _sha256(data).upper()))
        finally:
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# SafeDownloader
# ---------------------------------------------------------------------------

class TestSafeDownloader(unittest.TestCase):

    def test_download_success(self):
        """File is written atomically via .part → rename."""
        content = b"fake-archive-content"
        dl = SafeDownloader()

        def fake_urlopen(req, timeout):
            resp = MagicMock()
            resp.__enter__ = lambda s: s
            resp.__exit__  = MagicMock(return_value=False)
            resp.read = MagicMock(side_effect=[content, b""])
            return resp

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "file.tar.xz"
            with patch("netos_build.artifacts.downloader.urllib.request.urlopen", fake_urlopen):
                dl.download("http://example.com/file.tar.xz", dest, timeout=10, retries=1)
            self.assertTrue(dest.exists())
            # .part file must not remain
            self.assertFalse(dest.with_suffix(".xz.part").exists())

    def test_no_partial_file_on_failure(self):
        """On network error, .part file is cleaned up."""
        dl = SafeDownloader()

        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "file.tar.xz"
            with patch("netos_build.artifacts.downloader.urllib.request.urlopen", fake_urlopen):
                with self.assertRaises(DownloadError):
                    dl.download("http://example.com/file.tar.xz", dest, timeout=1, retries=1)
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_suffix(".xz.part").exists())

    def test_retry_succeeds_on_second_attempt(self):
        """Downloader retries and succeeds on the second attempt."""
        content = b"data"
        attempts = {"n": 0}

        def fake_urlopen(req, timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise urllib.error.URLError("temporary failure")
            resp = MagicMock()
            resp.__enter__ = lambda s: s
            resp.__exit__  = MagicMock(return_value=False)
            resp.read = MagicMock(side_effect=[content, b""])
            return resp

        dl = SafeDownloader()
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "file.tar.xz"
            with patch("netos_build.artifacts.downloader.urllib.request.urlopen", fake_urlopen):
                with patch("netos_build.artifacts.downloader.time.sleep"):  # skip delays
                    dl.download("http://example.com/file.tar.xz", dest, timeout=10, retries=2)
            self.assertTrue(dest.exists())
            self.assertEqual(attempts["n"], 2)


# ---------------------------------------------------------------------------
# DownloadCache
# ---------------------------------------------------------------------------

class TestDownloadCache(unittest.TestCase):

    def _make_cache(self, tmp: str) -> DownloadCache:
        return DownloadCache(Path(tmp) / "cache")

    def _populate(self, cache: DownloadCache, filename: str, data: bytes) -> Path:
        """Put a file directly into the cache dir (simulating a previous download)."""
        path = cache.cache_dir / filename
        _write(path, data)
        cache._update_index(filename, "http://example.com/" + filename, _sha256(data), len(data))
        return path

    def test_cache_hit_with_correct_sha256(self):
        data = b"buildroot-tarball"
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._make_cache(tmp)
            self._populate(cache, "buildroot.tar.xz", data)
            result = cache.get(
                url="http://example.com/buildroot.tar.xz",
                filename="buildroot.tar.xz",
                sha256=_sha256(data),
            )
            self.assertEqual(result, cache.cache_dir / "buildroot.tar.xz")

    def test_cache_miss_on_sha256_mismatch_triggers_redownload(self):
        """Corrupt cached file is deleted; fresh download is performed."""
        good_data    = b"correct content"
        corrupt_data = b"bit-rot happened"
        download_called = {"n": 0}

        def fake_urlopen(req, timeout):
            download_called["n"] += 1
            resp = MagicMock()
            resp.__enter__ = lambda s: s
            resp.__exit__  = MagicMock(return_value=False)
            resp.read = MagicMock(side_effect=[good_data, b""])
            return resp

        with tempfile.TemporaryDirectory() as tmp:
            cache = self._make_cache(tmp)
            # Seed cache with corrupt file
            self._populate(cache, "buildroot.tar.xz", corrupt_data)

            with patch("netos_build.artifacts.downloader.urllib.request.urlopen", fake_urlopen):
                with patch("netos_build.artifacts.downloader.time.sleep"):
                    result = cache.get(
                        url="http://example.com/buildroot.tar.xz",
                        filename="buildroot.tar.xz",
                        sha256=_sha256(good_data),
                    )
            self.assertEqual(download_called["n"], 1)
            self.assertEqual(result.read_bytes(), good_data)

    def test_no_sha256_uses_file_if_present(self):
        data = b"kernel-archive"
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._make_cache(tmp)
            self._populate(cache, "linux-6.12.27.tar.xz", data)
            result = cache.get(
                url="http://example.com/linux-6.12.27.tar.xz",
                filename="linux-6.12.27.tar.xz",
                sha256=None,
            )
            self.assertEqual(result.read_bytes(), data)

    def test_index_json_updated_after_download(self):
        data = b"ovs-tarball"
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._make_cache(tmp)

            def fake_urlopen(req, timeout):
                resp = MagicMock()
                resp.__enter__ = lambda s: s
                resp.__exit__  = MagicMock(return_value=False)
                resp.read = MagicMock(side_effect=[data, b""])
                return resp

            with patch("netos_build.artifacts.downloader.urllib.request.urlopen", fake_urlopen):
                cache.get(
                    url="http://example.com/ovs.tar.gz",
                    filename="ovs.tar.gz",
                    sha256=_sha256(data),
                )

            index = json.loads((cache.cache_dir / "index.json").read_text())
            self.assertIn("ovs.tar.gz", index)
            self.assertEqual(index["ovs.tar.gz"]["sha256"], _sha256(data))

    def test_index_entry_removed_on_hash_mismatch(self):
        corrupt = b"bad"
        good    = b"good-content"
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._make_cache(tmp)
            self._populate(cache, "file.tar.gz", corrupt)

            def fake_urlopen(req, timeout):
                resp = MagicMock()
                resp.__enter__ = lambda s: s
                resp.__exit__  = MagicMock(return_value=False)
                resp.read = MagicMock(side_effect=[good, b""])
                return resp

            with patch("netos_build.artifacts.downloader.urllib.request.urlopen", fake_urlopen):
                with patch("netos_build.artifacts.downloader.time.sleep"):
                    cache.get(
                        url="http://example.com/file.tar.gz",
                        filename="file.tar.gz",
                        sha256=_sha256(good),
                    )
            index = json.loads((cache.cache_dir / "index.json").read_text())
            # After replacement, the entry should reflect the new good file
            self.assertEqual(index["file.tar.gz"]["sha256"], _sha256(good))


# ---------------------------------------------------------------------------
# ArtifactSource / ArtifactManifest
# ---------------------------------------------------------------------------

class TestArtifactSource(unittest.TestCase):

    def test_url_source_valid(self):
        s = ArtifactSource(type="url", uri="https://example.com/file.tar.xz", sha256="abc")
        self.assertEqual(s.type, "url")

    def test_invalid_type_raises(self):
        with self.assertRaises(ValueError):
            ArtifactSource(type="buildroot", uri="https://example.com")  # not a valid source type

    def test_local_source(self):
        s = ArtifactSource(type="local", uri="/tmp/myfile.tar")
        self.assertEqual(s.type, "local")


class TestArtifactManifest(unittest.TestCase):

    def test_valid_manifest(self):
        from netos_build.artifacts.sources import ArtifactSource
        m = ArtifactManifest(
            name="buildroot",
            version="2026.02.1",
            arch="any",
            format="source-archive",
            sha256="abc123",
        )
        self.assertEqual(m.format, "source-archive")

    def test_invalid_format_raises(self):
        with self.assertRaises(ValueError):
            ArtifactManifest(
                name="buildroot", version="1.0", arch="any",
                format="unknown-format", sha256="abc",
            )


# ---------------------------------------------------------------------------
# ArtifactManager
# ---------------------------------------------------------------------------

class TestArtifactManager(unittest.TestCase):

    def test_fetch_delegates_to_cache(self):
        data = b"artifact-data"
        with tempfile.TemporaryDirectory() as tmp:
            mgr   = ArtifactManager(Path(tmp))
            cache = mgr._cache
            # Pre-seed the cache
            path  = cache.cache_dir / "file.tar.xz"
            _write(path, data)
            cache._update_index("file.tar.xz", "http://example.com/file.tar.xz", _sha256(data), len(data))

            result = mgr.fetch(
                url="http://example.com/file.tar.xz",
                sha256=_sha256(data),
                filename="file.tar.xz",
            )
            self.assertEqual(result, path)

    def test_fetch_source_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_file = Path(tmp) / "myfile.tar"
            local_file.write_bytes(b"local-data")
            mgr = ArtifactManager(Path(tmp) / "build_cache")
            src = ArtifactSource(type="local", uri=str(local_file))
            result = mgr.fetch_source(src)
            self.assertEqual(result, local_file)

    def test_fetch_source_missing_local_raises(self):
        mgr = ArtifactManager(Path("/tmp"))
        src = ArtifactSource(type="local", uri="/nonexistent/path.tar")
        with self.assertRaises(FileNotFoundError):
            mgr.fetch_source(src)

    def test_fetch_source_git_not_implemented(self):
        mgr = ArtifactManager(Path("/tmp"))
        src = ArtifactSource(type="git", uri="https://github.com/example/repo.git")
        with self.assertRaises(NotImplementedError):
            mgr.fetch_source(src)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
