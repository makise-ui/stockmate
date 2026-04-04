"""Reporting widgets for the Advanced Reporting screen.

Provides three widget classes:
- ``AdvancedFilterPanel`` — dynamic filter builder with preset persistence.
- ``ConditionRow`` — single filter condition row with field/operator/value controls.
- ``SamplingPanel`` — row limit, modulo filter, and custom expression controls.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import ttkbootstrap as tb
from tkinter import ttk

from core.reporting import ReportGenerator


# ---------------------------------------------------------------------------
# ConditionRow
# ---------------------------------------------------------------------------

_OPERATORS: list[str] = [
    "equals",
    "contains",
    "gt",
    "lt",
    "gte",
    "lte",
    "starts_with",
    "ends_with",
    "regex",
    "modulo",
    "is_empty",
    "not_empty",
]

_LOGIC_OPTIONS: list[str] = ["AND", "OR", "AND NOT", "OR NOT", "XOR"]

_VALUE_UNARY_OPERATORS: set[str] = {"is_empty", "not_empty"}


class ConditionRow(ttk.Frame):
    """Single filter condition row with logic, field, operator, and value controls."""

    def __init__(
        self,
        parent: tk.Misc,
        fields: list[str],
        is_first: bool = False,
        on_remove: Callable[[], None] | None = None,
        initial_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self._fields = fields
        self._on_remove = on_remove
        self._is_first = is_first

        # State variables
        self.logic_var = tk.StringVar(value="AND")
        self.field_var = tk.StringVar()
        self.operator_var = tk.StringVar()
        self.value_var = tk.StringVar()

        # Widgets
        self._logic_cb: ttk.Combobox | None = None
        self._field_cb: ttk.Combobox | None = None
        self._operator_cb: ttk.Combobox | None = None
        self._value_container: ttk.Frame | None = None
        self._remove_btn: ttk.Button | None = None

        self._build_ui(initial_data)

    # -- layout --------------------------------------------------------------

    def _build_ui(self, initial_data: dict[str, Any] | None) -> None:
        """Construct the condition row widgets."""
        # Logic combobox (disabled for first row)
        self._logic_cb = ttk.Combobox(
            self,
            textvariable=self.logic_var,
            values=_LOGIC_OPTIONS,
            state="readonly" if not self._is_first else "disabled",
            width=10,
        )
        self._logic_cb.pack(side=tk.LEFT, padx=2)

        # Field combobox
        self._field_cb = ttk.Combobox(
            self,
            textvariable=self.field_var,
            values=self._fields,
            state="readonly",
            width=18,
        )
        self._field_cb.pack(side=tk.LEFT, padx=2)
        self._field_cb.bind("<<ComboboxSelected>>", self._on_field_change)

        # Operator combobox
        self._operator_cb = ttk.Combobox(
            self,
            textvariable=self.operator_var,
            values=_OPERATORS,
            state="readonly",
            width=14,
        )
        self._operator_cb.pack(side=tk.LEFT, padx=2)
        self._operator_cb.bind("<<ComboboxSelected>>", self._on_operator_change)

        # Value container — dedicated frame for swapping value inputs
        self._value_container = ttk.Frame(self)
        self._value_container.pack(side=tk.LEFT, padx=2)
        self._build_value_input()

        # Remove button
        self._remove_btn = ttk.Button(
            self,
            text="✕",
            width=3,
            bootstyle="danger-outline",
            command=self._on_remove,
        )
        self._remove_btn.pack(side=tk.LEFT, padx=2)

        # Populate from initial data if provided
        if initial_data:
            self._apply_initial_data(initial_data)

    def _build_value_input(self) -> None:
        """Create the appropriate value input widget inside the container."""
        if self._value_container is None:
            return

        operator = self.operator_var.get()

        if operator in _VALUE_UNARY_OPERATORS:
            ttk.Label(
                self._value_container,
                text="(no value)",
                width=20,
                anchor=tk.CENTER,
            ).pack(fill=tk.BOTH)
        else:
            ttk.Entry(
                self._value_container,
                textvariable=self.value_var,
                width=20,
            ).pack(fill=tk.BOTH)

    def _swap_value_input(self) -> None:
        """Destroy and rebuild the value input widget."""
        if self._value_container is None:
            return

        for child in self._value_container.winfo_children():
            child.destroy()

        self._build_value_input()

    def _apply_initial_data(self, data: dict[str, Any]) -> None:
        """Pre-populate widgets from a condition dict."""
        if "logic" in data:
            self.logic_var.set(data["logic"])
        if "field" in data:
            self.field_var.set(data["field"])
        if "operator" in data:
            self.operator_var.set(data["operator"])
        if "value" in data:
            self.value_var.set(str(data["value"]))

    # -- event handlers ------------------------------------------------------

    def _on_field_change(self, event: tk.Event | None = None) -> None:
        """Update operator suggestions based on selected field type."""
        # For now, keep all operators available. Future enhancement:
        # detect numeric/date fields and filter operators accordingly.
        pass

    def _on_operator_change(self, event: tk.Event | None = None) -> None:
        """Switch value input type based on operator selection."""
        operator = self.operator_var.get()
        if not operator:
            return

        self._swap_value_input()

    # -- data access ---------------------------------------------------------

    def get_condition(self) -> dict[str, Any] | None:
        """Return the condition dict, or None if incomplete."""
        field = self.field_var.get().strip()
        if not field:
            return None

        operator = self.operator_var.get().strip()
        if not operator:
            return None

        condition: dict[str, Any] = {
            "logic": self.logic_var.get(),
            "field": field,
            "operator": operator,
        }

        if operator not in _VALUE_UNARY_OPERATORS:
            condition["value"] = self.value_var.get()

        return condition


# ---------------------------------------------------------------------------
# AdvancedFilterPanel
# ---------------------------------------------------------------------------

_PRESETS_FILE = "filter_presets.json"


class AdvancedFilterPanel(ttk.Frame):
    """Dynamic filter builder with condition rows and preset management."""

    def __init__(
        self,
        parent: tk.Misc,
        fields: list[str],
        config_dir: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._fields = fields
        self._config_dir = config_dir
        self._rows: list[ConditionRow] = []
        self._rows_frame: ttk.Frame | None = None
        self._preset_cb: ttk.Combobox | None = None

        self._build_ui()
        self._add_condition()  # start with one empty row

    # -- layout --------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the filter panel interface."""
        # Presets row
        preset_frame = ttk.Frame(self)
        preset_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(preset_frame, text="Presets:").pack(side=tk.LEFT)
        self._preset_cb = ttk.Combobox(
            preset_frame,
            values=self._load_preset_names(),
            state="readonly",
            width=25,
        )
        self._preset_cb.pack(side=tk.LEFT, padx=4)
        self._preset_cb.bind("<<ComboboxSelected>>", self._on_preset_select)

        ttk.Button(
            preset_frame,
            text="Save Preset",
            bootstyle="success-outline",
            command=self._save_preset,
            width=12,
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            preset_frame,
            text="Delete Preset",
            bootstyle="danger-outline",
            command=self._delete_preset,
            width=12,
        ).pack(side=tk.LEFT, padx=4)

        # Scrollable rows container
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)
        self._rows_frame = ttk.Frame(canvas)

        self._rows_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._rows_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Add condition button
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(
            btn_frame,
            text="+ Add Condition",
            bootstyle="info-outline",
            command=self._add_condition,
        ).pack(side=tk.LEFT)

    # -- condition management ------------------------------------------------

    def _add_condition(self, initial_data: dict[str, Any] | None = None) -> None:
        """Add a new condition row."""
        if self._rows_frame is None:
            return

        is_first = len(self._rows) == 0
        row = ConditionRow(
            self._rows_frame,
            fields=self._fields,
            is_first=is_first,
            on_remove=lambda: self._remove_condition(row),
            initial_data=initial_data,
        )
        row.pack(fill=tk.X, pady=2)
        self._rows.append(row)

        # If this is no longer the first row, disable the old first row's logic
        if len(self._rows) == 2:
            first_row = self._rows[0]
            if first_row._logic_cb is not None:
                first_row._logic_cb.configure(state="disabled")

    def _remove_condition(self, row: ConditionRow) -> None:
        """Remove a condition row."""
        if row not in self._rows:
            return

        self._rows.remove(row)
        row.destroy()

        # If only one row remains, ensure its logic is disabled
        if len(self._rows) == 1:
            first_row = self._rows[0]
            if first_row._logic_cb is not None:
                first_row._logic_cb.configure(state="disabled")

    # -- preset management ---------------------------------------------------

    def _get_presets_path(self) -> Path:
        """Return the path to the presets JSON file."""
        if self._config_dir:
            return Path(self._config_dir) / _PRESETS_FILE
        return (
            Path.home() / "Documents" / "StockMate" / "config" / _PRESETS_FILE
        )

    def _load_presets(self) -> dict[str, list[dict[str, Any]]]:
        """Load all filter presets from disk."""
        path = self._get_presets_path()
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def _save_presets_to_disk(self, presets: dict[str, list[dict[str, Any]]]) -> None:
        """Persist presets dict to disk."""
        path = self._get_presets_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(presets, f, indent=2)
        except OSError:
            pass

    def _load_preset_names(self) -> list[str]:
        """Return sorted list of preset names."""
        return sorted(self._load_presets().keys())

    def _save_preset(self) -> None:
        """Save current conditions as a named preset."""
        conditions = self.get_conditions()
        if not conditions:
            return

        # Simple dialog for preset name
        name_dialog = tk.Toplevel(self)
        name_dialog.title("Save Preset")
        name_dialog.transient(self)
        name_dialog.grab_set()
        name_dialog.geometry("300x120")
        name_dialog.resizable(False, False)

        ttk.Label(name_dialog, text="Preset name:").pack(
            anchor=tk.W, padx=12, pady=(12, 4)
        )
        name_var = tk.StringVar()
        entry = ttk.Entry(name_dialog, textvariable=name_var, width=35)
        entry.pack(fill=tk.X, padx=12)
        entry.focus_set()

        def _confirm() -> None:
            name = name_var.get().strip()
            if not name:
                return
            presets = self._load_presets()
            presets[name] = conditions
            self._save_presets_to_disk(presets)
            if self._preset_cb is not None:
                self._preset_cb.configure(values=self._load_preset_names())
            name_dialog.destroy()

        def _cancel() -> None:
            name_dialog.destroy()

        btn_frame = ttk.Frame(name_dialog)
        btn_frame.pack(fill=tk.X, padx=12, pady=(8, 12))
        ttk.Button(btn_frame, text="Save", bootstyle="success", command=_confirm).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(btn_frame, text="Cancel", command=_cancel).pack(side=tk.RIGHT)

        entry.bind("<Return>", lambda e: _confirm())

    def _delete_preset(self) -> None:
        """Delete the currently selected preset."""
        if self._preset_cb is None:
            return
        name = self._preset_cb.get()
        if not name:
            return

        presets = self._load_presets()
        if name in presets:
            del presets[name]
            self._save_presets_to_disk(presets)
            self._preset_cb.configure(values=self._load_preset_names())
            self._preset_cb.set("")

    def _on_preset_select(self, event: tk.Event | None = None) -> None:
        """Load the selected preset into condition rows."""
        if self._preset_cb is None:
            return
        name = self._preset_cb.get()
        if not name:
            return

        presets = self._load_presets()
        conditions = presets.get(name)
        if conditions is None:
            return

        self._load_conditions(conditions)

    def _load_conditions(self, conditions: list[dict[str, Any]]) -> None:
        """Replace all rows with the given conditions."""
        # Clear existing rows
        for row in self._rows:
            row.destroy()
        self._rows.clear()

        if self._rows_frame is None:
            return

        if not conditions:
            self._add_condition()
            return

        for i, cond in enumerate(conditions):
            self._add_condition(initial_data=cond)

    # -- data access ---------------------------------------------------------

    def get_conditions(self) -> list[dict[str, Any]]:
        """Collect conditions from all rows, filtering out incomplete ones."""
        conditions: list[dict[str, Any]] = []
        for row in self._rows:
            cond = row.get_condition()
            if cond is not None:
                conditions.append(cond)
        return conditions

    def update_fields(self, fields: list[str]) -> None:
        """Update the field list for all condition rows."""
        self._fields = fields
        for row in self._rows:
            if row._field_cb is not None:
                row._field_cb.configure(values=fields)


# ---------------------------------------------------------------------------
# SamplingPanel
# ---------------------------------------------------------------------------


class SamplingPanel(ttk.Frame):
    """Row sampling controls: limit, modulo, and custom pandas expression."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.limit_var = tk.StringVar()
        self.modulo_var = tk.StringVar()
        self.expression_var = tk.StringVar()

        self._build_ui()

    # -- layout --------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the sampling panel."""
        ttk.LabelFrame(self, text="Sampling", padding=8).pack(fill=tk.X)
        frame = self.winfo_children()[0]

        # Row limit
        ttk.Label(frame, text="Row Limit:").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(
            frame,
            from_=0,
            to=100000,
            textvariable=self.limit_var,
            width=10,
        ).grid(row=0, column=1, sticky=tk.W, padx=(8, 0), pady=4)

        # Modulo
        ttk.Label(frame, text="Modulo (every Nth):").grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        ttk.Spinbox(
            frame,
            from_=0,
            to=10000,
            textvariable=self.modulo_var,
            width=10,
        ).grid(row=1, column=1, sticky=tk.W, padx=(8, 0), pady=4)

        # Custom expression
        ttk.Label(frame, text="Custom Expression:").grid(
            row=2, column=0, sticky=tk.W, pady=4
        )
        ttk.Entry(
            frame,
            textvariable=self.expression_var,
            width=40,
        ).grid(row=2, column=1, sticky=tk.EW, padx=(8, 0), pady=4)

        frame.grid_columnconfigure(1, weight=1)

    # -- data access ---------------------------------------------------------

    def get_limit(self) -> int | None:
        """Return the row limit as an int, or None if empty/invalid."""
        raw = self.limit_var.get().strip()
        if not raw:
            return None
        try:
            val = int(raw)
            return val if val > 0 else None
        except ValueError:
            return None

    def get_modulo(self) -> int | None:
        """Return the modulo value as an int, or None if empty/invalid."""
        raw = self.modulo_var.get().strip()
        if not raw:
            return None
        try:
            val = int(raw)
            return val if val > 0 else None
        except ValueError:
            return None

    def get_expression(self) -> str:
        """Return the custom pandas expression string."""
        return self.expression_var.get().strip()
