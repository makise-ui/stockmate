"""
SQLite database module for StockMate.

Replaces JSON-based ID registry with a bulletproof SQLite backend.
Provides IMEI-aware deduplication, metadata tracking, and full audit history.
"""

import os
import re
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLACEHOLDER_IMEIS: set[str] = {
    "not on",
    "n/a",
    "na",
    "none",
    "nil",
    "unknown",
    "no imei",
    "noimei",
    "no",
    "test",
    "temp",
    "dummy",
    "missing",
    "not available",
    "not applicable",
    "-",
    "--",
    "---",
}

_IMEI_DIGIT_RE = re.compile(r"^\d{14,16}$")

_VALID_METADATA_FIELDS: set[str] = {
    "status",
    "buyer",
    "buyer_contact",
    "notes",
    "price_override",
    "sold_date",
    "is_hidden",
    "merged_into",
    "merge_reason",
}

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imei TEXT,
    imei_type TEXT NOT NULL DEFAULT 'unknown',
    model TEXT NOT NULL DEFAULT '',
    ram_rom TEXT NOT NULL DEFAULT '',
    supplier TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    price_original REAL DEFAULT 0.0,
    grade TEXT NOT NULL DEFAULT '',
    condition TEXT NOT NULL DEFAULT '',
    source_file TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS metadata (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'IN',
    buyer TEXT DEFAULT '',
    buyer_contact TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    price_override REAL DEFAULT NULL,
    sold_date TEXT DEFAULT NULL,
    added_date TEXT NOT NULL DEFAULT (datetime('now')),
    is_hidden INTEGER NOT NULL DEFAULT 0,
    merged_into INTEGER DEFAULT NULL,
    merge_reason TEXT DEFAULT '',
    FOREIGN KEY (id) REFERENCES items(id),
    FOREIGN KEY (merged_into) REFERENCES items(id)
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    details TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE INDEX IF NOT EXISTS idx_items_imei ON items(imei);
CREATE INDEX IF NOT EXISTS idx_items_type ON items(imei_type);
CREATE INDEX IF NOT EXISTS idx_metadata_status ON metadata(status);
CREATE INDEX IF NOT EXISTS idx_metadata_hidden ON metadata(is_hidden);
CREATE INDEX IF NOT EXISTS idx_history_item ON history(item_id);
"""


# ---------------------------------------------------------------------------
# Helper functions — pure, predictable, tested at the boundary
# ---------------------------------------------------------------------------


def is_valid_imei(imei_str: str) -> bool:
    """Return True when *imei_str* contains exactly 14-16 consecutive digits."""
    if not isinstance(imei_str, str):
        return False
    return bool(_IMEI_DIGIT_RE.match(imei_str.strip()))


def is_placeholder_imei(imei_str: str) -> bool:
    """Return True when *imei_str* is a known placeholder value."""
    if not isinstance(imei_str, str):
        return False
    return imei_str.strip().lower() in PLACEHOLDER_IMEIS


def _classify_imei(raw: str | None) -> str:
    """Classify an IMEI string into 'real', 'text', or 'placeholder'."""
    if raw is None:
        return "placeholder"

    stripped = raw.strip()

    if not stripped:
        return "placeholder"

    if is_valid_imei(stripped):
        return "real"

    if is_placeholder_imei(stripped):
        return "placeholder"

    return "text"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row into a plain dict."""
    return dict(row)


# ---------------------------------------------------------------------------
# SQLiteDatabase
# ---------------------------------------------------------------------------


class SQLiteDatabase:
    """Thread-safe SQLite database for StockMate.

    All write operations are serialised through an internal lock.
    Read operations use the shared connection directly.
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            db_path = str(Path.home() / "Documents" / "StockMate" / "stockmate.db")

        self._db_path = db_path
        self._lock = threading.Lock()

        # Ensure parent directories exist
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # WAL mode for better concurrent-read performance
        self._conn.execute("PRAGMA journal_mode=WAL")
        # Enforce foreign-key constraints
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._create_schema()

    # ---- private helpers ---------------------------------------------------

    def _create_schema(self) -> None:
        """Execute the full schema creation SQL (safe: IF NOT EXISTS)."""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    # ---- public API --------------------------------------------------------

    def get_or_create_id(
        self,
        imei: str | None,
        model: str,
        ram_rom: str,
        supplier: str,
        source_file: str,
        *,
        color: str = "",
        price_original: float = 0.0,
        grade: str = "",
        condition: str = "",
    ) -> int:
        """Return an existing ID for a *real* IMEI, or insert a new row.

        **Rules**
        - Real IMEI (14-16 digits): look up first; return existing or insert.
        - Text / placeholder IMEI: always insert, always new ID.
        """
        imei_type = _classify_imei(imei)
        clean_imei = imei.strip() if isinstance(imei, str) else None

        # Guard: real IMEIs may already exist — check first
        if imei_type == "real":
            existing = self._conn.execute(
                "SELECT id FROM items WHERE imei = ? AND imei_type = 'real'",
                (clean_imei,),
            ).fetchone()

            if existing is not None:
                return existing["id"]

        # For text/placeholder IMEIs, dedup by composite key
        if imei_type in ("text", "placeholder"):
            existing = self._conn.execute(
                "SELECT id FROM items WHERE imei = ? AND model = ? AND ram_rom = ? AND supplier = ? AND imei_type = ?",
                (clean_imei, model, ram_rom, supplier, imei_type),
            ).fetchone()

            if existing is not None:
                return existing["id"]

        # Insert path (all types reach here when no match or non-real)
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO items (imei, imei_type, model, ram_rom, supplier,
                                   color, price_original, grade, condition,
                                   source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_imei,
                    imei_type,
                    model,
                    ram_rom,
                    supplier,
                    color,
                    price_original,
                    grade,
                    condition,
                    source_file,
                ),
            )
            new_id = cursor.lastrowid

            # Create companion metadata row
            self._conn.execute(
                "INSERT INTO metadata (id) VALUES (?)",
                (new_id,),
            )
            self._conn.commit()

        return new_id

    def update_metadata(self, item_id: int, **kwargs: Any) -> None:
        """Update metadata fields for *item_id*.

        Only the fields passed in *kwargs* are touched.
        Unknown field names raise ``ValueError``.
        """
        unknown = set(kwargs) - _VALID_METADATA_FIELDS
        if unknown:
            raise ValueError(f"Invalid metadata fields: {', '.join(sorted(unknown))}")

        if not kwargs:
            return

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values())
        values.append(item_id)

        with self._lock:
            self._conn.execute(
                f"UPDATE metadata SET {set_clause} WHERE id = ?",
                values,
            )
            self._conn.commit()

    def add_history(self, item_id: int, action: str, details: str) -> None:
        """Append an immutable history entry."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO history (item_id, action, details) VALUES (?, ?, ?)",
                (item_id, action, details),
            )
            self._conn.commit()

    def get_metadata(self, item_id: int) -> dict[str, Any]:
        """Return metadata dict for *item_id*, or ``{}`` when not found."""
        row = self._conn.execute(
            "SELECT * FROM metadata WHERE id = ?", (item_id,)
        ).fetchone()

        if row is None:
            return {}
        return _row_to_dict(row)

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        """Return combined item + metadata dict, or ``None``."""
        row = self._conn.execute(
            """
            SELECT i.*, m.status, m.buyer, m.buyer_contact, m.notes,
                   m.price_override, m.sold_date, m.added_date,
                   m.is_hidden, m.merged_into, m.merge_reason
            FROM items i
            LEFT JOIN metadata m ON m.id = i.id
            WHERE i.id = ?
            """,
            (item_id,),
        ).fetchone()

        if row is None:
            return None
        return _row_to_dict(row)

    def get_all_items(
        self,
        *,
        status_filter: str | None = None,
        hidden: bool = False,
    ) -> list[dict[str, Any]]:
        """Return all items, optionally filtered by status and hidden flag."""
        query = """
            SELECT i.*, m.status, m.buyer, m.buyer_contact, m.notes,
                   m.price_override, m.sold_date, m.added_date,
                   m.is_hidden, m.merged_into, m.merge_reason
            FROM items i
            LEFT JOIN metadata m ON m.id = i.id
            WHERE 1=1
        """
        params: list[Any] = []

        if status_filter is not None:
            query += " AND m.status = ?"
            params.append(status_filter)

        if not hidden:
            query += " AND (m.is_hidden = 0 OR m.is_hidden IS NULL)"

        query += " ORDER BY i.id"

        rows = self._conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_items_by_ids(self, ids: list[int]) -> list[dict[str, Any]]:
        """Bulk lookup — return items whose id is in *ids*."""
        if not ids:
            return []

        placeholders = ", ".join("?" for _ in ids)
        query = f"""
            SELECT i.*, m.status, m.buyer, m.buyer_contact, m.notes,
                   m.price_override, m.sold_date, m.added_date,
                   m.is_hidden, m.merged_into, m.merge_reason
            FROM items i
            LEFT JOIN metadata m ON m.id = i.id
            WHERE i.id IN ({placeholders})
            ORDER BY i.id
        """
        rows = self._conn.execute(query, ids).fetchall()
        return [_row_to_dict(r) for r in rows]

    def resolve_conflict(
        self,
        keep_id: int,
        hide_ids: list[int],
        reason: str = "",
    ) -> None:
        """Mark *hide_ids* as hidden and merged into *keep_id*.

        Each hidden item receives a history entry.
        """
        if not hide_ids:
            return

        with self._lock:
            placeholders = ", ".join("?" for _ in hide_ids)
            values = [keep_id] + hide_ids

            self._conn.execute(
                f"""
                UPDATE metadata
                SET is_hidden = 1,
                    merged_into = ?
                WHERE id IN ({placeholders})
                """,
                values,
            )

            # Add history entries for every hidden item
            now = datetime.utcnow().isoformat()
            for hid in hide_ids:
                self._conn.execute(
                    "INSERT INTO history (item_id, action, details, timestamp) "
                    "VALUES (?, 'resolved_conflict', ?, ?)",
                    (
                        hid,
                        f"Merged into item {keep_id}. Reason: {reason}",
                        now,
                    ),
                )
            self._conn.commit()

    def get_conflicts(self) -> list[dict[str, Any]]:
        """Return groups of items that share the same real IMEI.

        Each dict has keys ``imei`` and ``items`` (list of item dicts).
        """
        # Find real IMEIs that appear more than once
        duplicate_imeis = self._conn.execute(
            """
            SELECT imei
            FROM items
            WHERE imei_type = 'real' AND imei IS NOT NULL
            GROUP BY imei
            HAVING COUNT(*) > 1
            """
        ).fetchall()

        results: list[dict[str, Any]] = []
        for row in duplicate_imeis:
            imei_value = row["imei"]
            items = self._conn.execute(
                """
                SELECT i.*, m.status, m.buyer, m.buyer_contact, m.notes,
                       m.price_override, m.sold_date, m.added_date,
                       m.is_hidden, m.merged_into, m.merge_reason
                FROM items i
                LEFT JOIN metadata m ON m.id = i.id
                WHERE i.imei = ?
                ORDER BY i.id
                """,
                (imei_value,),
            ).fetchall()

            results.append(
                {
                    "imei": imei_value,
                    "items": [_row_to_dict(it) for it in items],
                }
            )

        return results

    def backup_db(self, backup_dir: str) -> str | None:
        """Create a timestamped backup using SQLite's online backup API.

        Returns the path to the backup file, or ``None`` on failure.
        """
        try:
            Path(backup_dir).mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = str(Path(backup_dir) / f"mobile_shop_backup_{timestamp}.db")

            # Online backup via a second connection
            source_conn = sqlite3.connect(self._db_path)
            dest_conn = sqlite3.connect(backup_path)

            with dest_conn:
                source_conn.backup(dest_conn)

            dest_conn.close()
            source_conn.close()

            return backup_path

        except Exception:
            return None

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]
