"""Settings, file management, and reference data screens.

Provides three screen classes:
- ``SettingsScreen`` — tabbed application settings editor.
- ``ManageFilesScreen`` — Excel file mapping management.
- ``ManageDataScreen`` — reference data (colors, buyers, grades, conditions).
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import ttk
from typing import Any

import ttkbootstrap as tb
from ttkbootstrap.dialogs import Messagebox

from gui.base import BaseScreen
from gui.dialogs import MapColumnsDialog


# ---------------------------------------------------------------------------
# SettingsScreen
# ---------------------------------------------------------------------------


class SettingsScreen(BaseScreen):
    """Tabbed settings editor for store, printing, invoice, appearance, and AI config."""

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)
        self._notebook: ttk.Notebook | None = None
        self._vars: dict[str, tk.StringVar | tk.DoubleVar | tk.BooleanVar] = {}
        self._theme_cb: ttk.Combobox | None = None
        self._printer_cb: ttk.Combobox | None = None
        self._ai_toggle: ttk.Checkbutton | None = None
        self._terms_text: tk.Text | None = None

        self._build_ui()

    # -- layout --------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the tabbed settings interface."""
        self.add_header("Settings")

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))

        self._build_general_tab()
        self._build_printing_tab()
        self._build_invoice_tab()
        self._build_appearance_tab()
        self._build_intelligence_tab()

    def _build_general_tab(self) -> None:
        """General settings: store info, terms, markup."""
        frame = ttk.Frame(self._notebook, padding=16)
        self._notebook.add(frame, text="General")

        fields = [
            ("Store Name", "store_name", tk.StringVar),
            ("GSTIN", "store_gstin", tk.StringVar),
            ("Address", "store_address", tk.StringVar),
            ("Phone", "store_contact", tk.StringVar),
            ("Markup %", "price_markup_percent", tk.DoubleVar),
        ]

        for idx, (label, key, var_cls) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=idx, column=0, sticky=tk.W, pady=4)
            var = var_cls()
            self._vars[key] = var
            entry: ttk.Entry | ttk.Spinbox
            if var_cls is tk.DoubleVar:
                entry = ttk.Spinbox(frame, from_=0, to=100, textvariable=var, width=12)
            else:
                entry = ttk.Entry(frame, textvariable=var, width=40)
            entry.grid(row=idx, column=1, sticky=tk.EW, padx=(8, 0), pady=4)

        # Terms & conditions — multi-line
        ttk.Label(frame, text="Terms & Conditions").grid(
            row=len(fields), column=0, sticky=tk.NW, pady=(12, 4)
        )
        self._terms_text = tk.Text(frame, width=40, height=5, wrap=tk.WORD)
        self._terms_text.grid(
            row=len(fields), column=1, sticky=tk.EW, padx=(8, 0), pady=(12, 4)
        )
        scrollbar = ttk.Scrollbar(
            frame, orient=tk.VERTICAL, command=self._terms_text.yview
        )
        scrollbar.grid(row=len(fields), column=2, sticky=tk.NS, pady=(12, 4))
        self._terms_text.configure(yscrollcommand=scrollbar.set)

        frame.grid_columnconfigure(1, weight=1)

        ttk.Button(
            frame, text="Save", bootstyle="success", command=self._save_settings
        ).grid(row=len(fields) + 1, column=1, sticky=tk.E, pady=(12, 0))

    def _build_printing_tab(self) -> None:
        """Printing settings: default printer, label dimensions."""
        frame = ttk.Frame(self._notebook, padding=16)
        self._notebook.add(frame, text="Printing")

        ttk.Label(frame, text="Default Printer").grid(
            row=0, column=0, sticky=tk.W, pady=4
        )
        printers = self._get_system_printers()
        self._printer_cb = ttk.Combobox(
            frame, values=printers, state="readonly", width=40
        )
        self._printer_cb.grid(row=0, column=1, sticky=tk.EW, padx=(8, 0), pady=4)

        ttk.Label(frame, text="Label Width (mm)").grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        self._vars["label_width_mm"] = tk.StringVar()
        ttk.Spinbox(
            frame, from_=10, to=200, textvariable=self._vars["label_width_mm"], width=12
        ).grid(row=1, column=1, sticky=tk.W, padx=(8, 0), pady=4)

        ttk.Label(frame, text="Label Height (mm)").grid(
            row=2, column=0, sticky=tk.W, pady=4
        )
        self._vars["label_height_mm"] = tk.StringVar()
        ttk.Spinbox(
            frame,
            from_=10,
            to=200,
            textvariable=self._vars["label_height_mm"],
            width=12,
        ).grid(row=2, column=1, sticky=tk.W, padx=(8, 0), pady=4)

        frame.grid_columnconfigure(1, weight=1)

        ttk.Button(
            frame, text="Save", bootstyle="success", command=self._save_settings
        ).grid(row=3, column=1, sticky=tk.E, pady=(16, 0))

    def _build_invoice_tab(self) -> None:
        """Invoice settings: prefix, starting number, tax defaults."""
        frame = ttk.Frame(self._notebook, padding=16)
        self._notebook.add(frame, text="Invoice")

        fields = [
            ("Invoice Prefix", "invoice_prefix", tk.StringVar),
            ("Starting Number", "invoice_start_number", tk.StringVar),
            ("GST Rate %", "gst_default_percent", tk.DoubleVar),
        ]

        for idx, (label, key, var_cls) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=idx, column=0, sticky=tk.W, pady=4)
            var = var_cls()
            self._vars[key] = var
            if var_cls is tk.DoubleVar:
                entry: ttk.Widget = ttk.Spinbox(
                    frame, from_=0, to=100, textvariable=var, width=12
                )
            else:
                entry = ttk.Entry(frame, textvariable=var, width=20)
            entry.grid(row=idx, column=1, sticky=tk.W, padx=(8, 0), pady=4)

        # Interstate default toggle
        self._vars["invoice_interstate_default"] = tk.BooleanVar()
        ttk.Checkbutton(
            frame,
            text="Interstate (IGST) default",
            variable=self._vars["invoice_interstate_default"],
        ).grid(row=len(fields), column=0, columnspan=2, sticky=tk.W, pady=(8, 4))

        frame.grid_columnconfigure(1, weight=1)

        ttk.Button(
            frame, text="Save", bootstyle="success", command=self._save_settings
        ).grid(row=len(fields) + 1, column=1, sticky=tk.E, pady=(12, 0))

    def _build_appearance_tab(self) -> None:
        """Appearance settings: theme selector with live preview."""
        frame = ttk.Frame(self._notebook, padding=16)
        self._notebook.add(frame, text="Appearance")

        ttk.Label(frame, text="Theme").grid(row=0, column=0, sticky=tk.W, pady=4)
        themes = sorted(tb.Style().theme_names())
        self._vars["theme_name"] = tk.StringVar()
        self._theme_cb = ttk.Combobox(
            frame,
            textvariable=self._vars["theme_name"],
            values=themes,
            state="readonly",
            width=30,
        )
        self._theme_cb.grid(row=0, column=1, sticky=tk.W, padx=(8, 0), pady=4)
        self._theme_cb.bind("<<ComboboxSelected>>", self._on_theme_change)

        ttk.Button(
            frame, text="Save", bootstyle="success", command=self._save_settings
        ).grid(row=1, column=1, sticky=tk.E, pady=(16, 0))

    def _build_intelligence_tab(self) -> None:
        """Intelligence settings: AI feature toggles."""
        frame = ttk.Frame(self._notebook, padding=16)
        self._notebook.add(frame, text="Intelligence")

        self._vars["enable_ai_scraper"] = tk.BooleanVar()
        self._ai_toggle = ttk.Checkbutton(
            frame,
            text="Enable AI web scraper for price/market data",
            variable=self._vars["enable_ai_scraper"],
        )
        self._ai_toggle.grid(row=0, column=0, sticky=tk.W, pady=8)

        ttk.Button(
            frame, text="Save", bootstyle="success", command=self._save_settings
        ).grid(row=1, column=0, sticky=tk.W, pady=(12, 0))

    # -- settings persistence ------------------------------------------------

    def _load_settings(self) -> None:
        """Populate all fields from the current config."""
        config = self.app.get("config")
        if config is None:
            return

        for key, var in self._vars.items():
            value = config.get(key)
            if value is None:
                continue
            if isinstance(var, tk.BooleanVar):
                var.set(bool(value))
            elif isinstance(var, tk.DoubleVar):
                try:
                    var.set(float(value))
                except (ValueError, TypeError):
                    pass
            else:
                var.set(str(value))

        # Terms text — stored as a single string in config
        terms = config.get("invoice_terms", "")
        if self._terms_text is not None:
            self._terms_text.delete("1.0", tk.END)
            self._terms_text.insert("1.0", str(terms))

    def _save_settings(self) -> None:
        """Persist all fields to config."""
        config = self.app.get("config")
        if config is None:
            return

        for key, var in self._vars.items():
            if isinstance(var, tk.BooleanVar):
                config.set(key, var.get())
            elif isinstance(var, tk.DoubleVar):
                try:
                    config.set(key, float(var.get()))
                except (ValueError, TypeError):
                    pass
            else:
                config.set(key, var.get())

        # Terms
        if self._terms_text is not None:
            config.set("invoice_terms", self._terms_text.get("1.0", tk.END).strip())

        self.app["app"].show_toast(
            "Settings Saved", "All settings have been updated.", "success"
        )

    def _on_theme_change(self, event: tk.Event | None = None) -> None:
        """Apply theme change live for preview."""
        theme = self._vars.get("theme_name")
        if theme is None:
            return
        tb.Style().theme_use(theme.get())

    def _get_system_printers(self) -> list[str]:
        """Return a list of available system printer names."""
        printer = self.app.get("printer")
        if printer is not None and hasattr(printer, "list_printers"):
            return printer.list_printers()
        return []

    # -- lifecycle -----------------------------------------------------------

    def on_show(self) -> None:
        """Load settings when the screen becomes visible."""
        self._load_settings()

    def focus_primary(self) -> None:
        """No primary focus target for settings."""


# ---------------------------------------------------------------------------
# ManageFilesScreen
# ---------------------------------------------------------------------------


class ManageFilesScreen(BaseScreen):
    """Excel file mapping management screen."""

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)
        self._listbox: tk.Listbox | None = None
        self._status_var: tk.StringVar = tk.StringVar()

        self._build_ui()

    # -- layout --------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the file management interface."""
        self.add_header("Manage Files")

        # Status label
        ttk.Label(self, textvariable=self._status_var, font=("Segoe UI", 9)).pack(
            anchor=tk.W, padx=12, pady=(0, 4)
        )

        # File listbox with scrollbar
        list_frame = ttk.LabelFrame(self, text="Mapped Files", padding=8)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self._listbox = tk.Listbox(
            list_frame,
            selectmode=tk.SINGLE,
            yscrollcommand=scrollbar.set,
            font=("Consolas", 9),
        )
        scrollbar.configure(command=self._listbox.yview)

        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Action buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=8)

        ttk.Button(
            btn_frame, text="Add File", bootstyle="success", command=self._add_file
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btn_frame, text="Edit Mapping", bootstyle="info", command=self._edit_mapping
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btn_frame, text="Remove", bootstyle="danger", command=self._remove_file
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btn_frame,
            text="Refresh",
            bootstyle="secondary-outline",
            command=self._load_files,
        ).pack(side=tk.RIGHT, padx=4)

    # -- file operations -----------------------------------------------------

    def _load_files(self) -> None:
        """Load file mappings from config and populate the listbox."""
        if self._listbox is None:
            return

        self._listbox.delete(0, tk.END)
        config = self.app.get("config")
        if config is None:
            self._status_var.set("No configuration available.")
            return

        mappings = getattr(config, "mappings", {})
        if not mappings:
            self._status_var.set("No files mapped yet.")
            return

        for key, data in mappings.items():
            file_path = data.get("file_path", key)
            status = self._get_file_status(file_path)
            display = f"[{status}] {os.path.basename(file_path)} — {file_path}"
            self._listbox.insert(tk.END, display)

        self._status_var.set(f"{len(mappings)} file(s) mapped.")

    def _add_file(self) -> None:
        """Open file dialog to select an Excel file, then launch mapping dialog."""
        file_path = filedialog.askopenfilename(
            title="Select Excel File",
            filetypes=[
                ("Excel Files", "*.xlsx *.xls"),
                ("CSV Files", "*.csv"),
                ("All Files", "*.*"),
            ],
        )
        if not file_path:
            return

        config = self.app.get("config")
        if config is None:
            return

        if config.get_file_mapping(file_path):
            self.app["app"].show_toast(
                "Already Mapped", "This file is already mapped.", "warning"
            )
            return

        MapColumnsDialog(
            self,
            file_path=file_path,
            on_save_callback=self._on_save_mapping,
        )

    def _edit_mapping(self) -> None:
        """Open mapping dialog for the selected file."""
        selection = self._get_selected_mapping()
        if selection is None:
            return

        key, data = selection
        file_path = data.get("file_path", key)

        if not os.path.exists(file_path):
            self.app["app"].show_toast(
                "File Missing", f"File not found: {file_path}", "danger"
            )
            return

        MapColumnsDialog(
            self,
            file_path=file_path,
            on_save_callback=self._on_save_mapping,
            current_mapping=data,
        )

    def _remove_file(self) -> None:
        """Remove the selected file mapping after confirmation."""
        selection = self._get_selected_mapping()
        if selection is None:
            return

        key, data = selection
        file_path = data.get("file_path", key)

        response = Messagebox.okcancel(
            title="Confirm Removal",
            message=f"Remove mapping for:\n{file_path}?",
        )
        if response != "OK":
            return

        config = self.app.get("config")
        if config is None:
            return

        config.remove_file_mapping(key)
        self.app["app"].show_toast("Mapping Removed", "File mapping deleted.", "info")
        self._load_files()

        # Reload inventory to reflect removal
        inventory = self.app.get("inventory")
        if inventory is not None and hasattr(inventory, "reload_all"):
            inventory.reload_all()

    def _on_save_mapping(self, key: str, data: dict) -> None:
        """Callback from MapColumnsDialog — persist and reload."""
        config = self.app.get("config")
        if config is None:
            return

        config.set_file_mapping(key, data)

        inventory = self.app.get("inventory")
        if inventory is not None and hasattr(inventory, "reload_all"):
            inventory.reload_all()

        self.app["app"].show_toast(
            "File Mapped", "Excel file mapped successfully.", "success"
        )
        self._load_files()

    # -- helpers -------------------------------------------------------------

    def _get_selected_mapping(self) -> tuple[str, dict] | None:
        """Return (key, data) for the selected listbox item, or None."""
        if self._listbox is None:
            return None

        sel = self._listbox.curselection()
        if not sel:
            self.app["app"].show_toast(
                "No Selection", "Select a file first.", "warning"
            )
            return None

        config = self.app.get("config")
        if config is None:
            return None

        mappings = getattr(config, "mappings", {})
        keys = list(mappings.keys())
        index = sel[0]
        if index >= len(keys):
            return None

        key = keys[index]
        return key, mappings[key]

    @staticmethod
    def _get_file_status(file_path: str) -> str:
        """Return a status indicator for the given file path."""
        if not os.path.exists(file_path):
            return "MISSING"
        return "OK"

    # -- lifecycle -----------------------------------------------------------

    def on_show(self) -> None:
        """Load file list when the screen becomes visible."""
        self._load_files()

    def focus_primary(self) -> None:
        """No primary focus target for file management."""


# ---------------------------------------------------------------------------
# ManageDataScreen
# ---------------------------------------------------------------------------


class ManageDataScreen(BaseScreen):
    """Reference data management for colors, buyers, grades, and conditions."""

    CATEGORIES: list[str] = ["colors", "buyers", "grades", "conditions"]

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)
        self._notebook: ttk.Notebook | None = None
        self._listboxes: dict[str, tk.Listbox] = {}
        self._entry_vars: dict[str, tk.StringVar] = {}

        self._build_ui()

    # -- layout --------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the reference data management interface."""
        self.add_header("Manage Reference Data")

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))

        for category in self.CATEGORIES:
            self._build_category_tab(category)

    def _build_category_tab(self, category: str) -> None:
        """Build a tab for a single reference data category."""
        frame = ttk.Frame(self._notebook, padding=12)
        self._notebook.add(frame, text=category.capitalize())

        # Listbox with scrollbar
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        lb = tk.Listbox(
            list_frame,
            selectmode=tk.SINGLE,
            yscrollcommand=scrollbar.set,
            font=("Segoe UI", 10),
        )
        scrollbar.configure(command=lb.yview)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._listboxes[category] = lb

        # Add / Remove row
        row_frame = ttk.Frame(frame)
        row_frame.pack(fill=tk.X, pady=4)

        var = tk.StringVar()
        self._entry_vars[category] = var
        ttk.Entry(row_frame, textvariable=var, width=30).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            row_frame,
            text="Add",
            bootstyle="success",
            command=lambda c=category: self._add_item(c),
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            row_frame,
            text="Remove",
            bootstyle="danger",
            command=lambda c=category: self._remove_item(c),
        ).pack(side=tk.LEFT, padx=4)

        # Bind Enter key to add
        var.trace_add(
            "write",
            lambda *_: None,  # placeholder, Enter binding below
        )
        # We bind on the entry widget via the listbox parent
        lb.bind("<Return>", lambda e, c=category: self._add_item(c))

    # -- data operations -----------------------------------------------------

    def _load_data(self) -> None:
        """Load reference data from config into each category listbox."""
        config = self.app.get("config")
        if config is None:
            return

        for category in self.CATEGORIES:
            lb = self._listboxes.get(category)
            if lb is None:
                continue

            lb.delete(0, tk.END)
            items = self._get_category_data(category)
            for item in items:
                lb.insert(tk.END, item)

    def _add_item(self, category: str) -> None:
        """Add a new value to the given category."""
        var = self._entry_vars.get(category)
        if var is None:
            return

        value = var.get().strip()
        if not value:
            self.app["app"].show_toast(
                "Empty Value", "Enter a value before adding.", "warning"
            )
            return

        items = self._get_category_data(category)
        if value in items:
            self.app["app"].show_toast(
                "Duplicate", f"'{value}' already exists.", "warning"
            )
            return

        items.append(value)
        self._set_category_data(category, items)
        var.set("")
        self._load_data()

    def _remove_item(self, category: str) -> None:
        """Remove the selected value from the given category."""
        lb = self._listboxes.get(category)
        if lb is None:
            return

        sel = lb.curselection()
        if not sel:
            self.app["app"].show_toast(
                "No Selection", "Select an item to remove.", "warning"
            )
            return

        items = self._get_category_data(category)
        index = sel[0]
        if index >= len(items):
            return

        removed = items.pop(index)
        self._set_category_data(category, items)
        self.app["app"].show_toast("Removed", f"'{removed}' deleted.", "info")
        self._load_data()

    def _save_data(self) -> None:
        """Persist all category data to config."""
        # Data is saved incrementally in _add_item / _remove_item,
        # but this ensures a full refresh if called externally.
        self._load_data()

    # -- config helpers ------------------------------------------------------

    def _get_category_data(self, category: str) -> list[str]:
        """Return the list of values for a category from config."""
        config = self.app.get("config")
        if config is None:
            return []

        key = f"reference_{category}"
        data = config.get(key)
        if isinstance(data, list):
            return [str(item) for item in data]
        return []

    def _set_category_data(self, category: str, items: list[str]) -> None:
        """Persist the category list to config."""
        config = self.app.get("config")
        if config is None:
            return

        key = f"reference_{category}"
        config.set(key, items)

    # -- lifecycle -----------------------------------------------------------

    def on_show(self) -> None:
        """Load reference data when the screen becomes visible."""
        self._load_data()

    def focus_primary(self) -> None:
        """No primary focus target for reference data."""
