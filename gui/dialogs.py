"""Dialog windows for StockMate."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
from typing import Any, Callable

import pandas as pd
import ttkbootstrap as tb
from PIL import Image, ImageDraw, ImageFont

from core.constants import FIELD_IMEI, FIELD_MODEL, FIELD_PRICE, FIELD_UNIQUE_ID


# ---------------------------------------------------------------------------
# MapColumnsDialog
# ---------------------------------------------------------------------------


class MapColumnsDialog(tk.Toplevel):
    """Excel column mapping dialog.

    Loads an Excel file and lets the user map its columns to canonical
    field names.  Supports multi-sheet files, auto-suggest, and data
    preview.

    Parameters
    ----------
    parent:
        Parent window.
    file_path:
        Path to the Excel file.
    on_save_callback:
        Called with ``(key, save_data)`` when the user saves.
    current_mapping:
        Existing mapping to pre-populate, if any.
    """

    CANONICAL_FIELDS = [
        "imei",
        "model",
        "ram_rom",
        "price",
        "supplier",
        "notes",
        "status",
        "color",
        "buyer",
        "buyer_contact",
        "grade",
        "condition",
    ]

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        file_path: str,
        on_save_callback: Callable[[str, dict], None],
        current_mapping: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_path = file_path
        self._on_save = on_save_callback
        self._current_mapping = current_mapping or {}
        self._df: pd.DataFrame | None = None
        self._sheet_var = tk.StringVar()
        self._comboboxes: dict[str, ttk.Combobox] = {}

        self.title("Map Excel Columns")
        self.transient(parent)
        self.grab_set()
        self.geometry("700x600")
        self.minsize(600, 500)

        self._load_excel()
        self._build_ui()

    # -- loading -------------------------------------------------------------

    def _load_excel(self) -> None:
        """Load the Excel file and detect sheets."""
        try:
            xls = pd.ExcelFile(self._file_path)
            if len(xls.sheet_names) > 1:
                self._sheet_names = xls.sheet_names
            else:
                self._sheet_names = [0]

            sheet = self._sheet_names[0]
            self._df = pd.read_excel(self._file_path, sheet_name=sheet)
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to load file:\n{exc}")
            self.destroy()

    # -- UI ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build the mapping dialog UI."""
        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # Sheet selector
        sheet_frame = ttk.Frame(main)
        sheet_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(sheet_frame, text="Sheet:").pack(side=tk.LEFT)
        self._sheet_var.set(str(self._sheet_names[0]))
        cb = ttk.Combobox(
            sheet_frame,
            textvariable=self._sheet_var,
            values=[str(s) for s in self._sheet_names],
            state="readonly",
            width=30,
        )
        cb.pack(side=tk.LEFT, padx=8)
        cb.bind("<<ComboboxSelected>>", self._on_sheet_change)

        # Mapping frame
        map_frame = ttk.LabelFrame(main, text="Column Mapping", padding=8)
        map_frame.pack(fill=tk.BOTH, expand=True, pady=8)

        canvas = tk.Canvas(map_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(map_frame, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)

        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._build_mapping_rows(inner)

        # Supplier override
        sup_frame = ttk.Frame(main)
        sup_frame.pack(fill=tk.X, pady=4)
        ttk.Label(sup_frame, text="Supplier override:").pack(side=tk.LEFT)
        self._supplier_var = tk.StringVar(
            value=self._current_mapping.get("supplier", "")
        )
        sup_entry = ttk.Entry(sup_frame, textvariable=self._supplier_var, width=30)
        sup_entry.pack(side=tk.LEFT, padx=8)

        # Preview button
        preview_btn = ttk.Button(main, text="Preview Data", command=self._show_preview)
        preview_btn.pack(anchor=tk.W, pady=4)

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _build_mapping_rows(self, parent: ttk.Frame) -> None:
        """Build one row per canonical field."""
        if self._df is None:
            return

        excel_cols = list(self._df.columns)
        existing = self._current_mapping.get("mapping", {})

        for row_idx, field in enumerate(self.CANONICAL_FIELDS):
            ttk.Label(parent, text=field.replace("_", " ").title(), width=16).grid(
                row=row_idx, column=0, sticky=tk.W, pady=2
            )

            cb = ttk.Combobox(
                parent, values=[""] + excel_cols, width=30, state="readonly"
            )
            # Auto-suggest
            suggested = self._suggest_column(field, excel_cols)
            existing_col = existing.get(field, "")
            cb.set(existing_col if existing_col else suggested)
            cb.grid(row=row_idx, column=1, sticky=tk.EW, padx=8, pady=2)
            self._comboboxes[field] = cb

        parent.grid_columnconfigure(1, weight=1)

    @staticmethod
    def _suggest_column(field: str, excel_cols: list[str]) -> str:
        """Return the best-matching Excel column for *field*."""
        field_lower = field.lower()
        for col in excel_cols:
            if col.lower().replace(" ", "_") == field_lower:
                return col
        for col in excel_cols:
            if field_lower in col.lower().replace(" ", "_"):
                return col
        return ""

    def _on_sheet_change(self, event: tk.Event) -> None:
        """Reload data when sheet selection changes."""
        sheet = self._sheet_var.get()
        try:
            self._df = pd.read_excel(self._file_path, sheet_name=sheet)
        except Exception:
            return

    def _show_preview(self) -> None:
        """Show a Treeview with the first 5 rows."""
        if self._df is None:
            return

        preview = tk.Toplevel(self)
        preview.title("Data Preview")
        preview.transient(self)
        preview.geometry("600x300")

        tree = ttk.Treeview(preview, show="headings")
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        for col in self._df.columns:
            tree.heading(col, text=col)
            tree.column(col, width=100)

        for _, row in self._df.head(5).iterrows():
            tree.insert("", tk.END, values=list(row))

    def _save(self) -> None:
        """Collect mapping and fire callback."""
        if self._df is None:
            return

        mapping = {}
        for field, cb in self._comboboxes.items():
            val = cb.get()
            if val:
                mapping[field] = val

        sheet = self._sheet_var.get() or 0
        save_data = {
            "file_path": self._file_path,
            "mapping": mapping,
            "sheet_name": sheet,
            "supplier": self._supplier_var.get(),
        }

        key = self._file_path
        if len(self._sheet_names) > 1 and sheet:
            key = f"{self._file_path}::{sheet}"

        self._on_save(key, save_data)
        self.destroy()


# ---------------------------------------------------------------------------
# SettingsDialog
# ---------------------------------------------------------------------------


class SettingsDialog(tb.Toplevel):
    """Tabbed settings dialog.

    Parameters
    ----------
    parent:
        Parent window.
    config_manager:
        Application config manager.
    """

    def __init__(self, parent: tk.Tk | tk.Toplevel, config_manager: Any) -> None:
        super().__init__(parent)
        self._config = config_manager

        self.title("Settings")
        self.transient(parent)
        self.grab_set()
        self.geometry("450x350")
        self.resizable(False, False)

        self._build_ui()

    def _build_ui(self) -> None:
        """Build tabbed settings UI."""
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # Tab 1: General
        tab_general = ttk.Frame(nb, padding=12)
        nb.add(tab_general, text="General")
        ttk.Label(tab_general, text="Store Name:").pack(anchor=tk.W, pady=(0, 4))
        self._store_name_var = tk.StringVar(
            value=self._config.get("store_name", "My Mobile Shop")
        )
        ttk.Entry(tab_general, textvariable=self._store_name_var).pack(
            fill=tk.X, pady=(0, 8)
        )

        # Tab 2: Printing
        tab_printing = ttk.Frame(nb, padding=12)
        nb.add(tab_printing, text="Printing")
        ttk.Label(tab_printing, text="Label Width (mm):").pack(anchor=tk.W, pady=(0, 4))
        self._label_w_var = tk.StringVar(
            value=str(self._config.get("label_width_mm", 50))
        )
        ttk.Entry(tab_printing, textvariable=self._label_w_var).pack(fill=tk.X)
        ttk.Label(tab_printing, text="Label Height (mm):").pack(
            anchor=tk.W, pady=(8, 4)
        )
        self._label_h_var = tk.StringVar(
            value=str(self._config.get("label_height_mm", 22))
        )
        ttk.Entry(tab_printing, textvariable=self._label_h_var).pack(fill=tk.X)

        # Tab 3: Appearance
        tab_appearance = ttk.Frame(nb, padding=12)
        nb.add(tab_appearance, text="Appearance")
        ttk.Label(tab_appearance, text="Theme:").pack(anchor=tk.W, pady=(0, 4))
        themes = tb.Style().theme_names()
        current = self._config.get("theme_name", "cosmo")
        self._theme_var = tk.StringVar(value=current)
        theme_cb = ttk.Combobox(
            tab_appearance,
            textvariable=self._theme_var,
            values=sorted(themes),
            state="readonly",
        )
        theme_cb.pack(fill=tk.X)
        theme_cb.bind("<<ComboboxSelected>>", self._on_theme_change)

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=(0, 12))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _on_theme_change(self, event: tk.Event) -> None:
        """Apply theme change live."""
        theme = self._theme_var.get()
        tb.Style().theme_use(theme)

    def _save(self) -> None:
        """Persist settings."""
        self._config.set("store_name", self._store_name_var.get())
        try:
            self._config.set("label_width_mm", int(self._label_w_var.get()))
        except ValueError:
            pass
        try:
            self._config.set("label_height_mm", int(self._label_h_var.get()))
        except ValueError:
            pass
        self._config.set("theme_name", self._theme_var.get())
        self.destroy()


# ---------------------------------------------------------------------------
# ZPLPreviewDialog
# ---------------------------------------------------------------------------


class ZPLPreviewDialog(tk.Toplevel):
    """2-up label print preview dialog.

    Parameters
    ----------
    parent:
        Parent window.
    items:
        List of item dicts to preview.
    on_confirm:
        Called with the full items list when PRINT ALL is clicked.
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        items: list[dict[str, Any]],
        on_confirm: Callable[[list[dict[str, Any]]], None],
    ) -> None:
        super().__init__(parent)
        self._items = items
        self._on_confirm = on_confirm
        self._page = 0
        self._pages = self._pair_items()

        self.title("Label Preview")
        self.transient(parent)
        self.grab_set()
        self.geometry("700x500")

        self._build_ui()
        self._show_page()

    def _pair_items(self) -> list[list[dict[str, Any]]]:
        """Group items into pairs (2 per page)."""
        pages: list[list[dict[str, Any]]] = []
        for i in range(0, len(self._items), 2):
            pages.append(self._items[i : i + 2])
        return pages

    def _build_ui(self) -> None:
        """Build preview UI."""
        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # Canvas for label preview
        self._canvas = tk.Canvas(main, bg="#f0f0f0", width=660, height=320)
        self._canvas.pack(fill=tk.BOTH, expand=True, pady=8)

        # Navigation
        nav_frame = ttk.Frame(main)
        nav_frame.pack(fill=tk.X, pady=8)

        ttk.Button(nav_frame, text="Prev", command=self._prev_page).pack(side=tk.LEFT)
        self._page_label = ttk.Label(nav_frame, text="Page 1 / 1")
        self._page_label.pack(side=tk.LEFT, expand=True)
        ttk.Button(nav_frame, text="Next", command=self._next_page).pack(side=tk.RIGHT)

        # Print all button
        ttk.Button(
            main,
            text="PRINT ALL",
            bootstyle="success",
            command=self._print_all,
        ).pack(fill=tk.X, pady=(8, 0))

    def _show_page(self) -> None:
        """Render the current page of labels."""
        if not self._pages:
            return

        self._canvas.delete("all")
        page_items = self._pages[self._page]

        total_pages = len(self._pages)
        self._page_label.configure(text=f"Page {self._page + 1} / {total_pages}")

        # Draw simulated labels
        for i, item in enumerate(page_items):
            x_offset = i * 330
            self._draw_label(x_offset + 10, 10, item)

    def _draw_label(self, x: int, y: int, item: dict[str, Any]) -> None:
        """Draw a simulated label on the canvas."""
        w, h = 310, 140

        # Background
        self._canvas.create_rectangle(x, y, x + w, y + h, fill="white", outline="#ccc")

        # Store name
        self._canvas.create_text(
            x + w // 2,
            y + 16,
            text="Mobile Shop",
            font=("Arial", 10, "bold"),
        )

        # Model
        model = str(item.get("model", "Unknown"))
        self._canvas.create_text(x + w // 2, y + 36, text=model, font=("Arial", 9))

        # Price
        price = item.get("price", 0)
        self._canvas.create_text(
            x + w // 2,
            y + h - 20,
            text=f"\u20b9{price:,.0f}",
            font=("Arial", 14, "bold"),
            fill="#c0392b",
        )

        # Barcode placeholder
        self._canvas.create_rectangle(
            x + 20,
            y + 50,
            x + w - 20,
            y + 90,
            outline="#333",
            fill="#fafafa",
        )
        self._canvas.create_text(
            x + w // 2,
            y + 70,
            text=f"||| {item.get('unique_id', 'N/A')} |||",
            font=("Courier", 8),
        )

    def _prev_page(self) -> None:
        """Go to previous page."""
        if self._page > 0:
            self._page -= 1
            self._show_page()

    def _next_page(self) -> None:
        """Go to next page."""
        if self._page < len(self._pages) - 1:
            self._page += 1
            self._show_page()

    def _print_all(self) -> None:
        """Fire confirm callback with all items."""
        self.destroy()
        self._on_confirm(self._items)


# ---------------------------------------------------------------------------
# PrinterSelectionDialog
# ---------------------------------------------------------------------------


class PrinterSelectionDialog(tk.Toplevel):
    """Printer selection dialog.

    Parameters
    ----------
    parent:
        Parent window.
    printer_list:
        List of printer name strings.
    on_select:
        Called with the selected printer name.
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        printer_list: list[str],
        on_select: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self._on_select = on_select

        self.title("Select Printer")
        self.transient(parent)
        self.grab_set()
        self.geometry("350x140")
        self.resizable(False, False)

        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        self._printer_var = tk.StringVar()
        cb = ttk.Combobox(
            main,
            textvariable=self._printer_var,
            values=printer_list,
            state="readonly",
        )
        cb.pack(fill=tk.X, pady=(0, 12))
        if printer_list:
            cb.current(0)

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Print", command=self._confirm).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _confirm(self) -> None:
        """Fire callback with selected printer."""
        selected = self._printer_var.get()
        if selected:
            self.destroy()
            self._on_select(selected)


# ---------------------------------------------------------------------------
# FileSelectionDialog
# ---------------------------------------------------------------------------


class FileSelectionDialog(tk.Toplevel):
    """Modal file selection dialog.

    Parameters
    ----------
    parent:
        Parent window.
    file_list:
        List of file name strings.
    title:
        Dialog title.
    on_confirm:
        Called with the selected file name.
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        file_list: list[str],
        title: str,
        on_confirm: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self._on_confirm = on_confirm

        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.geometry("400x140")
        self.resizable(False, False)

        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        self._file_var = tk.StringVar()
        cb = ttk.Combobox(
            main,
            textvariable=self._file_var,
            values=file_list,
            state="readonly",
        )
        cb.pack(fill=tk.X, pady=(0, 12))
        if file_list:
            cb.current(0)

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="OK", command=self._confirm).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _confirm(self) -> None:
        """Fire callback with selected file."""
        selected = self._file_var.get()
        if selected:
            self.destroy()
            self._on_confirm(selected)


# ---------------------------------------------------------------------------
# ItemSelectionDialog
# ---------------------------------------------------------------------------


class ItemSelectionDialog(tk.Toplevel):
    """Modal item selection dialog with Treeview.

    Parameters
    ----------
    parent:
        Parent window.
    items:
        List of item dicts with keys: unique_id, imei, model, price.
    on_select:
        Called with the selected item dict.
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        items: list[dict[str, Any]],
        on_select: Callable[[dict[str, Any]], None],
    ) -> None:
        super().__init__(parent)
        self._items = items
        self._on_select = on_select

        self.title("Select Item")
        self.transient(parent)
        self.grab_set()
        self.geometry("600x400")

        self._build_ui()

    def _build_ui(self) -> None:
        """Build Treeview UI."""
        main = ttk.Frame(self, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        columns = ("id", "imei", "model", "price")
        self._tree = ttk.Treeview(
            main, columns=columns, show="headings", selectmode="browse"
        )

        self._tree.heading("id", text="ID")
        self._tree.heading("imei", text="IMEI")
        self._tree.heading("model", text="Model")
        self._tree.heading("price", text="Price")

        self._tree.column("id", width=60)
        self._tree.column("imei", width=150)
        self._tree.column("model", width=250)
        self._tree.column("price", width=80)

        for item in self._items:
            self._tree.insert(
                "",
                tk.END,
                iid=str(item.get(FIELD_UNIQUE_ID, "")),
                values=(
                    item.get(FIELD_UNIQUE_ID, ""),
                    item.get(FIELD_IMEI, ""),
                    item.get(FIELD_MODEL, ""),
                    item.get(FIELD_PRICE, 0),
                ),
            )

        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<Double-1>", self._on_select_item)
        self._tree.bind("<Return>", self._on_select_item)

        # Auto-select first item
        children = self._tree.get_children()
        if children:
            self._tree.selection_set(children[0])
            self._tree.focus(children[0])

    def _on_select_item(self, event: tk.Event) -> None:
        """Handle item selection."""
        sel = self._tree.selection()
        if not sel:
            return

        item_id = sel[0]
        for item in self._items:
            if str(item.get(FIELD_UNIQUE_ID, "")) == item_id:
                self.destroy()
                self._on_select(item)
                return


# ---------------------------------------------------------------------------
# ConflictResolutionDialog
# ---------------------------------------------------------------------------


class ConflictResolutionDialog(tk.Toplevel):
    """Dialog for resolving IMEI conflicts.

    Parameters
    ----------
    parent:
        Parent window.
    conflict_data:
        Dict with keys: imei, model, sources, rows.
    on_resolve:
        Called with ``(conflict, action)`` when resolved.
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        conflict_data: dict[str, Any],
        on_resolve: Callable[[dict[str, Any], str], None],
    ) -> None:
        super().__init__(parent)
        self._conflict = conflict_data
        self._on_resolve = on_resolve

        self.title("IMEI Conflict Detected")
        self.transient(parent)
        self.grab_set()
        self.geometry("500x350")

        self._build_ui()

    def _build_ui(self) -> None:
        """Build conflict resolution UI."""
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        # Conflict info
        ttk.Label(
            main,
            text=f"Duplicate IMEI: {self._conflict.get('imei', 'N/A')}",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W, pady=(0, 4))

        ttk.Label(
            main,
            text=f"Model: {self._conflict.get('model', 'N/A')}",
        ).pack(anchor=tk.W, pady=(0, 8))

        # Sources
        sources = self._conflict.get("sources", [])
        ttk.Label(main, text="Found in sources:").pack(anchor=tk.W)
        for src in sources:
            ttk.Label(main, text=f"  • {src}").pack(anchor=tk.W)

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(16, 0))

        ttk.Button(
            btn_frame,
            text="Keep All (Merge)",
            bootstyle="warning",
            command=lambda: self._resolve("merge"),
        ).pack(side=tk.RIGHT, padx=4)

        ttk.Button(
            btn_frame,
            text="Ignore Warning",
            command=lambda: self._resolve("ignore"),
        ).pack(side=tk.RIGHT)

    def _resolve(self, action: str) -> None:
        """Fire resolve callback."""
        self.destroy()
        self._on_resolve(self._conflict, action)


# ---------------------------------------------------------------------------
# SplashScreen
# ---------------------------------------------------------------------------


class SplashScreen(tk.Toplevel):
    """Splash screen shown during application startup.

    Parameters
    ----------
    parent:
        Parent window.
    store_name:
        Store name to display.
    """

    def __init__(self, parent: tk.Tk, store_name: str) -> None:
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(bg="#1a1a2e")

        # Center on parent
        parent.update_idletasks()
        w, h = 420, 200
        x = parent.winfo_x() + (parent.winfo_width() - w) // 2
        y = parent.winfo_y() + (parent.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        # Accent border
        self._border = tk.Frame(self, bg="#007acc", width=w, height=3)
        self._border.pack(fill=tk.X, side=tk.TOP)

        # Content
        content = tk.Frame(self, bg="#1a1a2e")
        content.pack(fill=tk.BOTH, expand=True, padx=24, pady=16)

        tk.Label(
            content,
            text="Welcome to",
            font=("Segoe UI", 12),
            fg="#888888",
            bg="#1a1a2e",
        ).pack()

        tk.Label(
            content,
            text="StockMate",
            font=("Segoe UI", 20, "bold"),
            fg="#ffffff",
            bg="#1a1a2e",
        ).pack(pady=(0, 4))

        tk.Label(
            content,
            text=store_name,
            font=("Segoe UI", 12),
            fg="#007acc",
            bg="#1a1a2e",
        ).pack(pady=(0, 16))

        # Progress
        self._progress_var = tk.StringVar(value="Initializing...")
        self._progress_label = tk.Label(
            content,
            textvariable=self._progress_var,
            font=("Segoe UI", 9),
            fg="#666666",
            bg="#1a1a2e",
        )
        self._progress_label.pack()

        self._progress_bar = ttk.Progressbar(content, mode="determinate", length=300)
        self._progress_bar.pack(pady=(4, 0))

    def update_progress(self, step_text: str, percent: float) -> None:
        """Update the splash screen progress.

        Args:
            step_text: Current step description.
            percent: Progress percentage (0-100).
        """
        self._progress_var.set(step_text)
        self._progress_bar["value"] = percent
        self.update_idletasks()


# ---------------------------------------------------------------------------
# WelcomeDialog
# ---------------------------------------------------------------------------


class WelcomeDialog(tk.Toplevel):
    """Welcome dialog shown on first launch.

    Parameters
    ----------
    parent:
        Parent window.
    on_choice:
        Called with the user's choice string.
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        on_choice: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self._on_choice = on_choice

        self.title("Welcome")
        self.transient(parent)
        self.grab_set()
        self.geometry("380x260")
        self.resizable(False, False)

        self._build_ui()

    def _build_ui(self) -> None:
        """Build welcome dialog UI."""
        main = ttk.Frame(self, padding=24)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text="Welcome to StockMate",
            font=("Segoe UI", 14, "bold"),
        ).pack(pady=(0, 16))

        ttk.Button(
            main,
            text="ADD EXCEL FILE",
            bootstyle="primary",
            command=lambda: self._choose("add_excel"),
        ).pack(fill=tk.X, pady=4)

        ttk.Button(
            main,
            text="USER GUIDE",
            bootstyle="info-outline",
            command=lambda: self._choose("guide"),
        ).pack(fill=tk.X, pady=4)

        ttk.Button(
            main,
            text="EXPLORE APP",
            bootstyle="secondary-outline",
            command=lambda: self._choose("explore"),
        ).pack(fill=tk.X, pady=4)

    def _choose(self, choice: str) -> None:
        """Fire callback with user's choice."""
        self.destroy()
        self._on_choice(choice)
