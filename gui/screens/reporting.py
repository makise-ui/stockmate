"""Advanced reporting screen with filter/query builder and export.

Provides the ``ReportingScreen`` class which integrates the
``AdvancedFilterPanel`` and ``SamplingPanel`` widgets for building
complex inventory queries.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import ttk
from typing import Any

import pandas as pd
import ttkbootstrap as tb
from ttkbootstrap.dialogs import Messagebox

from core.reporting import ReportGenerator
from gui.base import BaseScreen
from gui.screens.reporting_widgets import AdvancedFilterPanel, SamplingPanel


# ---------------------------------------------------------------------------
# ReportingScreen
# ---------------------------------------------------------------------------

_LAST_FILTERS_FILE = "last_filters.json"
_AVAILABLE_COLUMNS = [
    "unique_id",
    "imei",
    "brand",
    "model",
    "ram_rom",
    "price",
    "price_original",
    "supplier",
    "source_file",
    "status",
    "color",
    "buyer",
    "buyer_contact",
    "grade",
    "condition",
    "notes",
    "date_added",
    "date_sold",
    "last_updated",
]


class ReportingScreen(BaseScreen):
    """Advanced reporting screen with filter builder, column selection, and export."""

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)

        self._filter_panel: AdvancedFilterPanel | None = None
        self._sampling_panel: SamplingPanel | None = None
        self._tree: ttk.Treeview | None = None
        self._available_lb: tk.Listbox | None = None
        self._selected_lb: tk.Listbox | None = None
        self._selected_columns: list[str] = list(_AVAILABLE_COLUMNS)

        self._build_ui()

    # -- layout --------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the reporting interface."""
        self.add_header("Advanced Reporting")

        # Main split: left (filters) / right (columns + sampling)
        main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 8))

        # Left panel: filter builder
        left_frame = ttk.LabelFrame(main_paned, text="Filters", padding=8)
        main_paned.add(left_frame, weight=3)

        config = self.app.get("config")
        config_dir = str(config.get_config_dir()) if config else None

        self._filter_panel = AdvancedFilterPanel(
            left_frame,
            fields=list(_AVAILABLE_COLUMNS),
            config_dir=config_dir,
        )
        self._filter_panel.pack(fill=tk.BOTH, expand=True)

        # Right panel: column selection + sampling
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=2)

        self._build_column_selection(right_frame)
        self._build_sampling_panel(right_frame)

        # Bottom: actions + preview tree
        bottom_frame = ttk.Frame(self)
        bottom_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

        self._build_action_buttons(bottom_frame)
        self._build_preview_tree(bottom_frame)

    def _build_column_selection(self, parent: ttk.Frame) -> None:
        """Build the dual-listbox column selector."""
        col_frame = ttk.LabelFrame(parent, text="Columns", padding=8)
        col_frame.pack(fill=tk.X, pady=(0, 8))

        inner = ttk.Frame(col_frame)
        inner.pack(fill=tk.X)

        # Available columns
        ttk.Label(inner, text="Available").pack(anchor=tk.W)
        self._available_lb = tk.Listbox(inner, selectmode=tk.SINGLE, height=6, width=18)
        self._available_lb.pack(side=tk.LEFT, padx=(0, 4))
        for col in _AVAILABLE_COLUMNS:
            self._available_lb.insert(tk.END, col)

        # Move buttons
        btn_col = ttk.Frame(inner)
        btn_col.pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btn_col, text="→", width=3, bootstyle="info", command=self._add_column
        ).pack(pady=2)
        ttk.Button(
            btn_col, text="←", width=3, bootstyle="info", command=self._remove_column
        ).pack(pady=2)

        # Selected columns
        ttk.Label(inner, text="Selected").pack(anchor=tk.W)
        self._selected_lb = tk.Listbox(inner, selectmode=tk.SINGLE, height=6, width=18)
        self._selected_lb.pack(side=tk.LEFT, padx=(4, 0))
        self._refresh_selected_listbox()

    def _build_sampling_panel(self, parent: ttk.Frame) -> None:
        """Build the sampling controls."""
        self._sampling_panel = SamplingPanel(parent)
        self._sampling_panel.pack(fill=tk.X, pady=(0, 4))

    def _build_action_buttons(self, parent: ttk.Frame) -> None:
        """Build preview and export action buttons."""
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(
            btn_frame,
            text="Preview",
            bootstyle="primary",
            command=self._apply_filters,
        ).pack(side=tk.LEFT, padx=4)

        export_menu = tk.Menu(btn_frame, tearoff=False)
        export_menu.add_command(
            label="Export to Excel", command=lambda: self._export("excel")
        )
        export_menu.add_command(
            label="Export to PDF", command=lambda: self._export("pdf")
        )
        export_menu.add_command(
            label="Export to Word", command=lambda: self._export("word")
        )

        export_btn = ttk.Menubutton(btn_frame, text="Export ▼", bootstyle="success")
        export_btn.configure(menu=export_menu)
        export_btn.pack(side=tk.LEFT, padx=4)

        ttk.Button(
            btn_frame,
            text="Clear Filters",
            bootstyle="secondary-outline",
            command=self._clear_filters,
        ).pack(side=tk.RIGHT, padx=4)

    def _build_preview_tree(self, parent: ttk.Frame) -> None:
        """Build the preview Treeview."""
        tree_frame = ttk.LabelFrame(parent, text="Preview", padding=4)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self._tree = ttk.Treeview(tree_frame, show="headings")
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

    # -- column selection ----------------------------------------------------

    def _add_column(self) -> None:
        """Move selected column from available to selected."""
        if self._available_lb is None:
            return
        sel = self._available_lb.curselection()
        if not sel:
            return
        col = self._available_lb.get(sel[0])
        if col not in self._selected_columns:
            self._selected_columns.append(col)
            self._refresh_selected_listbox()

    def _remove_column(self) -> None:
        """Move selected column from selected back to available."""
        if self._selected_lb is None:
            return
        sel = self._selected_lb.curselection()
        if not sel:
            return
        col = self._selected_lb.get(sel[0])
        if col in self._selected_columns:
            self._selected_columns.remove(col)
            self._refresh_selected_listbox()

    def _refresh_selected_listbox(self) -> None:
        """Rebuild the selected columns listbox."""
        if self._selected_lb is None:
            return
        self._selected_lb.delete(0, tk.END)
        for col in self._selected_columns:
            self._selected_lb.insert(tk.END, col)

    # -- filter operations ---------------------------------------------------

    def _apply_filters(self) -> None:
        """Apply current filters and sampling, show preview."""
        inventory = self.app.get("inventory")
        if inventory is None:
            self.app["app"].show_toast(
                "No Inventory", "Load inventory first.", "warning"
            )
            return

        df = getattr(inventory, "inventory_df", pd.DataFrame())
        if df.empty:
            self.app["app"].show_toast(
                "Empty Inventory", "No data to filter.", "warning"
            )
            return

        reporting: ReportGenerator | None = self.app.get("reporting")
        if reporting is None:
            return

        # Apply filter conditions
        conditions = self._filter_panel.get_conditions() if self._filter_panel else []
        if conditions:
            df = reporting.apply_filters(df, conditions)

        # Apply custom expression
        if self._sampling_panel is not None:
            expr = self._sampling_panel.get_expression()
            if expr:
                try:
                    df = reporting.apply_custom_expression(df, expr)
                except ValueError as exc:
                    self.app["app"].show_toast("Expression Error", str(exc), "danger")
                    return

            # Apply limit and modulo
            limit = self._sampling_panel.get_limit()
            modulo = self._sampling_panel.get_modulo()
            df = reporting.apply_limit(df, limit=limit, modulo=modulo)

        # Select columns
        cols = [c for c in self._selected_columns if c in df.columns]
        if cols:
            df = df[cols].copy()

        # Persist last filters
        self._persist_last_filters(conditions)

        # Populate treeview
        self._populate_tree(df)

        count = len(df)
        self.app["app"].show_toast("Preview Ready", f"{count} row(s) matched.", "info")

    def _export(self, fmt: str) -> None:
        """Export current filtered results to the chosen format."""
        inventory = self.app.get("inventory")
        if inventory is None:
            self.app["app"].show_toast(
                "No Inventory", "Load inventory first.", "warning"
            )
            return

        df = getattr(inventory, "inventory_df", pd.DataFrame())
        if df.empty:
            self.app["app"].show_toast(
                "Empty Inventory", "No data to export.", "warning"
            )
            return

        reporting: ReportGenerator | None = self.app.get("reporting")
        if reporting is None:
            return

        # Re-apply filters to get current result set
        conditions = self._filter_panel.get_conditions() if self._filter_panel else []
        if conditions:
            df = reporting.apply_filters(df, conditions)

        if self._sampling_panel is not None:
            expr = self._sampling_panel.get_expression()
            if expr:
                try:
                    df = reporting.apply_custom_expression(df, expr)
                except ValueError as exc:
                    self.app["app"].show_toast("Expression Error", str(exc), "danger")
                    return
            limit = self._sampling_panel.get_limit()
            modulo = self._sampling_panel.get_modulo()
            df = reporting.apply_limit(df, limit=limit, modulo=modulo)

        cols = [c for c in self._selected_columns if c in df.columns]
        if cols:
            df = df[cols].copy()

        # File dialog
        ext_map = {"excel": ".xlsx", "pdf": ".pdf", "word": ".docx"}
        ext = ext_map.get(fmt, ".xlsx")
        file_path = filedialog.asksaveasfilename(
            title=f"Export as {fmt.upper()}",
            defaultextension=ext,
            filetypes=[(f"{fmt.upper()} Files", f"*{ext}")],
        )
        if not file_path:
            return

        success = reporting.export(df, fmt, file_path)
        if success:
            self.app["app"].show_toast(
                "Export Complete", f"Saved to {os.path.basename(file_path)}", "success"
            )
        else:
            self.app["app"].show_toast(
                "Export Failed", "Could not write file.", "danger"
            )

    def _clear_filters(self) -> None:
        """Reset all filter conditions and clear the preview."""
        if self._filter_panel is not None:
            self._filter_panel._load_conditions([])
        if self._sampling_panel is not None:
            self._sampling_panel.limit_var.set("")
            self._sampling_panel.modulo_var.set("")
            self._sampling_panel.expression_var.set("")
        if self._tree is not None:
            for col in self._tree["columns"]:
                self._tree.heading(col, text="")
            self._tree["columns"] = ()
            for item in self._tree.get_children():
                self._tree.delete(item)

    # -- preset management ---------------------------------------------------

    def _save_preset(self) -> None:
        """Delegate to the filter panel's save preset."""
        if self._filter_panel is not None:
            self._filter_panel._save_preset()

    def _load_preset(self) -> None:
        """Delegate to the filter panel's load preset."""
        if self._filter_panel is not None:
            self._filter_panel._on_preset_select()

    # -- treeview helpers ----------------------------------------------------

    def _populate_tree(self, df: pd.DataFrame) -> None:
        """Populate the preview Treeview with DataFrame data."""
        if self._tree is None:
            return

        # Clear existing
        for item in self._tree.get_children():
            self._tree.delete(item)

        if df.empty:
            self._tree["columns"] = ()
            return

        columns = list(df.columns)
        self._tree["columns"] = columns

        for col in columns:
            header = col.replace("_", " ").title()
            self._tree.heading(col, text=header)
            self._tree.column(col, width=120, minwidth=60)

        # Insert data (cap at 500 rows for preview performance)
        preview_df = df.head(500)
        for _, row in preview_df.iterrows():
            values = [str(v) for v in row.values]
            self._tree.insert("", tk.END, values=values)

    # -- filter persistence --------------------------------------------------

    def _persist_last_filters(self, conditions: list[dict[str, Any]]) -> None:
        """Save the current filter conditions to disk."""
        config = self.app.get("config")
        if config is None:
            return

        config_dir = config.get_config_dir()
        path = Path(config_dir) / _LAST_FILTERS_FILE
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(conditions, f, indent=2)
        except OSError:
            pass

    def _load_last_filters(self) -> list[dict[str, Any]]:
        """Load the last used filter conditions from disk."""
        config = self.app.get("config")
        if config is None:
            return []

        config_dir = config.get_config_dir()
        path = Path(config_dir) / _LAST_FILTERS_FILE
        if not path.exists():
            return []

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
        return []

    # -- field options -------------------------------------------------------

    def _update_field_options(self) -> None:
        """Update filter panel field options from current inventory columns."""
        inventory = self.app.get("inventory")
        if inventory is None or self._filter_panel is None:
            return

        df = getattr(inventory, "inventory_df", pd.DataFrame())
        if df.empty:
            return

        columns = list(df.columns)
        self._filter_panel.update_fields(columns)

    # -- lifecycle -----------------------------------------------------------

    def on_show(self) -> None:
        """Load inventory columns and restore last filters."""
        self._update_field_options()
        last_filters = self._load_last_filters()
        if last_filters and self._filter_panel is not None:
            self._filter_panel._load_conditions(last_filters)

    def focus_primary(self) -> None:
        """No primary focus target for reporting screen."""
