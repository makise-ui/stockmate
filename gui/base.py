"""Base classes and shared UI components for StockMate screens."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

import pandas as pd


class AutocompleteEntry(ttk.Entry):
    """Entry widget with inline type-ahead autocompletion.

    Only completes when the cursor is at the end of the entry text.
    Matching is case-insensitive; the matched item's original casing is
    inserted.

    Parameters
    ----------
    parent:
        Parent widget.
    completion_list:
        Initial list of completion candidates.
    """

    def __init__(
        self,
        parent: tk.Misc,
        completion_list: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent, **kwargs)
        self._completion_list: list[str] = []
        self._typed_prefix: str = ""

        if completion_list:
            self.set_completion_list(completion_list)

        self.bind("<KeyRelease>", self.handle_keyrelease)
        self.bind("<Tab>", self._complete)
        self.bind("<Right>", self._complete)

    # -- public API ----------------------------------------------------------

    def set_completion_list(self, completion_list: list[str]) -> None:
        """Replace the completion candidate list.

        Args:
            completion_list: New list of strings to autocomplete against.
        """
        self._completion_list = sorted(completion_list)

    def handle_keyrelease(self, event: tk.Event) -> None:
        """Handle key release events for autocompletion.

        Backspace clears the typed prefix; printable keys trigger
        completion attempt.
        """
        if event.keysym in ("BackSpace", "Delete"):
            return

        if event.keysym in ("Tab", "Right", "Return", "Escape", "Up", "Down"):
            return

        self._attempt_completion()

    # -- private helpers -----------------------------------------------------

    def _attempt_completion(self) -> None:
        """Try to autocomplete the current entry text."""
        current = self.get()
        cursor_pos = self.index(tk.INSERT)

        # Only autocomplete when cursor is at the end
        if cursor_pos != len(current):
            return

        if not current:
            return

        self._typed_prefix = current

        match = self._find_match(current)
        if match is None:
            return

        self.delete(0, tk.END)
        self.insert(0, match)
        self.icursor(len(current))
        self.select_range(len(current), tk.END)

    def _find_match(self, prefix: str) -> str | None:
        """Return the first completion candidate starting with *prefix*, or None."""
        lower_prefix = prefix.lower()
        for candidate in self._completion_list:
            if candidate.lower().startswith(lower_prefix):
                return candidate
        return None

    def _complete(self, event: tk.Event) -> str | None:
        """Accept the autocompleted text on Tab/Right."""
        try:
            current = self.get()
            sel_start = int(self.index(tk.SEL_FIRST))
            sel_end = int(self.index(tk.SEL_LAST))
            # Only consume if there is a selection (i.e. autocompleted part)
            if sel_start < len(current):
                self.delete(sel_start, sel_end)
                self.icursor(sel_start)
                return "break"
        except tk.TclError:
            pass
        return None


class BaseScreen(ttk.Frame):
    """Base class for all application screens.

    Every screen receives an ``app_context`` dict containing references
    to core managers and the main application window.

    Parameters
    ----------
    parent:
        Parent widget (the content area of MainApp).
    app_context:
        Dict with keys: ``config``, ``db``, ``inventory``, ``analytics``,
        ``reporting``, ``billing``, ``printer``, ``barcode``, ``watcher``,
        ``activity_logger``, ``updater``, ``app``.
    """

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent)
        self.app = app_context

    # -- lifecycle hooks -----------------------------------------------------

    def on_show(self) -> None:
        """Called when this screen becomes visible. Override in subclasses."""

    def focus_primary(self) -> None:
        """Focus the primary widget on this screen. Override in subclasses."""

    # -- helpers -------------------------------------------------------------

    def add_header(
        self,
        title: str,
        help_section: str | None = None,
    ) -> ttk.Frame:
        """Create a header frame with a title and optional help button.

        Args:
            title: Header text.
            help_section: If provided, a help button is added that calls
                ``app.show_help_section(help_section)``.

        Returns:
            The constructed header frame.
        """
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=12, pady=(8, 4))

        lbl = ttk.Label(header, text=title, font=("Segoe UI", 16, "bold"))
        lbl.pack(side=tk.LEFT)

        if help_section:
            help_btn = ttk.Button(
                header,
                text="?",
                width=3,
                command=lambda: self.app["app"].show_help_section(help_section),
            )
            help_btn.pack(side=tk.RIGHT)

        return header

    def _get_all_models(self) -> list[str]:
        """Return a sorted list of unique model names from the inventory."""
        inventory = self.app.get("inventory")
        if inventory is None:
            return []

        df: pd.DataFrame = getattr(inventory, "inventory_df", pd.DataFrame())
        if df.empty or "model" not in df.columns:
            return []

        return sorted(df["model"].dropna().unique().tolist())
