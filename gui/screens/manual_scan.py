"""Manual scan session screen for barcode/ID-based inventory audits.

Provides the ``ManualScanScreen`` class which manages a scanning session,
allowing users to look up items by ID/IMEI, track session statistics,
and export results.
"""

from __future__ import annotations

import datetime
import os
import tkinter as tk
from tkinter import filedialog
from tkinter import ttk
from typing import Any

import pandas as pd
import ttkbootstrap as tb
from ttkbootstrap.dialogs import Messagebox

from core.constants import FIELD_IMEI, FIELD_MODEL, FIELD_PRICE, FIELD_UNIQUE_ID
from core.reporting import ReportGenerator
from gui.base import BaseScreen


# ---------------------------------------------------------------------------
# ManualReportSession
# ---------------------------------------------------------------------------


class ManualReportSession:
    """In-memory session for manual scan reports.

    Tracks scanned items, timestamps, and provides export-ready data.
    """

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []
        self._started_at: datetime.datetime = datetime.datetime.now()
        self._last_modified: datetime.datetime = self._started_at

    @property
    def items(self) -> list[dict[str, Any]]:
        """Return a copy of the scanned items list."""
        return list(self._items)

    @property
    def item_count(self) -> int:
        """Return the number of items in the session."""
        return len(self._items)

    @property
    def total_value(self) -> float:
        """Return the sum of prices for all scanned items."""
        return sum(item.get(FIELD_PRICE, 0) for item in self._items)

    @property
    def started_at(self) -> datetime.datetime:
        """Return the session start timestamp."""
        return self._started_at

    def add_item(self, item: dict[str, Any]) -> None:
        """Add an item to the session.

        Args:
            item: Item dict from inventory lookup.
        """
        entry = dict(item)
        entry["scanned_at"] = datetime.datetime.now().isoformat()
        self._items.append(entry)
        self._last_modified = datetime.datetime.now()

    def remove_item(self, index: int) -> dict[str, Any] | None:
        """Remove an item by its session index.

        Args:
            index: Zero-based index in the session list.

        Returns:
            The removed item dict, or None if index is out of range.
        """
        if index < 0 or index >= len(self._items):
            return None
        removed = self._items.pop(index)
        self._last_modified = datetime.datetime.now()
        return removed

    def clear(self) -> None:
        """Remove all items from the session."""
        self._items.clear()
        self._last_modified = datetime.datetime.now()

    def to_dataframe(self) -> pd.DataFrame:
        """Return session items as a DataFrame for export."""
        if not self._items:
            return pd.DataFrame()
        return pd.DataFrame(self._items)


# ---------------------------------------------------------------------------
# ManualScanScreen
# ---------------------------------------------------------------------------

_DEFAULT_COLUMNS = [
    "unique_id",
    "imei",
    "model",
    "price",
    "status",
    "scanned_at",
]


class ManualScanScreen(BaseScreen):
    """Manual barcode scanning session screen."""

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)
        self._session = ManualReportSession()
        self._scan_var = tk.StringVar()
        self._count_var = tk.StringVar(value="Items: 0")
        self._value_var = tk.StringVar(value="Total Value: ₹0")
        self._tree: ttk.Treeview | None = None
        self._display_columns: list[str] = list(_DEFAULT_COLUMNS)

        self._build_ui()

    # -- layout --------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the manual scan interface."""
        self.add_header("Manual Scan Report")

        # Scan bar
        scan_frame = ttk.Frame(self)
        scan_frame.pack(fill=tk.X, padx=12, pady=(4, 8))

        ttk.Label(scan_frame, text="Scan / Enter ID or IMEI:").pack(
            side=tk.LEFT, padx=(0, 4)
        )
        self._scan_entry = ttk.Entry(
            scan_frame, textvariable=self._scan_var, width=40, font=("Consolas", 11)
        )
        self._scan_entry.pack(side=tk.LEFT, padx=4)
        self._scan_entry.bind("<Return>", self._on_scan)

        ttk.Button(
            scan_frame,
            text="Add",
            bootstyle="success",
            command=self._on_scan,
        ).pack(side=tk.LEFT, padx=4)

        # Session stats
        stats_frame = ttk.Frame(self)
        stats_frame.pack(fill=tk.X, padx=12, pady=(0, 8))

        ttk.Label(
            stats_frame,
            textvariable=self._count_var,
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 24))

        ttk.Label(
            stats_frame,
            textvariable=self._value_var,
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 24))

        # Column selection
        col_frame = ttk.Frame(self)
        col_frame.pack(fill=tk.X, padx=12, pady=(0, 4))

        ttk.Label(col_frame, text="Columns:").pack(side=tk.LEFT)
        col_btn = ttk.Menubutton(
            col_frame, text="Select Columns ▼", bootstyle="info-outline"
        )
        col_menu = tk.Menu(col_btn, tearoff=False)
        for col in _DEFAULT_COLUMNS:
            var = tk.BooleanVar(value=True)
            col_menu.add_checkbutton(label=col.replace("_", " ").title(), variable=var)
            var.trace_add("write", lambda *_: self._refresh_columns())
        col_btn.configure(menu=col_menu)
        col_btn.pack(side=tk.LEFT, padx=8)

        # Treeview
        tree_frame = ttk.LabelFrame(self, text="Scanned Items", padding=4)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

        self._tree = ttk.Treeview(tree_frame, show="headings", selectmode="extended")
        scrollbar_y = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self._tree.yview
        )
        scrollbar_x = ttk.Scrollbar(
            tree_frame, orient=tk.HORIZONTAL, command=self._tree.xview
        )
        self._tree.configure(
            yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set
        )

        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)

        self._build_tree_columns()

        # Action buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=(0, 8))

        ttk.Button(
            btn_frame,
            text="Delete Selected",
            bootstyle="danger",
            command=self._delete_selected,
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            btn_frame,
            text="Clear Session",
            bootstyle="warning",
            command=self._clear_session,
        ).pack(side=tk.LEFT, padx=4)

        export_menu = tk.Menu(btn_frame, tearoff=False)
        export_menu.add_command(
            label="Export to Excel", command=lambda: self._export("excel")
        )
        export_menu.add_command(
            label="Export to PDF", command=lambda: self._export("pdf")
        )

        export_btn = ttk.Menubutton(btn_frame, text="Export ▼", bootstyle="success")
        export_btn.configure(menu=export_menu)
        export_btn.pack(side=tk.RIGHT, padx=4)

    def _build_tree_columns(self) -> None:
        """Build treeview columns from the display column list."""
        if self._tree is None:
            return

        self._tree["columns"] = self._display_columns
        for col in self._display_columns:
            header = col.replace("_", " ").title()
            self._tree.heading(col, text=header)
            width = 150 if col != "unique_id" else 80
            self._tree.column(col, width=width, minwidth=50)

    def _refresh_columns(self) -> None:
        """Rebuild treeview columns (placeholder — full implementation would
        track checkbox variables). For now, keep defaults."""

    # -- scan operations -----------------------------------------------------

    def _on_scan(self, event: tk.Event | None = None) -> None:
        """Handle scan entry: lookup item and add to session."""
        raw = self._scan_var.get().strip()
        if not raw:
            return

        self._scan_var.set("")

        item = self._lookup_item(raw)
        if item is None:
            self.app["app"].show_toast(
                "Not Found", f"No item found for '{raw}'.", "warning"
            )
            return

        self._add_to_session(item)

    def _lookup_item(self, query: str) -> dict[str, Any] | None:
        """Look up an item by unique_id or IMEI.

        Args:
            query: The scanned barcode / ID / IMEI string.

        Returns:
            Item dict if found, None otherwise.
        """
        inventory = self.app.get("inventory")
        if inventory is None:
            return None

        # Try as unique_id first
        try:
            item_id = int(query)
            item, _redirected = inventory.get_item_by_id(item_id)
            if item is not None:
                return item
        except (ValueError, TypeError):
            pass

        # Try as IMEI
        df = getattr(inventory, "inventory_df", pd.DataFrame())
        if df.empty:
            return None

        mask = df[FIELD_IMEI].astype(str).str.contains(query, na=False, case=False)
        matches = df[mask]
        if matches.empty:
            return None

        # Return first match
        return matches.iloc[0].to_dict()

    def _add_to_session(self, item: dict[str, Any]) -> None:
        """Add a looked-up item to the scanning session.

        Args:
            item: Item dict from inventory.
        """
        self._session.add_item(item)
        self._insert_tree_row(item)
        self._update_stats()

    def _insert_tree_row(self, item: dict[str, Any]) -> None:
        """Insert a single item into the Treeview."""
        if self._tree is None:
            return

        values = []
        for col in self._display_columns:
            val = item.get(col, "")
            if col == FIELD_PRICE:
                val = f"₹{float(val):,.0f}" if val else "₹0"
            values.append(str(val))

        iid = f"scan_{self._session.item_count}"
        self._tree.insert("", tk.END, iid=iid, values=values)

    # -- session management --------------------------------------------------

    def _delete_selected(self) -> None:
        """Remove selected items from the session and treeview."""
        if self._tree is None:
            return

        selected = self._tree.selection()
        if not selected:
            self.app["app"].show_toast(
                "No Selection", "Select items to delete.", "warning"
            )
            return

        # Map treeview iids back to session indices
        # Since we delete from the end to preserve indices
        all_items = self._tree.get_children()
        indices_to_remove = []
        for iid in selected:
            try:
                idx = all_items.index(iid)
                indices_to_remove.append(idx)
            except ValueError:
                continue

        # Sort descending so we remove from the end first
        indices_to_remove.sort(reverse=True)

        for idx in indices_to_remove:
            self._session.remove_item(idx)

        # Rebuild treeview from session
        self._rebuild_tree()
        self._update_stats()

    def _clear_session(self) -> None:
        """Clear all items from the session after confirmation."""
        if self._session.item_count == 0:
            return

        response = Messagebox.okcancel(
            title="Clear Session",
            message=f"Clear all {self._session.item_count} scanned items?",
        )
        if response != "OK":
            return

        self._session.clear()
        self._rebuild_tree()
        self._update_stats()

    def _rebuild_tree(self) -> None:
        """Rebuild the entire treeview from the current session."""
        if self._tree is None:
            return

        for item in self._tree.get_children():
            self._tree.delete(item)

        for item in self._session.items:
            self._insert_tree_row(item)

    # -- export --------------------------------------------------------------

    def _export(self, fmt: str) -> None:
        """Export the current session to the chosen format.

        Args:
            fmt: Export format — ``"excel"`` or ``"pdf"``.
        """
        df = self._session.to_dataframe()
        if df.empty:
            self.app["app"].show_toast(
                "Empty Session", "No items to export.", "warning"
            )
            return

        reporting: ReportGenerator | None = self.app.get("reporting")
        if reporting is None:
            return

        ext_map = {"excel": ".xlsx", "pdf": ".pdf"}
        ext = ext_map.get(fmt, ".xlsx")
        file_path = filedialog.asksaveasfilename(
            title=f"Export Scan Session as {fmt.upper()}",
            defaultextension=ext,
            filetypes=[(f"{fmt.upper()} Files", f"*{ext}")],
        )
        if not file_path:
            return

        success = reporting.export(df, fmt, file_path)
        if success:
            self.app["app"].show_toast(
                "Export Complete",
                f"Saved {self._session.item_count} item(s) to {os.path.basename(file_path)}",
                "success",
            )
        else:
            self.app["app"].show_toast(
                "Export Failed", "Could not write file.", "danger"
            )

    # -- stats ---------------------------------------------------------------

    def _update_stats(self) -> None:
        """Update the item count and total value display."""
        self._count_var.set(f"Items: {self._session.item_count}")
        total = self._session.total_value
        self._value_var.set(f"Total Value: ₹{total:,.0f}")

    # -- lifecycle -----------------------------------------------------------

    def on_show(self) -> None:
        """Load existing session data when the screen becomes visible."""
        # Session persists in memory; stats are already current.
        # If the tree is empty but session has items, rebuild.
        if self._tree is not None and self._session.item_count > 0:
            if not self._tree.get_children():
                self._rebuild_tree()
        self._update_stats()

    def focus_primary(self) -> None:
        """Focus the scan entry field."""
        if hasattr(self, "_scan_entry"):
            self._scan_entry.focus_set()
            self._scan_entry.select_range(0, tk.END)
