"""Operational screens for StockMate.

Provides SearchScreen, StatusScreen, and EditDataScreen for day-to-day
inventory operations: searching items, updating status, and bulk editing.
All screens extend ``BaseScreen`` and receive the application context dict.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from typing import Any

import ttkbootstrap as tb
from ttkbootstrap.dialogs import Messagebox

from core.constants import (
    FIELD_BUYER,
    FIELD_BUYER_CONTACT,
    FIELD_COLOR,
    FIELD_CONDITION,
    FIELD_GRADE,
    FIELD_IMEI,
    FIELD_MODEL,
    FIELD_NOTES,
    FIELD_PRICE,
    FIELD_RAM_ROM,
    FIELD_SOURCE_FILE,
    FIELD_STATUS,
    FIELD_UNIQUE_ID,
    STATUS_IN,
    STATUS_OUT,
    STATUS_RETURN,
)
from gui.base import AutocompleteEntry, BaseScreen
from gui.widgets import CollapsibleFrame


# ---------------------------------------------------------------------------
# SearchScreen
# ---------------------------------------------------------------------------


class SearchScreen(BaseScreen):
    """Search & item details screen.

    Supports exact ID lookup and partial model/IMEI search. Displays
    selected item details with a Details & History tabbed pane. Context
    menu offers quick actions: mark sold, add to invoice, print label,
    edit, and copy IMEI.
    """

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)

        self._search_var = tk.StringVar()
        self._results_tree: ttk.Treeview | None = None
        self._detail_labels: dict[str, ttk.Label] = {}
        self._history_tree: ttk.Treeview | None = None
        self._current_item: dict[str, Any] | None = None

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the search screen layout."""
        # Header
        self.add_header("Search")

        # Search bar
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=12, pady=6)

        ttk.Label(search_frame, text="ID / Model / IMEI:").pack(side=tk.LEFT, padx=4)
        self._search_entry = ttk.Entry(
            search_frame, textvariable=self._search_var, width=40
        )
        self._search_entry.pack(side=tk.LEFT, padx=4)
        self._search_entry.bind("<Return>", lambda e: self._search())

        ttk.Button(
            search_frame,
            text="Search",
            bootstyle="primary",
            command=self._search,
        ).pack(side=tk.LEFT, padx=4)

        # Main split: results + details
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

        # Results (left)
        results_frame = ttk.Labelframe(main_frame, text="Results", padding=8)
        results_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        results_columns = ("id", "imei", "model", "ram_rom", "price", "status")
        self._results_tree = ttk.Treeview(
            results_frame, columns=results_columns, show="headings", height=12
        )
        self._results_tree.heading("id", text="ID")
        self._results_tree.heading("imei", text="IMEI")
        self._results_tree.heading("model", text="Model")
        self._results_tree.heading("ram_rom", text="RAM/ROM")
        self._results_tree.heading("price", text="Price")
        self._results_tree.heading("status", text="Status")
        self._results_tree.column("id", width=50, anchor=tk.CENTER)
        self._results_tree.column("imei", width=130)
        self._results_tree.column("model", width=180)
        self._results_tree.column("ram_rom", width=70, anchor=tk.CENTER)
        self._results_tree.column("price", width=70, anchor=tk.E)
        self._results_tree.column("status", width=50, anchor=tk.CENTER)

        results_scroll = ttk.Scrollbar(
            results_frame, orient=tk.VERTICAL, command=self._results_tree.yview
        )
        self._results_tree.configure(yscrollcommand=results_scroll.set)
        self._results_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        results_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._results_tree.bind("<<TreeviewSelect>>", self._on_select)
        self._results_tree.bind("<Button-3>", self._open_context_menu)

        # Details pane (right)
        details_frame = ttk.Labelframe(main_frame, text="Details", padding=8)
        details_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))

        # Notebook for tabs
        nb = ttk.Notebook(details_frame)
        nb.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Details & Specs
        specs_tab = ttk.Frame(nb, padding=4)
        nb.add(specs_tab, text="Details & Specs")
        self._build_specs_tab(specs_tab)

        # Tab 2: History & Logs
        history_tab = ttk.Frame(nb, padding=4)
        nb.add(history_tab, text="History & Logs")
        self._build_history_tab(history_tab)

    def _build_specs_tab(self, parent: ttk.Frame) -> None:
        """Build the details/specs tab with label-value pairs."""
        fields = [
            ("unique_id", "ID"),
            ("imei", "IMEI"),
            ("model", "Model"),
            ("ram_rom", "RAM / ROM"),
            ("price", "Price"),
            ("supplier", "Supplier"),
            ("status", "Status"),
            ("color", "Color"),
            ("grade", "Grade"),
            ("condition", "Condition"),
            ("buyer", "Buyer"),
            ("buyer_contact", "Buyer Contact"),
            ("source_file", "Source File"),
            ("notes", "Notes"),
        ]

        for idx, (key, label) in enumerate(fields):
            ttk.Label(parent, text=label, font=("Segoe UI", 9, "bold")).grid(
                row=idx, column=0, sticky=tk.W, padx=4, pady=2
            )
            val_lbl = ttk.Label(parent, text="—", font=("Segoe UI", 9))
            val_lbl.grid(row=idx, column=1, sticky=tk.W, padx=4, pady=2)
            self._detail_labels[key] = val_lbl

        parent.grid_columnconfigure(1, weight=1)

    def _build_history_tab(self, parent: ttk.Frame) -> None:
        """Build the history/logs tab with a Treeview."""
        history_columns = ("timestamp", "action", "details")
        self._history_tree = ttk.Treeview(
            parent, columns=history_columns, show="headings", height=12
        )
        self._history_tree.heading("timestamp", text="Timestamp")
        self._history_tree.heading("action", text="Action")
        self._history_tree.heading("details", text="Details")
        self._history_tree.column("timestamp", width=140)
        self._history_tree.column("action", width=110)
        self._history_tree.column("details", width=300)

        history_scroll = ttk.Scrollbar(
            parent, orient=tk.VERTICAL, command=self._history_tree.yview
        )
        self._history_tree.configure(yscrollcommand=history_scroll.set)
        self._history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        history_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # -- search & selection --------------------------------------------------

    def _search(self) -> None:
        """Search by ID (exact) or Model/IMEI (partial)."""
        if self._results_tree is None:
            return

        for iid in self._results_tree.get_children():
            self._results_tree.delete(iid)

        query = self._search_var.get().strip()
        if not query:
            return

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            return

        # Try exact ID match first
        try:
            exact_id = int(query)
            mask = df[FIELD_UNIQUE_ID] == exact_id
            results = df[mask]
            if not results.empty:
                self._populate_results(results)
                return
        except (ValueError, TypeError):
            pass

        # Partial match on model or IMEI
        query_lower = query.lower()
        model_mask = (
            df[FIELD_MODEL].astype(str).str.lower().str.contains(query_lower, na=False)
        )
        imei_mask = (
            df[FIELD_IMEI].astype(str).str.lower().str.contains(query_lower, na=False)
        )
        results = df[model_mask | imei_mask]

        self._populate_results(results)

    def _populate_results(self, results_df: Any) -> None:
        """Populate the results treeview from a DataFrame."""
        if self._results_tree is None:
            return

        for _, row in results_df.iterrows():
            uid = row.get(FIELD_UNIQUE_ID, "")
            self._results_tree.insert(
                "",
                tk.END,
                iid=str(uid),
                values=(
                    int(uid),
                    row.get(FIELD_IMEI, ""),
                    row.get(FIELD_MODEL, ""),
                    row.get(FIELD_RAM_ROM, ""),
                    f"\u20b9{row.get(FIELD_PRICE, 0):,.0f}",
                    row.get(FIELD_STATUS, ""),
                ),
            )

    def _on_select(self, event: tk.Event) -> None:
        """Show details for the selected item."""
        if self._results_tree is None:
            return

        sel = self._results_tree.selection()
        if not sel:
            return

        item_id = sel[0]
        inventory = self.app.get("inventory")
        if inventory is None:
            return

        item, _ = inventory.get_item_by_id(item_id)
        if item is None:
            return

        self._current_item = item
        self._update_detail_labels(item)
        self._load_history(item_id)

    def _update_detail_labels(self, item: dict[str, Any]) -> None:
        """Update the detail label widgets with item data."""
        mapping = {
            "unique_id": str(item.get(FIELD_UNIQUE_ID, "")),
            "imei": str(item.get(FIELD_IMEI, "—")),
            "model": str(item.get(FIELD_MODEL, "—")),
            "ram_rom": str(item.get(FIELD_RAM_ROM, "—")),
            "price": f"\u20b9{item.get(FIELD_PRICE, 0):,.0f}",
            "supplier": str(item.get("supplier", "—")),
            "status": str(item.get(FIELD_STATUS, "—")),
            "color": str(item.get(FIELD_COLOR, "—")),
            "grade": str(item.get(FIELD_GRADE, "—")),
            "condition": str(item.get(FIELD_CONDITION, "—")),
            "buyer": str(item.get(FIELD_BUYER, "—")),
            "buyer_contact": str(item.get(FIELD_BUYER_CONTACT, "—")),
            "source_file": str(item.get(FIELD_SOURCE_FILE, "—")),
            "notes": str(item.get(FIELD_NOTES, "—")),
        }

        for key, value in mapping.items():
            lbl = self._detail_labels.get(key)
            if lbl is not None:
                lbl.configure(text=value if value else "—")

    def _load_history(self, item_id: str) -> None:
        """Load history timeline from the database."""
        if self._history_tree is None:
            return

        for iid in self._history_tree.get_children():
            self._history_tree.delete(iid)

        db = self.app.get("db")
        if db is None:
            return

        try:
            numeric_id = int(item_id)
        except (ValueError, TypeError):
            return

        history = db.get_metadata(numeric_id)
        # History is stored separately; query the DB
        try:
            rows = db._conn.execute(
                "SELECT timestamp, action, details FROM history WHERE item_id = ? ORDER BY id DESC",
                (numeric_id,),
            ).fetchall()

            for row in rows:
                ts = row[0]
                if ts and len(ts) > 19:
                    ts = ts[:19]
                self._history_tree.insert(
                    "",
                    tk.END,
                    values=(ts, row[1], row[2]),
                )
        except Exception:
            pass

    # -- context menu --------------------------------------------------------

    def _open_context_menu(self, event: tk.Event) -> None:
        """Show context menu on right-click."""
        if self._results_tree is None:
            return

        # Select the row under cursor
        row_id = self._results_tree.identify_row(event.y)
        if row_id:
            self._results_tree.selection_set(row_id)
            self._results_tree.focus(row_id)

        sel = self._results_tree.selection()
        if not sel:
            return

        item_id = sel[0]
        inventory = self.app.get("inventory")
        if inventory is None:
            return

        item, _ = inventory.get_item_by_id(item_id)
        if item is None:
            return

        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Mark SOLD", command=lambda: self._mark_sold(item))
        menu.add_command(
            label="Add to Invoice", command=lambda: self._add_to_invoice(item)
        )
        menu.add_command(label="Print Label", command=lambda: self._print_label(item))
        menu.add_command(label="Edit", command=lambda: self._edit_item(item))
        menu.add_command(label="Copy IMEI", command=lambda: self._copy_imei(item))

        menu.tk_popup(event.x_root, event.y_root)

    def _mark_sold(self, item: dict[str, Any]) -> None:
        """Quick status update to OUT."""
        item_id = item.get(FIELD_UNIQUE_ID)
        if item_id is None:
            return

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        success = inventory.update_item_status(item_id, STATUS_OUT)
        if success:
            self.app.get("app").show_toast(
                "Marked Sold", f"Item {item_id} marked as OUT.", "success"
            )
            self._search()
        else:
            self.app.get("app").show_toast(
                "Failed", "Could not update status.", "danger"
            )

    def _add_to_invoice(self, item: dict[str, Any]) -> None:
        """Switch to billing with this item."""
        self.app.get("app").switch_to_billing([item])

    def _print_label(self, item: dict[str, Any]) -> None:
        """Print label via printer manager."""
        printer = self.app.get("printer")
        barcode = self.app.get("barcode")
        if printer is None or barcode is None:
            self.app.get("app").show_toast(
                "Print Failed", "Printer or barcode module not available.", "danger"
            )
            return

        try:
            printer.print_label(item, barcode)
            self.app.get("app").show_toast(
                "Label Printed",
                f"Label for item {item.get(FIELD_UNIQUE_ID, '')}.",
                "success",
            )
        except Exception as exc:
            self.app.get("app").show_toast("Print Failed", str(exc), "danger")

    def _edit_item(self, item: dict[str, Any]) -> None:
        """Switch to edit screen with this item pre-loaded."""
        self.app.get("app").show_screen("edit")
        edit_screen = self.app.get("app").screens.get("edit")
        if edit_screen is not None and hasattr(edit_screen, "load_item_by_id"):
            edit_screen.load_item_by_id(item.get(FIELD_UNIQUE_ID, ""))

    def _copy_imei(self, item: dict[str, Any]) -> None:
        """Copy IMEI to clipboard."""
        imei = str(item.get(FIELD_IMEI, ""))
        if not imei:
            self.app.get("app").show_toast(
                "No IMEI", "This item has no IMEI.", "warning"
            )
            return

        self.clipboard_clear()
        self.clipboard_append(imei)
        self.app.get("app").show_toast(
            "Copied", f"IMEI copied to clipboard.", "success"
        )

    # -- lifecycle -----------------------------------------------------------

    def focus_primary(self) -> None:
        """Focus the search entry."""
        self._search_entry.focus_set()
        self._search_entry.select_range(0, tk.END)

    def on_show(self) -> None:
        """Focus search when the screen becomes visible."""
        self.focus_primary()


# ---------------------------------------------------------------------------
# StatusScreen
# ---------------------------------------------------------------------------


class StatusScreen(BaseScreen):
    """Quick status update screen (F3).

    Scan an item ID, view details, and change status with optional buyer
    info. Supports batch mode for scanning multiple items before applying
    a single status change.
    """

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)

        self._scan_var = tk.StringVar()
        self._batch_mode = tk.BooleanVar(value=False)
        self._batch_queue: list[dict[str, Any]] = []
        self._last_action: dict[str, Any] | None = None

        self._current_item: dict[str, Any] | None = None
        self._detail_labels: dict[str, ttk.Label] = {}

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the status update layout."""
        # Header
        self.add_header("Quick Status Update")

        # Scan bar
        scan_frame = ttk.Frame(self)
        scan_frame.pack(fill=tk.X, padx=12, pady=6)

        ttk.Label(scan_frame, text="Scan ID:").pack(side=tk.LEFT, padx=4)
        self._scan_entry = ttk.Entry(scan_frame, textvariable=self._scan_var, width=30)
        self._scan_entry.pack(side=tk.LEFT, padx=4)
        self._scan_entry.bind("<Return>", self._on_scan)

        # Batch mode toggle
        ttk.Checkbutton(
            scan_frame,
            text="Batch Mode",
            variable=self._batch_mode,
            command=self._toggle_batch_ui,
        ).pack(side=tk.LEFT, padx=12)

        # Item details (read-only)
        details_frame = ttk.Labelframe(self, text="Item Details", padding=8)
        details_frame.pack(fill=tk.X, padx=12, pady=6)

        detail_fields = [
            ("unique_id", "ID"),
            ("imei", "IMEI"),
            ("model", "Model"),
            ("status", "Current Status"),
        ]

        for idx, (key, label) in enumerate(detail_fields):
            ttk.Label(details_frame, text=label, font=("Segoe UI", 9, "bold")).grid(
                row=0, column=idx * 2, padx=8, pady=4, sticky=tk.W
            )
            val_lbl = ttk.Label(details_frame, text="—", font=("Segoe UI", 9))
            val_lbl.grid(row=0, column=idx * 2 + 1, padx=8, pady=4, sticky=tk.W)
            self._detail_labels[key] = val_lbl

        # Status buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=6)

        self._btn_out = ttk.Button(
            btn_frame,
            text="OUT (Sold)",
            bootstyle="danger",
            command=lambda: self._update_status(STATUS_OUT),
        )
        self._btn_out.pack(side=tk.LEFT, padx=4)

        self._btn_rtn = ttk.Button(
            btn_frame,
            text="RTN (Return)",
            bootstyle="warning",
            command=lambda: self._update_status(STATUS_RETURN),
        )
        self._btn_rtn.pack(side=tk.LEFT, padx=4)

        self._btn_in = ttk.Button(
            btn_frame,
            text="IN (Restock)",
            bootstyle="success",
            command=lambda: self._update_status(STATUS_IN),
        )
        self._btn_in.pack(side=tk.LEFT, padx=4)

        # Undo button
        self._undo_btn = ttk.Button(
            btn_frame,
            text="Undo Last",
            bootstyle="secondary-outline",
            command=self._undo_last,
            state=tk.DISABLED,
        )
        self._undo_btn.pack(side=tk.RIGHT, padx=4)

        # Buyer info frame (hidden by default)
        self._buyer_frame = CollapsibleFrame(self)
        buyer_inner = ttk.Frame(self._buyer_frame, padding=8)
        buyer_inner.pack(fill=tk.X)

        ttk.Label(buyer_inner, text="Buyer Name:").grid(
            row=0, column=0, sticky=tk.W, padx=4, pady=4
        )
        self._buyer_name_var = tk.StringVar()
        self._buyer_entry = AutocompleteEntry(
            buyer_inner, textvariable=self._buyer_name_var, width=30
        )
        self._buyer_entry.grid(row=0, column=1, padx=4, pady=4, sticky=tk.W)

        ttk.Label(buyer_inner, text="Contact:").grid(
            row=1, column=0, sticky=tk.W, padx=4, pady=4
        )
        self._buyer_contact_var = tk.StringVar()
        ttk.Entry(buyer_inner, textvariable=self._buyer_contact_var, width=30).grid(
            row=1, column=1, padx=4, pady=4, sticky=tk.W
        )

        ttk.Label(buyer_inner, text="Notes:").grid(
            row=2, column=0, sticky=tk.NW, padx=4, pady=4
        )
        self._buyer_notes_var = tk.StringVar()
        ttk.Entry(buyer_inner, textvariable=self._buyer_notes_var, width=30).grid(
            row=2, column=1, padx=4, pady=4, sticky=tk.W
        )

        ttk.Button(
            buyer_inner,
            text="Confirm SOLD",
            bootstyle="danger",
            command=lambda: self._confirm_sold(),
        ).grid(row=3, column=0, columnspan=2, pady=8)

        # Batch review frame (hidden by default)
        self._batch_frame = CollapsibleFrame(self)
        batch_inner = ttk.Frame(self._batch_frame, padding=8)
        batch_inner.pack(fill=tk.BOTH, expand=True)

        ttk.Label(batch_inner, text="Batch Queue:", font=("Segoe UI", 10, "bold")).pack(
            anchor=tk.W
        )

        batch_columns = ("id", "model", "status")
        self._batch_tree = ttk.Treeview(
            batch_inner, columns=batch_columns, show="headings", height=5
        )
        self._batch_tree.heading("id", text="ID")
        self._batch_tree.heading("model", text="Model")
        self._batch_tree.heading("status", text="Status")
        self._batch_tree.column("id", width=60, anchor=tk.CENTER)
        self._batch_tree.column("model", width=200)
        self._batch_tree.column("status", width=60, anchor=tk.CENTER)
        self._batch_tree.pack(fill=tk.X, pady=4)

        batch_btn_frame = ttk.Frame(batch_inner)
        batch_btn_frame.pack(fill=tk.X, pady=4)

        self._batch_confirm_btn = ttk.Button(
            batch_btn_frame,
            text="Confirm All",
            bootstyle="success",
            command=self._confirm_batch,
        )
        self._batch_confirm_btn.pack(side=tk.RIGHT, padx=4)

        ttk.Button(
            batch_btn_frame,
            text="Clear Batch",
            bootstyle="danger-outline",
            command=self._clear_batch,
        ).pack(side=tk.RIGHT, padx=4)

    # -- scanning & lookup ---------------------------------------------------

    def _on_scan(self, event: tk.Event) -> None:
        """Lookup item by ID and show details."""
        item_id = self._scan_var.get().strip()
        if not item_id:
            return

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        item, redirected = inventory.get_item_by_id(item_id)
        if item is None:
            self.app.get("app").show_toast(
                "Not Found", f"No item found with ID {item_id}.", "warning"
            )
            return

        self._current_item = item
        self._update_detail_display(item)

        # In batch mode, add to queue instead of showing details only
        if self._batch_mode.get():
            self._add_to_batch(item)
            self._scan_var.set("")
        else:
            # Show buyer frame if marking OUT
            self._show_buyer_frame(False)

    def _update_detail_display(self, item: dict[str, Any]) -> None:
        """Update the detail labels with current item data."""
        self._detail_labels["unique_id"].configure(
            text=str(item.get(FIELD_UNIQUE_ID, "—"))
        )
        self._detail_labels["imei"].configure(text=str(item.get(FIELD_IMEI, "—")))
        self._detail_labels["model"].configure(text=str(item.get(FIELD_MODEL, "—")))
        self._detail_labels["status"].configure(text=str(item.get(FIELD_STATUS, "—")))

    # -- status update -------------------------------------------------------

    def _update_status(self, new_status: str) -> None:
        """Update item status with optional buyer info."""
        if self._current_item is None:
            self.app.get("app").show_toast("No Item", "Scan an item first.", "warning")
            return

        item_id = self._current_item.get(FIELD_UNIQUE_ID)
        if item_id is None:
            return

        # Show buyer frame for OUT status
        if new_status == STATUS_OUT:
            self._show_buyer_frame(True)
            return

        # For non-OUT statuses, update directly
        self._apply_status_change(item_id, new_status)

    def _apply_status_change(self, item_id: Any, new_status: str) -> None:
        """Apply the status change to the inventory."""
        inventory = self.app.get("inventory")
        if inventory is None:
            return

        # Attach buyer info if available
        if new_status == STATUS_OUT:
            buyer = self._buyer_name_var.get().strip()
            contact = self._buyer_contact_var.get().strip()
            notes = self._buyer_notes_var.get().strip()

            if buyer:
                db = self.app.get("db")
                if db is not None:
                    try:
                        db.update_metadata(
                            int(item_id),
                            buyer=buyer,
                            buyer_contact=contact,
                            notes=notes,
                        )
                    except (ValueError, TypeError):
                        pass

        success = inventory.update_item_status(item_id, new_status)
        if success:
            self._last_action = {
                "item_id": item_id,
                "old_status": self._current_item.get(FIELD_STATUS, ""),
                "new_status": new_status,
            }
            self._undo_btn.configure(state=tk.NORMAL)

            status_name = {
                STATUS_OUT: "SOLD",
                STATUS_RETURN: "RETURNED",
                STATUS_IN: "RESTOCKED",
            }.get(new_status, new_status)
            self.app.get("app").show_toast(
                "Status Updated",
                f"Item {item_id} marked as {status_name}.",
                "success",
            )

            # Refresh display
            item, _ = inventory.get_item_by_id(item_id)
            if item is not None:
                self._current_item = item
                self._update_detail_display(item)

            # Clear buyer fields
            self._buyer_name_var.set("")
            self._buyer_contact_var.set("")
            self._buyer_notes_var.set("")
            self._show_buyer_frame(False)
        else:
            self.app.get("app").show_toast(
                "Update Failed", "Could not update status.", "danger"
            )

    def _show_buyer_frame(self, show: bool) -> None:
        """Show or hide the buyer info frame."""
        if show:
            self._buyer_frame.show(fill=tk.X, padx=12, pady=4)
            # Update autocomplete list from existing buyers
            self._update_buyer_autocomplete()
            self._buyer_entry.focus_set()
        else:
            self._buyer_frame.hide()

    def _confirm_sold(self) -> None:
        """Confirm the SOLD status change with buyer info."""
        if self._current_item is None:
            return
        item_id = self._current_item.get(FIELD_UNIQUE_ID)
        if item_id is None:
            return
        self._apply_status_change(item_id, STATUS_OUT)

    def _update_buyer_autocomplete(self) -> None:
        """Populate buyer autocomplete from sold items."""
        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            return

        out_stock = df[df[FIELD_STATUS] == STATUS_OUT]
        if out_stock.empty:
            return

        buyers = sorted(out_stock[FIELD_BUYER].dropna().unique().tolist())
        buyers = [b for b in buyers if b.strip()]
        self._buyer_entry.set_completion_list(buyers)

    # -- batch mode ----------------------------------------------------------

    def _toggle_batch_ui(self) -> None:
        """Show/hide batch UI based on toggle state."""
        if self._batch_mode.get():
            self._batch_frame.show(fill=tk.BOTH, expand=True, padx=12, pady=4)
        else:
            self._batch_frame.hide()
            self._clear_batch()

    def _add_to_batch(self, item: dict[str, Any]) -> None:
        """Add item to the batch queue."""
        self._batch_queue.append(item)
        self._refresh_batch_tree()

    def _refresh_batch_tree(self) -> None:
        """Update the batch treeview display."""
        if not hasattr(self, "_batch_tree") or self._batch_tree is None:
            return

        for iid in self._batch_tree.get_children():
            self._batch_tree.delete(iid)

        for item in self._batch_queue:
            self._batch_tree.insert(
                "",
                tk.END,
                values=(
                    item.get(FIELD_UNIQUE_ID, ""),
                    item.get(FIELD_MODEL, ""),
                    item.get(FIELD_STATUS, ""),
                ),
            )

    def _confirm_batch(self) -> None:
        """Apply status to all batched items."""
        if not self._batch_queue:
            self.app.get("app").show_toast(
                "Empty Batch", "No items in batch queue.", "warning"
            )
            return

        # Determine target status from context — default to OUT for batch
        target_status = STATUS_OUT

        confirm = Messagebox.okcancel(
            title="Confirm Batch",
            message=f"Mark {len(self._batch_queue)} item(s) as {target_status}?",
        )
        if confirm != "OK":
            return

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        success_count = 0
        for item in self._batch_queue:
            item_id = item.get(FIELD_UNIQUE_ID)
            if item_id is not None:
                if inventory.update_item_status(item_id, target_status):
                    success_count += 1

        self.app.get("app").show_toast(
            "Batch Complete",
            f"{success_count}/{len(self._batch_queue)} items updated.",
            "success",
        )

        self._last_action = {
            "batch": True,
            "items": list(self._batch_queue),
            "status": target_status,
        }
        self._undo_btn.configure(state=tk.NORMAL)

        self._clear_batch()
        self._scan_var.set("")

    def _clear_batch(self) -> None:
        """Clear the batch queue."""
        self._batch_queue.clear()
        self._refresh_batch_tree()

    def _undo_last(self) -> None:
        """Revert the last status change."""
        if self._last_action is None:
            return

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        action = self._last_action
        if action.get("batch"):
            # Undo batch: revert all items to their original status
            for item in action.get("items", []):
                item_id = item.get(FIELD_UNIQUE_ID)
                old_status = item.get(FIELD_STATUS, STATUS_IN)
                if item_id is not None:
                    inventory.update_item_status(item_id, old_status)
            self.app.get("app").show_toast(
                "Batch Undone", f"Reverted {len(action['items'])} items.", "info"
            )
        else:
            item_id = action.get("item_id")
            old_status = action.get("old_status", STATUS_IN)
            if item_id is not None:
                inventory.update_item_status(item_id, old_status)
                self.app.get("app").show_toast(
                    "Undone", f"Item {item_id} reverted to {old_status}.", "info"
                )

        self._last_action = None
        self._undo_btn.configure(state=tk.DISABLED)

    # -- lifecycle -----------------------------------------------------------

    def focus_primary(self) -> None:
        """Focus the scan entry."""
        self._scan_entry.focus_set()
        self._scan_entry.select_range(0, tk.END)

    def on_show(self) -> None:
        """Clear form and focus scan when the screen becomes visible."""
        self._scan_var.set("")
        self._current_item = None
        for lbl in self._detail_labels.values():
            lbl.configure(text="—")
        self._show_buyer_frame(False)
        self.focus_primary()


# ---------------------------------------------------------------------------
# EditDataScreen
# ---------------------------------------------------------------------------


class EditDataScreen(BaseScreen):
    """High-speed bulk edit screen.

    Search for an item by ID/IMEI/Model, load it into an editable form,
    and save changes. Each field has a skip toggle so Enter navigates
    only to non-skipped fields, with the last field triggering save.
    """

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)

        self._search_var = tk.StringVar()
        self._current_item: dict[str, Any] | None = None
        self._field_vars: dict[str, tk.StringVar] = {}
        self._field_skips: dict[str, tk.BooleanVar] = {}
        self._field_entries: dict[str, ttk.Entry] = {}
        self._field_order: list[str] = []

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the edit screen layout."""
        # Header
        self.add_header("High-Speed Edit")

        # Search bar
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=12, pady=6)

        ttk.Label(search_frame, text="ID / IMEI / Model:").pack(side=tk.LEFT, padx=4)
        self._search_entry = ttk.Entry(
            search_frame, textvariable=self._search_var, width=35
        )
        self._search_entry.pack(side=tk.LEFT, padx=4)
        self._search_entry.bind("<Return>", lambda e: self._load_item())

        ttk.Button(
            search_frame,
            text="Load",
            bootstyle="primary",
            command=self._load_item,
        ).pack(side=tk.LEFT, padx=4)

        # Edit form
        form_frame = ttk.Labelframe(self, text="Edit Fields", padding=12)
        form_frame.pack(fill=tk.X, padx=12, pady=6)

        editable_fields = [
            ("model", "Model"),
            ("imei", "IMEI"),
            ("supplier", "Supplier"),
            ("price", "Price"),
            ("color", "Color"),
            ("grade", "Grade"),
            ("condition", "Condition"),
            ("notes", "Notes"),
        ]

        self._field_order = [f[0] for f in editable_fields]

        for idx, (key, label) in enumerate(editable_fields):
            row_frame = ttk.Frame(form_frame)
            row_frame.pack(fill=tk.X, pady=2)

            ttk.Label(row_frame, text=label, width=12).pack(side=tk.LEFT, padx=4)

            var = tk.StringVar()
            self._field_vars[key] = var

            entry = ttk.Entry(row_frame, textvariable=var, width=30)
            entry.pack(side=tk.LEFT, padx=4)
            entry.bind("<Return>", self._on_enter)
            self._field_entries[key] = entry

            skip_var = tk.BooleanVar(value=False)
            self._field_skips[key] = skip_var

            ttk.Checkbutton(
                row_frame,
                text="Skip",
                variable=skip_var,
                command=lambda k=key: self._apply_skip(k),
            ).pack(side=tk.LEFT, padx=4)

        # Action buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=8)

        ttk.Button(
            btn_frame,
            text="Save",
            bootstyle="success",
            command=self._save_item,
        ).pack(side=tk.RIGHT, padx=4)

        ttk.Button(
            btn_frame,
            text="Next Item",
            bootstyle="info-outline",
            command=self._next_item,
        ).pack(side=tk.RIGHT, padx=4)

        ttk.Button(
            btn_frame,
            text="Clear",
            bootstyle="secondary-outline",
            command=self._clear_form,
        ).pack(side=tk.RIGHT, padx=4)

    # -- loading -------------------------------------------------------------

    def _load_item(self) -> None:
        """Search and load item into the form."""
        query = self._search_var.get().strip()
        if not query:
            self.app.get("app").show_toast(
                "No Query", "Enter an ID, IMEI, or model to search.", "warning"
            )
            return

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            return

        # Try exact ID first
        try:
            exact_id = int(query)
            mask = df[FIELD_UNIQUE_ID] == exact_id
            results = df[mask]
            if not results.empty:
                self._populate_form(results.iloc[0].to_dict())
                return
        except (ValueError, TypeError):
            pass

        # Partial match on IMEI or model
        query_lower = query.lower()
        imei_mask = (
            df[FIELD_IMEI].astype(str).str.lower().str.contains(query_lower, na=False)
        )
        model_mask = (
            df[FIELD_MODEL].astype(str).str.lower().str.contains(query_lower, na=False)
        )
        results = df[imei_mask | model_mask]

        if results.empty:
            self.app.get("app").show_toast(
                "Not Found", f"No item matches '{query}'.", "warning"
            )
            return

        # Take first match
        self._populate_form(results.iloc[0].to_dict())

    def _populate_form(self, item: dict[str, Any]) -> None:
        """Fill the form fields with item data."""
        self._current_item = item

        field_mapping = {
            "model": FIELD_MODEL,
            "imei": FIELD_IMEI,
            "supplier": "supplier",
            "price": FIELD_PRICE,
            "color": FIELD_COLOR,
            "grade": FIELD_GRADE,
            "condition": FIELD_CONDITION,
            "notes": FIELD_NOTES,
        }

        for field_key, col_name in field_mapping.items():
            var = self._field_vars.get(field_key)
            entry = self._field_entries.get(field_key)
            if var is None or entry is None:
                continue

            value = item.get(col_name, "")
            if value is None:
                value = ""
            # Convert price to string without formatting
            if field_key == "price":
                try:
                    value = str(float(value))
                except (ValueError, TypeError):
                    value = "0"

            var.set(str(value))
            # Reset skip toggle
            self._field_skips[field_key].set(False)
            entry.configure(state=tk.NORMAL)

    # -- saving --------------------------------------------------------------

    def _save_item(self) -> None:
        """Save changes via inventory.update_item_data()."""
        if self._current_item is None:
            self.app.get("app").show_toast("No Item", "Load an item first.", "warning")
            return

        item_id = self._current_item.get(FIELD_UNIQUE_ID)
        if item_id is None:
            return

        updates: dict[str, Any] = {}
        field_mapping = {
            "model": FIELD_MODEL,
            "imei": FIELD_IMEI,
            "supplier": "supplier",
            "price": FIELD_PRICE,
            "color": FIELD_COLOR,
            "grade": FIELD_GRADE,
            "condition": FIELD_CONDITION,
            "notes": FIELD_NOTES,
        }

        for field_key, col_name in field_mapping.items():
            skip = self._field_skips.get(field_key)
            if skip is not None and skip.get():
                continue

            var = self._field_vars.get(field_key)
            if var is None:
                continue

            value = var.get().strip()
            if not value:
                continue

            # Convert price to float
            if field_key == "price":
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    self.app.get("app").show_toast(
                        "Invalid Price", "Price must be a number.", "warning"
                    )
                    return

            updates[col_name] = value

        if not updates:
            self.app.get("app").show_toast("No Changes", "No fields to update.", "info")
            return

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        success = inventory.update_item_data(item_id, updates)
        if success:
            self.app.get("app").show_toast(
                "Saved", f"Item {item_id} updated.", "success"
            )
            # Reload to reflect changes
            item, _ = inventory.get_item_by_id(item_id)
            if item is not None:
                self._current_item = item
        else:
            self.app.get("app").show_toast(
                "Save Failed", "Could not update item.", "danger"
            )

    # -- navigation ----------------------------------------------------------

    def _next_field(self, current_field: str) -> None:
        """Navigate to the next non-skipped field."""
        current_idx = (
            self._field_order.index(current_field)
            if current_field in self._field_order
            else -1
        )
        if current_idx < 0:
            return

        for idx in range(current_idx + 1, len(self._field_order)):
            field_key = self._field_order[idx]
            skip = self._field_skips.get(field_key)
            entry = self._field_entries.get(field_key)
            if skip is not None and not skip.get() and entry is not None:
                entry.focus_set()
                entry.select_range(0, tk.END)
                return

        # No more fields — save
        self._save_item()

    def _on_enter(self, event: tk.Event) -> None:
        """Smart Enter: navigate to next non-skipped field or save."""
        # Find which entry triggered this
        widget = event.widget
        current_field = None
        for key, entry in self._field_entries.items():
            if entry is widget:
                current_field = key
                break

        if current_field is None:
            return

        self._next_field(current_field)
        return "break"

    def _apply_skip(self, field_key: str) -> None:
        """Enable/disable a field based on its skip toggle."""
        entry = self._field_entries.get(field_key)
        skip = self._field_skips.get(field_key)
        if entry is None or skip is None:
            return

        if skip.get():
            entry.configure(state=tk.DISABLED)
        else:
            entry.configure(state=tk.NORMAL)

    def _clear_form(self) -> None:
        """Reset all fields and clear current item."""
        self._current_item = None
        self._search_var.set("")

        for key in self._field_order:
            var = self._field_vars.get(key)
            skip = self._field_skips.get(key)
            entry = self._field_entries.get(key)
            if var is not None:
                var.set("")
            if skip is not None:
                skip.set(False)
            if entry is not None:
                entry.configure(state=tk.NORMAL)

    def _next_item(self) -> None:
        """Clear form and focus search for the next item."""
        self._clear_form()
        self.focus_primary()

    # Public method for external pre-loading
    def load_item_by_id(self, item_id: Any) -> None:
        """Load an item by its unique ID. Callable from other screens."""
        if item_id is None:
            return
        self._search_var.set(str(item_id))
        self._load_item()

    # -- lifecycle -----------------------------------------------------------

    def focus_primary(self) -> None:
        """Focus the search entry."""
        self._search_entry.focus_set()
        self._search_entry.select_range(0, tk.END)

    def on_show(self) -> None:
        """Clear form and focus search when the screen becomes visible."""
        self._clear_form()
        self.focus_primary()
