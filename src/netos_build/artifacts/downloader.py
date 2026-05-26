"""Atomic, retry-capable HTTP downloader."""
from __future__ import annotations

import logging
import shutil
import time
import urllib.request
from pathlib import Path

_DEFAULT_TIMEOUT = 300   # seconds per attempt
_DEFAULT_RETRIES = 3
_RETRY_DELAYS    = (5, 15, 30)  # back-off between attempts
_USER_AGENT      = "netos-build/1.0"


class DownloadError(RuntimeError):
    """Raised when all download attempts have been exhausted."""


class SafeDownloader:
    """Downloads a URL to *destination* using an atomic .part temp file.

    Guarantees:
    - *destination* is either absent or fully written (no partial files left)
    - Network timeout is enforced per attempt
    - Retries with back-off on transient errors
    """

    def download(
        self,
        url: str,
        destination: Path,
        timeout: int  = _DEFAULT_TIMEOUT,
        retries: int  = _DEFAULT_RETRIES,
        user_agent: str = _USER_AGENT,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_suffix(destination.suffix + ".part")

        last_exc: BaseException | None = None
        for attempt in range(1, retries + 1):
            try:
                self._fetch(url, tmp, timeout, user_agent)
                tmp.rename(destination)
                logging.info("Downloaded %s -> %s", url, destination)
                return
            except Exception as exc:
                last_exc = exc
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
                if attempt < retries:
                    delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
                    logging.warning(
                        "Download attempt %d/%d failed: %s — retrying in %ds (%s)",
                        attempt, retries, exc, delay, url,
                    )
                    time.sleep(delay)
                else:
                    logging.error("Download failed after %d attempts: %s", retries, url)

        raise DownloadError(
            f"Failed to download {url} after {retries} attempts"
        ) from last_exc

    # ------------------------------------------------------------------
    def _fetch(self, url: str, tmp: Path, timeout: int, user_agent: str) -> None:
        logging.info("Fetching %s -> %s", url, tmp)
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
            shutil.copyfileobj(resp, out)
