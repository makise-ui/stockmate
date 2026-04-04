"""Reusable custom widgets for StockMate."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

import ttkbootstrap as tb
from PIL import Image, ImageTk


class IconButton(tb.Button):
    """A themed button with an image and optional tooltip.

    Parameters
    ----------
    master:
        Parent widget.
    image:
        PIL ``Image`` or ``PhotoImage`` to display.
    command:
        Callback invoked on click.
    tooltip:
        Hover text shown via ttkbootstrap ``ToolTip``.
    bootstyle:
        ttkbootstrap style string.
    """

    def __init__(
        self,
        master: tk.Misc,
        image: Image.Image | tk.PhotoImage | None = None,
        command: Callable[[], None] | None = None,
        tooltip: str | None = None,
        bootstyle: str = "secondary-outline",
        **kwargs,
    ) -> None:
        super().__init__(master, command=command, bootstyle=bootstyle, **kwargs)
        self._tooltip: tb.ToolTip | None = None
        self._photo: tk.PhotoImage | None = None

        if image is not None:
            self._photo = self._to_photo(image)
            self.configure(image=self._photo)

        if tooltip:
            self._tooltip = tb.ToolTip(self, text=tooltip)

    # -- public API ----------------------------------------------------------

    def update_icon(self, new_image: Image.Image | tk.PhotoImage) -> None:
        """Replace the button's icon image.

        Args:
            new_image: Replacement image.
        """
        self._photo = self._to_photo(new_image)
        self.configure(image=self._photo)

    # -- private helpers -----------------------------------------------------

    @staticmethod
    def _to_photo(image: Image.Image | tk.PhotoImage) -> tk.PhotoImage:
        """Convert a PIL ``Image`` to a ``PhotoImage``, or pass through."""
        if isinstance(image, Image.Image):
            return ImageTk.PhotoImage(image)
        return image


class CollapsibleFrame(ttk.Frame):
    """A frame whose visibility can be toggled.

    The frame uses ``pack`` internally for show/hide.  Call ``show()``,
    ``hide()``, or ``toggle()`` to manage visibility.
    """

    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._is_expanded = False

    # -- public API ----------------------------------------------------------

    @property
    def is_expanded(self) -> bool:
        """Return whether the frame is currently visible."""
        return self._is_expanded

    def show(self, **pack_opts) -> None:
        """Make the frame visible.

        Additional keyword arguments are forwarded to ``pack()``.
        """
        if not self._is_expanded:
            self._is_expanded = True
            self.pack(**pack_opts) if pack_opts else self.pack()

    def hide(self) -> None:
        """Hide the frame."""
        if self._is_expanded:
            self._is_expanded = False
            self.pack_forget()

    def toggle(self, **pack_opts) -> None:
        """Flip visibility.

        Additional keyword arguments are forwarded to ``pack()`` when showing.
        """
        if self._is_expanded:
            self.hide()
        else:
            self.show(**pack_opts)
