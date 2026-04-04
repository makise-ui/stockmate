"""
File system watcher module for StockMate.

Monitors mapped inventory files for changes using the ``watchdog`` library
and triggers automatic reloads via a debounced callback.
"""

import os
import threading
from collections import defaultdict
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import ConfigManager
from .inventory import InventoryManager

# File extensions that trigger a reload
_WATCHED_EXTENSIONS: frozenset[str] = frozenset({".xlsx", ".xls"})


def _is_watched_file(path: str) -> bool:
    """Return True when *path* has a watched extension."""
    return Path(path).suffix.lower() in _WATCHED_EXTENSIONS


def _get_parent_directory(path: str) -> str:
    """Return the absolute parent directory of *path*."""
    return str(Path(path).resolve().parent)


# ---------------------------------------------------------------------------
# FileChangeHandler — debounced event handler
# ---------------------------------------------------------------------------


class FileChangeHandler(FileSystemEventHandler):
    """Debounced file-system event handler for Excel inventory files.

    Cancels any pending callback timer on each new event and schedules a
    fresh one, ensuring the callback fires only once after a quiet period.
    """

    def __init__(
        self,
        callback: Callable[[], None],
        debounce_seconds: float = 1.0,
    ) -> None:
        super().__init__()
        self._callback = callback
        self._debounce_seconds = debounce_seconds
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    # -- event dispatch --------------------------------------------------

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if not _is_watched_file(event.src_path):
            return
        self._schedule_callback()

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if not _is_watched_file(event.src_path):
            return
        self._schedule_callback()

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # Check both source and destination paths
        if not _is_watched_file(event.src_path) and not _is_watched_file(
            getattr(event, "dest_path", "")
        ):
            return
        self._schedule_callback()

    # -- debouncing ------------------------------------------------------

    def _schedule_callback(self) -> None:
        """Cancel any pending timer and schedule a fresh callback."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_seconds, self._callback)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self) -> None:
        """Cancel any pending callback timer."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


# ---------------------------------------------------------------------------
# InventoryWatcher — directory observer manager
# ---------------------------------------------------------------------------


class InventoryWatcher:
    """Watch all directories containing mapped inventory files.

    On any relevant file change, triggers a full inventory reload through
    the ``InventoryManager``.
    """

    def __init__(
        self,
        inventory_manager: InventoryManager,
        config_manager: ConfigManager,
    ) -> None:
        self._inventory = inventory_manager
        self._config = config_manager
        self._observer: Observer | None = None
        self._handler: FileChangeHandler | None = None

    def start(self) -> None:
        """Create an observer and watch every unique directory that holds
        mapped inventory files."""
        directories = self._collect_watched_directories()

        if not directories:
            return

        self._handler = FileChangeHandler(callback=self._on_change)
        self._observer = Observer()

        for directory in directories:
            if os.path.isdir(directory):
                self._observer.schedule(self._handler, directory, recursive=False)

        self._observer.start()

    def stop(self) -> None:
        """Stop the observer and cancel any pending callbacks."""
        if self._handler is not None:
            self._handler.cancel()

        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

        self._handler = None

    # -- private helpers -------------------------------------------------

    def _collect_watched_directories(self) -> list[str]:
        """Return a deduplicated list of parent directories for all mapped files."""
        directories: set[str] = set()

        for key, mapping in self._config.mappings.items():
            file_path = mapping.get("file_path", key)

            # Composite key fallback: "path::sheet" → "path"
            if "::" in key and not os.path.exists(key):
                parts = key.split("::")
                if os.path.exists(parts[0]):
                    file_path = parts[0]

            if os.path.exists(file_path) and _is_watched_file(file_path):
                directories.add(_get_parent_directory(file_path))

        return sorted(directories)

    def _on_change(self) -> None:
        """Reload all inventory data when a watched file changes."""
        self._inventory.reload_all()
