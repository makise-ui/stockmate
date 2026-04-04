import json
import os
import shutil
import datetime
from pathlib import Path


class SafeJsonWriter:
    """Atomic JSON writer — writes to .tmp then replaces target."""

    @staticmethod
    def write(file_path, data):
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            tmp_path.replace(path)
            return True
        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"SafeJsonWriter failed for {path}: {e}") from e


def backup_excel_file(file_path):
    """Create a timestamped backup of an Excel file.

    Returns the backup path string on success, None on failure.
    """
    path = Path(file_path)
    if not path.exists():
        return None

    backup_dir = Path.home() / "Documents" / "StockMate" / "backups"
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{path.stem}_{ts}{path.suffix}.bak"
    backup_path = backup_dir / safe_name

    try:
        shutil.copy2(path, backup_path)
        rotate_backups(path.name, backup_dir, max_backups=5)
        return str(backup_path)
    except OSError:
        return None


def rotate_backups(file_name, backup_dir, max_backups=5):
    """Keep only the last N backups for a given file name."""
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return

    stem = Path(file_name).stem
    suffix = Path(file_name).suffix

    candidates = [
        p for p in backup_dir.glob(f"*{suffix}.bak") if p.name.startswith(stem + "_")
    ]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for old_file in candidates[max_backups:]:
        try:
            old_file.unlink()
        except OSError:
            pass
