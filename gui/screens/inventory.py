"""Inventory screen module for StockMate.

Provides the main inventory grid view with filtering, multi-select,
bulk actions, label preview, and context menu operations.
"""

from __future__ import annotations

import datetime
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from typing import Any

import pandas as pd
import ttkbootstrap as tb
from ttkbootstrap.dialogs import Messagebox

from core.constants import (
    FIELD_IMEI,
    FIELD_MODEL,
    FIELD_PRICE,
    FIELD_RAM_ROM,
    FIELD_STATUS,
    FIELD_UNIQUE_ID,
    STATUS_IN,
    STATUS_OUT,
    STATUS_RETURN,
)

FIELD_SUPPLIER = "supplier"
from gui.base import BaseScreen
from gui.dialogs import ItemSelectionDialog, ZPLPreviewDialog, PrinterSelectionDialog
from gui.widgets import CollapsibleFrame, IconButton


# ---------------------------------------------------------------------------
# InventoryScreen
# ---------------------------------------------------------------------------


class InventoryScreen(BaseScreen):
    """Main inventory grid view.

    Displays the full inventory in a Treeview with filtering, multi-select,
    bulk operations, label preview, and context menu actions.

    Parameters
    ----------
    parent:
        Parent widget (the content area of MainApp).
    app_context:
        Dict with references to core managers and the main application window.
    """

    # -- constructor ---------------------------------------------------------

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)

        self._checked_ids: set[int] = set()
        self._preview_visible = False
        self._search_after_id: str | None = None
        self._context_menu: tk.Menu | None = None
        self._selection_anchor: str | None = None

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the full inventory screen layout."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # 1. Header (uses pack from BaseScreen.add_header)
        self.add_header("Inventory", help_section="inventory")

        # 2. Content wrapper: all grid-managed widgets go in this frame
        self._content_wrapper = ttk.Frame(self)
        self._content_wrapper.pack(fill=tk.BOTH, expand=True)
        self._content_wrapper.columnconfigure(0, weight=1)
        self._content_wrapper.rowconfigure(2, weight=1)

        # 3. Collapsible filter panel
        self._build_filter_panel()

        # 4. Main content: treeview + optional label preview
        self._build_main_content()

        # 5. Bottom bar: item count + bulk actions
        self._build_bottom_bar()

        # Context menu
        self._build_context_menu()

    def _build_filter_panel(self) -> None:
        """Build the collapsible filter panel."""
        filter_toggle = ttk.Frame(self._content_wrapper)
        filter_toggle.grid(row=1, column=0, sticky=tk.EW, padx=12, pady=(0, 4))
        filter_toggle.columnconfigure(0, weight=1)

        self._filter_toggle_btn = ttk.Button(
            filter_toggle,
            text="▼ Filters",
            bootstyle="secondary-outline",
            command=self._toggle_filters,
        )
        self._filter_toggle_btn.pack(side=tk.LEFT)

        self._filter_panel = ttk.Frame(self._content_wrapper)
        self._filter_panel.grid(row=2, column=0, sticky=tk.EW, padx=12, pady=4)
        self._filter_panel.grid_remove()
        self._filter_panel.columnconfigure(0, weight=1)

        inner = ttk.Frame(self._filter_panel, padding=8)
        inner.grid(row=0, column=0, sticky=tk.EW, padx=12, pady=4)

        # Row 1: Search + Supplier
        ttk.Label(inner, text="Search:").grid(row=0, column=0, sticky=tk.W, padx=4)
        self._search_var = tk.StringVar()
        self._search_entry = ttk.Entry(inner, textvariable=self._search_var, width=30)
        self._search_entry.grid(row=0, column=1, sticky=tk.W, padx=4)
        self._search_var.trace_add("write", self._on_search_change)

        ttk.Label(inner, text="Supplier:").grid(row=0, column=2, sticky=tk.W, padx=4)
        self._supplier_var = tk.StringVar()
        self._supplier_combo = ttk.Combobox(
            inner, textvariable=self._supplier_var, state="readonly", width=18
        )
        self._supplier_combo.grid(row=0, column=3, sticky=tk.W, padx=4)

        # Row 2: Status + Date range
        ttk.Label(inner, text="Status:").grid(row=1, column=0, sticky=tk.W, padx=4)
        self._status_var = tk.StringVar(value="All")
        self._status_combo = ttk.Combobox(
            inner,
            textvariable=self._status_var,
            values=["All", STATUS_IN, STATUS_OUT, STATUS_RETURN],
            state="readonly",
            width=10,
        )
        self._status_combo.grid(row=1, column=1, sticky=tk.W, padx=4)

        ttk.Label(inner, text="From:").grid(row=1, column=2, sticky=tk.W, padx=4)
        self._date_from_var = tk.StringVar()
        self._date_from_entry = ttk.Entry(
            inner, textvariable=self._date_from_var, width=12
        )
        self._date_from_entry.grid(row=1, column=3, sticky=tk.W, padx=4)

        ttk.Label(inner, text="To:").grid(row=1, column=4, sticky=tk.W, padx=4)
        self._date_to_var = tk.StringVar()
        self._date_to_entry = ttk.Entry(inner, textvariable=self._date_to_var, width=12)
        self._date_to_entry.grid(row=1, column=5, sticky=tk.W, padx=4)

        # Row 3: Buttons
        btn_frame = ttk.Frame(inner)
        btn_frame.grid(row=2, column=0, columnspan=6, sticky=tk.W, pady=(8, 0))

        ttk.Button(
            btn_frame,
            text="Apply Filter",
            bootstyle="primary",
            command=self._apply_filters,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btn_frame,
            text="Clear Filter",
            bootstyle="secondary-outline",
            command=self._clear_filters,
        ).pack(side=tk.LEFT, padx=4)

    def _build_main_content(self) -> None:
        """Build the treeview and label preview panel."""
        content_frame = ttk.Frame(self._content_wrapper)
        content_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=4)
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)

        # Treeview
        tree_frame = ttk.Frame(content_frame)
        tree_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        columns = (
            "check",
            "unique_id",
            FIELD_IMEI,
            FIELD_MODEL,
            FIELD_RAM_ROM,
            FIELD_PRICE,
            "supplier",
            FIELD_STATUS,
        )
        self._tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="extended"
        )

        self._tree.heading("check", text="☐", anchor=tk.CENTER)
        self._tree.heading("unique_id", text="ID", anchor=tk.CENTER)
        self._tree.heading(FIELD_IMEI, text="IMEI", anchor=tk.W)
        self._tree.heading(FIELD_MODEL, text="Model", anchor=tk.W)
        self._tree.heading(FIELD_RAM_ROM, text="RAM/ROM", anchor=tk.CENTER)
        self._tree.heading(FIELD_PRICE, text="Price", anchor=tk.E)
        self._tree.heading("supplier", text="Supplier", anchor=tk.W)
        self._tree.heading(FIELD_STATUS, text="Status", anchor=tk.CENTER)

        self._tree.column("check", width=40, anchor=tk.CENTER, stretch=False)
        self._tree.column("unique_id", width=60, anchor=tk.CENTER, stretch=False)
        self._tree.column(FIELD_IMEI, width=140, anchor=tk.W)
        self._tree.column(FIELD_MODEL, width=200, anchor=tk.W)
        self._tree.column(FIELD_RAM_ROM, width=90, anchor=tk.CENTER, stretch=False)
        self._tree.column(FIELD_PRICE, width=80, anchor=tk.E, stretch=False)
        self._tree.column("supplier", width=120, anchor=tk.W)
        self._tree.column(FIELD_STATUS, width=60, anchor=tk.CENTER, stretch=False)

        # Scrollbar
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky=tk.NS)
        hsb.grid(row=1, column=0, sticky=tk.EW)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        # Bindings
        self._tree.bind("<Double-1>", self._on_double_click)
        self._tree.bind("<Button-3>", self._on_context_menu)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Control-a>", self._select_all)
        self._tree.bind("<Control-Shift-Up>", self._extend_selection_up)
        self._tree.bind("<Control-Shift-Down>", self._extend_selection_down)
        self._tree.bind("<space>", self._toggle_check)
        self._tree.bind("<Button-1>", self._on_tree_click)

        # Label preview panel
        self._preview_frame = ttk.LabelFrame(
            content_frame, text="Label Preview", padding=8
        )
        self._preview_frame.grid(row=0, column=1, sticky="nsew")
        self._preview_frame.grid_remove()

        self._preview_label = ttk.Label(self._preview_frame, text="")
        self._preview_label.pack(fill=tk.BOTH, expand=True)

        ttk.Button(
            self._preview_frame,
            text="Print Label",
            bootstyle="primary",
            command=self._print_selected_label,
        ).pack(fill=tk.X, pady=(8, 0))

    def _build_bottom_bar(self) -> None:
        """Build the bottom bar with item count and bulk action buttons."""
        bottom = ttk.Frame(self._content_wrapper)
        bottom.grid(row=3, column=0, sticky=tk.EW, padx=12, pady=4)

        self._item_count_var = tk.StringVar(value="0 items")
        ttk.Label(bottom, textvariable=self._item_count_var).pack(side=tk.LEFT, padx=8)

        ttk.Button(
            bottom,
            text="Mark Selected SOLD",
            bootstyle="warning",
            command=self._bulk_mark_sold,
        ).pack(side=tk.RIGHT, padx=4)

        ttk.Button(
            bottom,
            text="Print Selected Labels",
            bootstyle="info-outline",
            command=self._bulk_print_labels,
        ).pack(side=tk.RIGHT, padx=4)

        ttk.Button(
            bottom,
            text="Toggle Preview",
            bootstyle="secondary-outline",
            command=self._toggle_preview,
        ).pack(side=tk.RIGHT, padx=4)

    def _build_context_menu(self) -> None:
        """Build the right-click context menu."""
        self._context_menu = tk.Menu(self, tearoff=0)
        self._context_menu.add_command(
            label="Add to Invoice", command=self._ctx_add_to_invoice
        )
        self._context_menu.add_command(label="Mark SOLD", command=self._ctx_mark_sold)
        self._context_menu.add_command(
            label="Print Label", command=self._ctx_print_label
        )
        self._context_menu.add_command(label="Edit", command=self._ctx_edit)
        self._context_menu.add_command(label="Copy IMEI", command=self._ctx_copy_imei)

    # -- filter panel toggle -------------------------------------------------

    def _toggle_filters(self) -> None:
        """Toggle the filter panel visibility."""
        if self._filter_panel.winfo_viewable():
            self._filter_panel.grid_remove()
            self._filter_toggle_btn.configure(text="▶ Filters")
        else:
            self._filter_panel.grid()
            self._filter_toggle_btn.configure(text="▼ Filters")

    # -- data loading --------------------------------------------------------

    def refresh_data(self) -> None:
        """Reload treeview from inventory DataFrame."""
        self._populate_supplier_combo()
        self._apply_filters()

    def _populate_supplier_combo(self) -> None:
        """Populate the supplier combobox from current inventory."""
        df = self.app["inventory"].get_inventory()
        if df.empty or "supplier" not in df.columns:
            self._supplier_combo.configure(values=[])
            return

        suppliers = sorted(df["supplier"].dropna().unique().tolist())
        self._supplier_combo.configure(values=["All"] + suppliers)
        self._supplier_var.set("All")

    def _populate_treeview(self, df: pd.DataFrame) -> None:
        """Fill the treeview from a filtered DataFrame."""
        # Clear existing
        for item in self._tree.get_children():
            self._tree.delete(item)

        self._checked_ids.clear()
        self._selection_anchor = None

        if df.empty:
            self._item_count_var.set("0 items")
            return

        today = datetime.datetime.now()
        for _, row in df.iterrows():
            uid = int(row.get(FIELD_UNIQUE_ID, 0))
            status = str(row.get(FIELD_STATUS, STATUS_IN))
            date_added = row.get("date_added")

            # Aging tag
            tag = ""
            if pd.notna(date_added):
                try:
                    added = (
                        date_added
                        if isinstance(date_added, datetime.datetime)
                        else datetime.datetime.fromisoformat(str(date_added))
                    )
                    age_days = (today - added).days
                    if age_days > 60:
                        tag = "aged_red"
                    elif age_days > 30:
                        tag = "aged_yellow"
                except (ValueError, TypeError):
                    pass

            check_char = "☑" if uid in self._checked_ids else "☐"

            price = row.get(FIELD_PRICE, 0)
            try:
                price_str = f"₹{float(price):,.0f}"
            except (ValueError, TypeError):
                price_str = "₹0"

            self._tree.insert(
                "",
                tk.END,
                iid=str(uid),
                values=(
                    check_char,
                    uid,
                    str(row.get(FIELD_IMEI, "")),
                    str(row.get(FIELD_MODEL, "")),
                    str(row.get(FIELD_RAM_ROM, "")),
                    price_str,
                    str(row.get("supplier", "")),
                    status,
                ),
                tags=(tag,) if tag else (),
            )

        self._tree.tag_configure("aged_yellow", background="#fff3cd")
        self._tree.tag_configure("aged_red", background="#f8d7da")

        self._item_count_var.set(f"{len(df)} items")

    # -- filtering -----------------------------------------------------------

    def _apply_filters(self) -> None:
        """Apply all active filters and repopulate the treeview."""
        df = self.app["inventory"].get_inventory()
        if df.empty:
            self._populate_treeview(df)
            return

        filtered = df.copy()

        # Search filter: model / IMEI / ID
        search_text = self._search_var.get().strip().lower()
        if search_text:
            mask = pd.Series(False, index=filtered.index)
            if FIELD_MODEL in filtered.columns:
                mask |= (
                    filtered[FIELD_MODEL]
                    .str.lower()
                    .str.contains(search_text, na=False)
                )
            if FIELD_IMEI in filtered.columns:
                mask |= (
                    filtered[FIELD_IMEI].str.lower().str.contains(search_text, na=False)
                )
            mask |= (
                filtered[FIELD_UNIQUE_ID]
                .astype(str)
                .str.contains(search_text, na=False)
            )
            filtered = filtered[mask]

        # Supplier filter
        supplier = self._supplier_var.get()
        if supplier and supplier != "All":
            if "supplier" in filtered.columns:
                filtered = filtered[filtered["supplier"] == supplier]

        # Status filter
        status = self._status_var.get()
        if status and status != "All":
            if FIELD_STATUS in filtered.columns:
                filtered = filtered[filtered[FIELD_STATUS] == status]

        # Date range filter
        date_from = self._date_from_var.get().strip()
        date_to = self._date_to_var.get().strip()

        if "date_added" in filtered.columns:
            if date_from:
                try:
                    from_dt = datetime.datetime.strptime(date_from, "%Y-%m-%d")
                    filtered = filtered[filtered["date_added"] >= from_dt]
                except ValueError:
                    pass
            if date_to:
                try:
                    to_dt = datetime.datetime.strptime(date_to, "%Y-%m-%d")
                    to_dt = to_dt.replace(hour=23, minute=59, second=59)
                    filtered = filtered[filtered["date_added"] <= to_dt]
                except ValueError:
                    pass

        self._populate_treeview(filtered)

    def _clear_filters(self) -> None:
        """Clear all filter fields and repopulate treeview."""
        self._search_var.set("")
        self._supplier_var.set("All")
        self._status_var.set("All")
        self._date_from_var.set("")
        self._date_to_var.set("")
        self._apply_filters()

    def _on_search_change(self, *args: Any) -> None:
        """Debounced search filtering on search entry change."""
        if self._search_after_id is not None:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(250, self._apply_filters)

    # -- selection & preview -------------------------------------------------

    def _on_double_click(self, event: tk.Event) -> None:
        """Open the selected item for editing."""
        selection = self._tree.selection()
        if not selection:
            return

        item_id = selection[0]
        self._open_edit(item_id)

    def _on_select(self, event: tk.Event) -> None:
        """Update label preview for the selected item."""
        selection = self._tree.selection()
        if not selection:
            self._preview_label.configure(text="")
            return

        # Reset anchor on fresh single-item selection
        if len(selection) == 1:
            self._selection_anchor = selection[0]

        if not self._preview_visible:
            return

        item_id = selection[0]
        item = self._get_item_by_id(item_id)
        if item is None:
            self._preview_label.configure(text="Item not found")
            return

        model = item.get(FIELD_MODEL, "Unknown")
        imei = item.get(FIELD_IMEI, "N/A")
        price = item.get(FIELD_PRICE, 0)
        uid = item.get(FIELD_UNIQUE_ID, "N/A")

        preview_text = f"ID: {uid}\nModel: {model}\nIMEI: {imei}\nPrice: ₹{price:,.0f}"
        self._preview_label.configure(text=preview_text)

    def _toggle_preview(self) -> None:
        """Show or hide the label preview panel."""
        self._preview_visible = not self._preview_visible
        if self._preview_visible:
            self._preview_frame.grid()
        else:
            self._preview_frame.grid_remove()

    def _get_item_by_id(self, item_id: str) -> dict[str, Any] | None:
        """Look up an item dict from the inventory by its unique_id string."""
        try:
            uid = int(item_id)
        except (ValueError, TypeError):
            return None

        item, _ = self.app["inventory"].get_item_by_id(uid)
        return item

    # -- checkbox / multi-select ---------------------------------------------

    def _toggle_check(self, event: tk.Event) -> str | None:
        """Toggle the checkbox for the focused/selected item."""
        selection = self._tree.selection()
        if not selection:
            return None

        for iid in selection:
            try:
                uid = int(iid)
            except (ValueError, TypeError):
                continue

            if uid in self._checked_ids:
                self._checked_ids.discard(uid)
                self._tree.set(iid, "check", "☐")
            else:
                self._checked_ids.add(uid)
                self._tree.set(iid, "check", "☑")

        return "break"

    def _on_tree_click(self, event: tk.Event) -> None:
        """Handle clicks on the check column to toggle checkboxes."""
        region = self._tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self._tree.identify_column(event.x)
        col_index = int(col.replace("#", ""))
        if col_index != 1:
            return
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        try:
            uid = int(iid)
        except (ValueError, TypeError):
            return
        if uid in self._checked_ids:
            self._checked_ids.discard(uid)
            self._tree.set(iid, "check", "☐")
        else:
            self._checked_ids.add(uid)
            self._tree.set(iid, "check", "☑")

    def _select_all(self, event: tk.Event) -> str | None:
        """Select all items and check them."""
        all_items = self._tree.get_children()
        if not all_items:
            return None

        self._tree.selection_set(all_items)
        for iid in all_items:
            try:
                uid = int(iid)
            except (ValueError, TypeError):
                continue
            self._checked_ids.add(uid)
            self._tree.set(iid, "check", "☑")

        return "break"

    def _extend_selection_up(self, event: tk.Event) -> str | None:
        """Extend selection upward using anchor-based range."""
        all_items = list(self._tree.get_children())
        if not all_items:
            return None

        selection = self._tree.selection()
        if not selection:
            return None

        old_selection = set(selection)

        # Set anchor on first selection
        if self._selection_anchor is None:
            self._selection_anchor = selection[-1]

        anchor_idx = all_items.index(self._selection_anchor)
        current_top = all_items.index(selection[0])
        new_top = max(0, current_top - 1)
        if new_top >= anchor_idx:
            new_items = all_items[anchor_idx : new_top + 1]
        else:
            new_items = all_items[new_top : anchor_idx + 1]

        self._tree.selection_set(new_items)
        new_selection = set(new_items)

        # Check newly selected items
        for iid in new_selection - old_selection:
            try:
                uid = int(iid)
            except (ValueError, TypeError):
                continue
            self._checked_ids.add(uid)
            self._tree.set(iid, "check", "☑")

        # Uncheck items no longer selected
        for iid in old_selection - new_selection:
            try:
                uid = int(iid)
            except (ValueError, TypeError):
                continue
            self._checked_ids.discard(uid)
            self._tree.set(iid, "check", "☐")

        return "break"

    def _extend_selection_down(self, event: tk.Event) -> str | None:
        """Extend selection downward using anchor-based range."""
        all_items = list(self._tree.get_children())
        if not all_items:
            return None

        selection = self._tree.selection()
        if not selection:
            return None

        old_selection = set(selection)

        # Set anchor on first selection
        if self._selection_anchor is None:
            self._selection_anchor = selection[0]

        anchor_idx = all_items.index(self._selection_anchor)
        current_bottom = all_items.index(selection[-1])
        new_bottom = min(len(all_items) - 1, current_bottom + 1)
        if new_bottom <= anchor_idx:
            new_items = all_items[new_bottom : anchor_idx + 1]
        else:
            new_items = all_items[anchor_idx : new_bottom + 1]

        self._tree.selection_set(new_items)
        new_selection = set(new_items)

        # Check newly selected items
        for iid in new_selection - old_selection:
            try:
                uid = int(iid)
            except (ValueError, TypeError):
                continue
            self._checked_ids.add(uid)
            self._tree.set(iid, "check", "☑")

        # Uncheck items no longer selected
        for iid in old_selection - new_selection:
            try:
                uid = int(iid)
            except (ValueError, TypeError):
                continue
            self._checked_ids.discard(uid)
            self._tree.set(iid, "check", "☐")

        return "break"

    # -- context menu --------------------------------------------------------

    def _on_context_menu(self, event: tk.Event) -> None:
        """Show context menu on right-click."""
        item = self._tree.identify_row(event.y)
        if item:
            self._tree.selection_set(item)
            self._tree.focus(item)
            self._context_menu.tk_popup(event.x_root, event.y_root)

    def _ctx_add_to_invoice(self) -> None:
        """Add selected item to invoice via billing screen."""
        selection = self._tree.selection()
        if not selection:
            return

        items = [
            item for iid in selection if (item := self._get_item_by_id(iid)) is not None
        ]
        if items:
            self._add_to_invoice(items)

    def _ctx_mark_sold(self) -> None:
        """Mark selected item as SOLD."""
        selection = self._tree.selection()
        if not selection:
            return

        for iid in selection:
            self._mark_item_sold(iid)

    def _ctx_print_label(self) -> None:
        """Print label for selected item."""
        selection = self._tree.selection()
        if not selection:
            return

        items = [
            item for iid in selection if (item := self._get_item_by_id(iid)) is not None
        ]
        if items:
            self._print_labels_for_items(items)

    def _ctx_edit(self) -> None:
        """Open edit screen for selected item."""
        selection = self._tree.selection()
        if not selection:
            return

        item_id = selection[0]
        self._open_edit(item_id)

    def _ctx_copy_imei(self) -> None:
        """Copy IMEI of selected item to clipboard."""
        selection = self._tree.selection()
        if not selection:
            return

        item_id = selection[0]
        self._copy_imei(item_id)

    # -- bulk operations -----------------------------------------------------

    def _bulk_mark_sold(self) -> None:
        """Dialog for buyer info, then bulk status update for checked items."""
        checked = list(self._checked_ids)
        if not checked:
            selection = self._tree.selection()
            if not selection:
                self.app["app"].show_toast(
                    "No Selection", "Select or check items first.", "warning"
                )
                return
            checked = [int(iid) for iid in selection]

        dialog = _BulkSoldDialog(self, checked)
        self.wait_window(dialog)

        if not dialog.confirmed:
            return

        buyer = dialog.buyer_name
        contact = dialog.buyer_contact
        count = 0

        for uid in checked:
            success = self.app["inventory"].update_item_status(uid, STATUS_OUT)
            if success:
                # Update buyer info
                self.app["inventory"].update_item_data(
                    uid,
                    {
                        "buyer": buyer,
                        "buyer_contact": contact,
                    },
                )
                count += 1

        self.app["app"].show_toast(
            "Items Sold",
            f"{count} item(s) marked as SOLD.",
            "success",
        )
        self.refresh_data()

    def _bulk_print_labels(self) -> None:
        """Show ZPLPreviewDialog for checked items, then print."""
        checked = list(self._checked_ids)
        if not checked:
            selection = self._tree.selection()
            if not selection:
                self.app["app"].show_toast(
                    "No Selection", "Select or check items first.", "warning"
                )
                return
            checked = [int(iid) for iid in selection]

        items = [
            item
            for uid in checked
            if (item := self._get_item_by_id(str(uid))) is not None
        ]
        if not items:
            self.app["app"].show_toast(
                "No Items", "Could not find selected items.", "warning"
            )
            return

        self._print_labels_for_items(items)

    def _print_labels_for_items(self, items: list[dict[str, Any]]) -> None:
        """Show preview dialog then send to printer."""

        def on_confirm(all_items: list[dict[str, Any]]) -> None:
            printers = (
                self.app["printer"].list_printers() if self.app.get("printer") else []
            )
            if not printers:
                # Print with default
                self.app["app"].show_toast(
                    "Print Labels",
                    f"Sending {len(all_items)} label(s) to default printer.",
                    "info",
                )
                return

            PrinterSelectionDialog(
                self,
                printer_list=printers,
                on_select=lambda p: self._send_labels_to_printer(all_items, p),
            )

        ZPLPreviewDialog(self, items=items, on_confirm=on_confirm)

    def _send_labels_to_printer(
        self, items: list[dict[str, Any]], printer: str
    ) -> None:
        """Send label data to the selected printer."""
        barcode_gen = self.app.get("barcode")
        if barcode_gen is None:
            self.app["app"].show_toast(
                "Error", "Barcode generator not available.", "danger"
            )
            return

        count = 0
        for item in items:
            uid = item.get(FIELD_UNIQUE_ID, "")
            try:
                barcode_gen.generate_label(item, printer=printer)
                count += 1
            except Exception:
                pass

        self.app["app"].show_toast(
            "Labels Printed",
            f"{count} label(s) sent to {printer}.",
            "success",
        )

    def _print_selected_label(self) -> None:
        """Print label for the currently previewed item."""
        selection = self._tree.selection()
        if not selection:
            return

        item = self._get_item_by_id(selection[0])
        if item is None:
            return

        self._print_labels_for_items([item])

    # -- individual operations -----------------------------------------------

    def _copy_imei(self, item_id: str) -> None:
        """Copy IMEI of the given item to the clipboard."""
        item = self._get_item_by_id(item_id)
        if item is None:
            return

        imei = str(item.get(FIELD_IMEI, ""))
        if not imei:
            self.app["app"].show_toast("No IMEI", "This item has no IMEI.", "warning")
            return

        self.clipboard_clear()
        self.clipboard_append(imei)
        self.app["app"].show_toast("Copied", f"IMEI copied to clipboard.", "info")

    def _open_edit(self, item_id: str) -> None:
        """Switch to edit screen with the given item pre-loaded."""
        item = self._get_item_by_id(item_id)
        if item is None:
            return

        # Store item in app context for the edit screen to pick up
        self.app["app"]._edit_item = item
        self.app["app"].show_screen("edit")

    def _add_to_invoice(self, items: list[dict[str, Any]]) -> None:
        """Switch to billing screen with the given items."""
        if not items:
            return

        self.app["app"].switch_to_billing(items)

    def _mark_item_sold(self, item_id: str) -> None:
        """Mark a single item as SOLD."""
        try:
            uid = int(item_id)
        except (ValueError, TypeError):
            return

        success = self.app["inventory"].update_item_status(uid, STATUS_OUT)
        if success:
            self.app["app"].show_toast(
                "Item Sold",
                f"Item {uid} marked as SOLD.",
                "success",
            )
            self.refresh_data()

    # -- lifecycle -----------------------------------------------------------

    def focus_primary(self) -> None:
        """Focus the search entry."""
        self._search_entry.focus_set()

    def on_show(self) -> None:
        """Called when this screen becomes visible."""
        self.refresh_data()


# ---------------------------------------------------------------------------
# _BulkSoldDialog — helper dialog for bulk mark-sold
# ---------------------------------------------------------------------------


class _BulkSoldDialog(tb.Toplevel):
    """Dialog to collect buyer info before bulk marking items as sold.

    Parameters
    ----------
    parent:
        Parent window.
    item_ids:
        List of unique IDs to be marked sold.
    """

    def __init__(self, parent: tk.Misc, item_ids: list[int]) -> None:
        super().__init__(parent)
        self.confirmed = False
        self.buyer_name = ""
        self.buyer_contact = ""

        self.title(f"Mark {len(item_ids)} Item(s) as SOLD")
        self.transient(parent)
        self.grab_set()
        self.geometry("350x200")
        self.resizable(False, False)

        self._build_ui()

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="Buyer Name:").pack(anchor=tk.W, pady=(0, 4))
        self._buyer_var = tk.StringVar()
        ttk.Entry(main, textvariable=self._buyer_var).pack(fill=tk.X, pady=(0, 8))

        ttk.Label(main, text="Contact:").pack(anchor=tk.W, pady=(0, 4))
        self._contact_var = tk.StringVar()
        ttk.Entry(main, textvariable=self._contact_var).pack(fill=tk.X, pady=(0, 12))

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)

        ttk.Button(
            btn_frame, text="Confirm SOLD", bootstyle="warning", command=self._confirm
        ).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _confirm(self) -> None:
        """Collect data and close."""
        self.buyer_name = self._buyer_var.get().strip()
        self.buyer_contact = self._contact_var.get().strip()
        self.confirmed = True
        self.destroy()
