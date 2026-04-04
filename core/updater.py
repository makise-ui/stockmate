"""Auto-updater — check GitHub releases, download, and install updates."""

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import requests
from packaging.version import Version

from .version import APP_VERSION, REPO_NAME, REPO_OWNER

logger = logging.getLogger(__name__)

_GITHUB_API_URL = (
    f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
)
_REQUEST_TIMEOUT = 10
_CHUNK_SIZE = 8192

# Windows-specific creation flag for detached process
try:
    import win32process

    DETACHED_PROCESS = win32process.CREATE_NO_WINDOW  # type: ignore[attr-defined]
except ImportError:
    DETACHED_PROCESS = 0x08000000  # fallback constant


class UpdateChecker:
    """Check for and download application updates from GitHub Releases."""

    def __init__(self, current_version: str = APP_VERSION) -> None:
        self._current_version = Version(current_version)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": f"stockmate/{current_version}",
            }
        )

    # -- public API ----------------------------------------------------------

    def check_for_updates(self) -> Optional[dict[str, str]]:
        """Return update metadata dict or None when up-to-date / on error.

        Returns dict with keys: version, download_url, release_notes,
        asset_name, sha256, variant — or None.
        """
        release = self._fetch_latest_release()
        if release is None:
            return None

        latest_version = self._parse_release_version(release)
        if latest_version is None:
            return None

        if latest_version <= self._current_version:
            return None

        asset_info = self._select_download_asset(release)
        if asset_info is None:
            return None

        download_url, asset_name, sha256_hash = asset_info
        variant = self._detect_variant(asset_name)

        return {
            "version": str(latest_version),
            "download_url": download_url,
            "release_notes": release.get("body", ""),
            "asset_name": asset_name,
            "sha256": sha256_hash,
            "variant": variant,
        }

    def download_update(
        self, download_url: str, target_path: str, expected_sha256: str = ""
    ) -> bool:
        """Download update to *target_path* with optional SHA-256 verification.

        Streams to a temp file, verifies hash, then moves into place.
        Returns True on success, False on any failure.
        """
        if not download_url:
            logger.error("download_update called with empty URL")
            return False

        temp_fd, temp_path = tempfile.mkstemp(suffix=".tmp", prefix="msm_update_")
        os.close(temp_fd)

        try:
            if not self._stream_download(download_url, temp_path):
                return False

            if expected_sha256:
                if not self._verify_sha256(temp_path, expected_sha256):
                    logger.error("SHA-256 mismatch — update rejected")
                    return False

            shutil.move(temp_path, target_path)
            return True
        except Exception as exc:
            logger.error("download_update failed: %s", exc)
            return False
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def restart_and_install(self, exe_path: str, temp_path: str) -> bool:
        """Replace the running EXE with *temp_path* and relaunch.

        Writes a detached batch script that waits, copies, then launches.
        Returns True when the batch process was started successfully.
        """
        if not self._paths_are_valid(exe_path, temp_path):
            return False

        batch_path = self._write_install_script(exe_path, temp_path)
        if batch_path is None:
            return False

        if not self._run_detached(batch_path):
            return False

        sys.exit(0)

    # -- internal helpers ----------------------------------------------------

    def _fetch_latest_release(self) -> Optional[dict]:
        """Fetch the latest GitHub release JSON or return None."""
        try:
            resp = self._session.get(_GITHUB_API_URL, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.debug("Network error fetching releases: %s", exc)
            return None

        if resp.status_code == 403:
            logger.warning("GitHub API rate-limited — skipping update check")
            return None

        if resp.status_code != 200:
            logger.debug("GitHub API returned %d", resp.status_code)
            return None

        try:
            return resp.json()
        except ValueError:
            logger.debug("Invalid JSON from GitHub API")
            return None

    @staticmethod
    def _parse_release_version(release: dict) -> Optional[Version]:
        """Extract and parse the version tag from a release dict."""
        tag = release.get("tag_name", "").lstrip("v")
        if not tag:
            return None
        try:
            return Version(tag)
        except ValueError:
            return None

    def _select_download_asset(self, release: dict) -> Optional[tuple[str, str, str]]:
        """Return (download_url, asset_name, sha256) for the best asset.

        Prefers .exe assets on Windows.  SHA-256 may come from a sidecar
        file or the release body; defaults to empty string.
        """
        assets = release.get("assets", [])
        if not assets:
            return None

        for asset in assets:
            name = asset.get("name", "")
            if name.endswith(".exe"):
                return (
                    asset.get("browser_download_url", ""),
                    name,
                    self._find_sha256(release, name),
                )

        # Fall back to first asset
        first = assets[0]
        return (
            first.get("browser_download_url", ""),
            first.get("name", ""),
            "",
        )

    @staticmethod
    def _find_sha256(release: dict, asset_name: str) -> str:
        """Look for a SHA-256 hash matching *asset_name* in release assets."""
        expected_hash_file = f"{asset_name}.sha256"
        for asset in release.get("assets", []):
            if asset.get("name") == expected_hash_file:
                return asset.get("browser_download_url", "")
        return ""

    @staticmethod
    def _detect_variant(asset_name: str) -> str:
        """Return 'licensed' or 'free' based on the asset filename."""
        lower = asset_name.lower()
        if "licensed" in lower or "pro" in lower:
            return "licensed"
        return "free"

    def _stream_download(self, url: str, dest_path: str) -> bool:
        """Stream-download *url* to *dest_path*. Returns True on success."""
        try:
            with self._session.get(url, stream=True, timeout=_REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                        f.write(chunk)
            return True
        except Exception as exc:
            logger.error("Stream download failed: %s", exc)
            return False

    @staticmethod
    def _verify_sha256(file_path: str, expected_hash: str) -> bool:
        """Verify SHA-256 of *file_path* against *expected_hash*."""
        if not expected_hash:
            return True

        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
                    sha256.update(chunk)
        except OSError as exc:
            logger.error("Cannot read file for hash verification: %s", exc)
            return False

        actual = sha256.hexdigest()
        return actual == expected_hash

    @staticmethod
    def _paths_are_valid(exe_path: str, temp_path: str) -> bool:
        """Validate that both paths exist and point to files."""
        if not exe_path or not temp_path:
            logger.error("restart_and_install: empty path provided")
            return False
        if not Path(temp_path).is_file():
            logger.error("restart_and_install: temp file does not exist: %s", temp_path)
            return False
        return True

    @staticmethod
    def _write_install_script(exe_path: str, temp_path: str) -> Optional[str]:
        """Write a batch script that copies *temp_path* over *exe_path* and launches it."""
        batch_dir = Path(tempfile.gettempdir())
        batch_path = batch_dir / "msm_installer.bat"

        exe_dir = Path(exe_path).parent
        exe_name = Path(exe_path).name

        script_lines = [
            "@echo off",
            "timeout /t 2 /nobreak >nul",
            f'copy /y "{temp_path}" "{exe_path}"',
            f'cd /d "{exe_dir}"',
            f'start "" "{exe_name}"',
            f'del /f /q "{batch_path}"',
        ]

        try:
            batch_path.write_text("\r\n".join(script_lines), encoding="utf-8")
            return str(batch_path)
        except OSError as exc:
            logger.error("Failed to write install script: %s", exc)
            return None

    @staticmethod
    def _run_detached(batch_path: str) -> bool:
        """Execute *batch_path* as a detached process."""
        try:
            subprocess.Popen(
                [batch_path],
                creationflags=DETACHED_PROCESS,
                shell=True,
            )
            return True
        except Exception as exc:
            logger.error("Failed to launch install script: %s", exc)
            return False
