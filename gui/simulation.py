"""Price simulation dialog for StockMate."""

from __future__ import annotations

import tkinter as tk
from typing import Any

import ttkbootstrap as tb
from tkinter import ttk


class PriceSimulationDialog(tb.Toplevel):
    """What-if price/cost simulation dialog.

    Allows the user to adjust cost or price by percentage or flat amount
    and see the projected impact in real time.

    Parameters
    ----------
    parent:
        Parent window.
    current_params:
        Optional dict with existing simulation parameters to pre-fill.
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        current_params: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.result: dict[str, Any] | None = None
        self._params = current_params or {}

        self.title("Price Simulation")
        self.transient(parent)
        self.grab_set()
        self.geometry("400x420")
        self.resizable(False, False)

        self._build_ui()
        self._update_example()

    # -- UI ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build simulation dialog UI."""
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        # Enable toggle
        self._enabled_var = tk.BooleanVar(value=bool(self._params))
        ttk.Checkbutton(
            main,
            text="Enable Simulation",
            variable=self._enabled_var,
            command=self._on_toggle,
        ).pack(anchor=tk.W, pady=(0, 12))

        # Target
        ttk.Label(main, text="Adjust:").pack(anchor=tk.W)
        self._target_var = tk.StringVar(value=self._params.get("target", "price"))
        ttk.Combobox(
            main,
            textvariable=self._target_var,
            values=["cost", "price"],
            state="readonly",
            width=20,
        ).pack(fill=tk.X, pady=(0, 8))

        # Base
        ttk.Label(main, text="Base:").pack(anchor=tk.W)
        self._base_var = tk.StringVar(value=self._params.get("base", "cost"))
        ttk.Combobox(
            main,
            textvariable=self._base_var,
            values=["cost", "price"],
            state="readonly",
            width=20,
        ).pack(fill=tk.X, pady=(0, 8))

        # Percentage adjustment
        pct_frame = ttk.Frame(main)
        pct_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(pct_frame, text="Percentage:").pack(side=tk.LEFT)
        self._pct_var = tk.DoubleVar(value=self._params.get("percent", 0.0))
        tb.Spinbox(
            pct_frame,
            from_=-100,
            to=100,
            increment=1,
            textvariable=self._pct_var,
            width=10,
            command=self._update_example,
        ).pack(side=tk.LEFT, padx=8)
        self._pct_var.trace_add("write", lambda *_: self._update_example())

        # Flat adjustment
        flat_frame = ttk.Frame(main)
        flat_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(flat_frame, text="Flat adjustment:").pack(side=tk.LEFT)
        self._flat_var = tk.DoubleVar(value=self._params.get("flat", 0.0))
        flat_entry = ttk.Entry(flat_frame, textvariable=self._flat_var, width=12)
        flat_entry.pack(side=tk.LEFT, padx=8)
        flat_entry.bind("<KeyRelease>", lambda e: self._update_example())

        # Live example
        self._example_frame = ttk.LabelFrame(main, text="Example", padding=8)
        self._example_frame.pack(fill=tk.X, pady=(0, 12))
        self._example_text = tk.StringVar(value="")
        ttk.Label(
            self._example_frame,
            textvariable=self._example_text,
            font=("Consolas", 10),
        ).pack(anchor=tk.W)

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Apply", command=self._apply).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

        self._on_toggle()

    # -- interaction ---------------------------------------------------------

    def _on_toggle(self) -> None:
        """Enable/disable controls based on toggle state."""
        state = "normal" if self._enabled_var.get() else "disabled"
        for child in self.winfo_children():
            if isinstance(child, ttk.Frame):
                for grandchild in child.winfo_children():
                    if isinstance(grandchild, (ttk.Combobox, tb.Spinbox, ttk.Entry)):
                        grandchild.configure(state=state)

    def _update_example(self) -> None:
        """Update the live example calculation display."""
        if not self._enabled_var.get():
            self._example_text.set("Simulation disabled")
            return

        pct = self._pct_var.get()
        flat = self._flat_var.get()
        target = self._target_var.get()
        base = self._base_var.get()

        # Example: base=10000, pct=10, flat=500
        example_base = 10000.0
        modifier = 1.0 + pct / 100.0
        adjusted = example_base * modifier + flat

        self._example_text.set(
            f"Base: \u20b9{example_base:,.0f}\n"
            f"Modifier: {modifier:.2f} ({pct:+.0f}%)\n"
            f"Flat: {flat:+,.0f}\n"
            f"Result: \u20b9{adjusted:,.0f}"
        )

    def _apply(self) -> None:
        """Set result and close."""
        if not self._enabled_var.get():
            self.result = None
        else:
            pct = self._pct_var.get()
            flat = self._flat_var.get()
            modifier = 1.0 + pct / 100.0

            self.result = {
                "target": self._target_var.get(),
                "base": self._base_var.get(),
                "modifier": modifier,
                "flat_adjust": flat,
            }
        self.destroy()
