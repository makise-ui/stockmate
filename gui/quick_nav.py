"""Quick navigation overlay — command palette for StockMate."""

from __future__ import annotations

import tkinter as tk
from typing import Callable


ICON_MAP: dict[str, str] = {
    "dashboard": "📊",
    "inventory": "📱",
    "billing": "🧾",
    "quick_entry": "⚡",
    "search": "🔍",
    "status": "📋",
    "analytics": "📈",
    "invoices": "📂",
    "designer": "🏷️",
    "files": "📁",
    "managedata": "💾",
    "settings": "⚙️",
    "edit": "✏️",
    "help": "❓",
    "reporting": "📊",
    "manual_scan": "📷",
    "activity": "📜",
    "conflicts": "⚠️",
}


class QuickNavOverlay(tk.Toplevel):
    """Frameless command palette triggered by Ctrl+N / Ctrl+W.

    Displays a scrollable grid of navigation cards with emoji icons.
    Supports keyboard navigation (arrows, Enter, Escape) and mouse clicks.

    Parameters
    ----------
    parent:
        Parent window (used for centering).
    screens_map:
        Dict mapping navigation keys to display labels, e.g.
        ``{"inventory": "Inventory", "billing": "Billing"}``.
    callback:
        Called with the selected key when a card is activated.
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        screens_map: dict[str, str],
        callback: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self._callback = callback
        self._screens_map = screens_map
        self._selected_index: int = 0
        self._card_widgets: list[tk.Frame] = []

        self._build_ui()
        self._center_on_parent(parent)
        self._bind_keys()
        self._highlight_card(0)

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the overlay UI."""
        self.overrideredirect(True)
        self.attributes("-alpha", 0.95)
        self.attributes("-topmost", True)
        self.configure(bg="#2b2b2b")

        # Main container
        main = tk.Frame(self, bg="#2b2b2b")
        main.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        # Title
        title_lbl = tk.Label(
            main,
            text="Quick Navigation",
            font=("Segoe UI", 14, "bold"),
            fg="#ffffff",
            bg="#2b2b2b",
        )
        title_lbl.pack(anchor=tk.W, pady=(0, 12))

        # Scrollable canvas
        canvas = tk.Canvas(main, bg="#2b2b2b", highlightthickness=0)
        scrollbar = tk.Scrollbar(main, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg="#2b2b2b")

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        canvas.create_window((0, 0), window=scroll_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 3-column card grid
        self._build_cards(scroll_frame)

    def _build_cards(self, parent: tk.Frame) -> None:
        """Build navigation cards in a 3-column grid."""
        keys = list(self._screens_map.keys())
        cols = 3

        for idx, key in enumerate(keys):
            row = idx // cols
            col = idx % cols
            label = self._screens_map[key]
            icon = ICON_MAP.get(key, "📄")

            card = self._create_card(parent, icon, label, key)
            card.grid(row=row, column=col, padx=6, pady=6, sticky=tk.NSEW)
            self._card_widgets.append(card)

        # Make columns expand equally
        for c in range(cols):
            parent.grid_columnconfigure(c, weight=1)

    def _create_card(
        self,
        parent: tk.Frame,
        icon: str,
        label: str,
        key: str,
    ) -> tk.Frame:
        """Create a single navigation card.

        Args:
            parent: Parent frame.
            icon: Emoji icon string.
            label: Display text.
            key: Navigation key for callback.

        Returns:
            The card frame widget.
        """
        card = tk.Frame(parent, bg="#3c3c3c", cursor="hand2")
        card._nav_key = key  # type: ignore[attr-defined]

        icon_lbl = tk.Label(card, text=icon, font=("Segoe UI Emoji", 24), bg="#3c3c3c")
        icon_lbl.pack(pady=(10, 2))

        text_lbl = tk.Label(
            card,
            text=label,
            font=("Segoe UI", 11),
            fg="#ffffff",
            bg="#3c3c3c",
        )
        text_lbl.pack(pady=(0, 10))

        # Store references for style updates
        card._icon_lbl = icon_lbl  # type: ignore[attr-defined]
        card._text_lbl = text_lbl  # type: ignore[attr-defined]

        card.bind("<Button-1>", lambda e: self._activate(key))
        icon_lbl.bind("<Button-1>", lambda e: self._activate(key))
        text_lbl.bind("<Button-1>", lambda e: self._activate(key))

        return card

    # -- layout --------------------------------------------------------------

    def _center_on_parent(self, parent: tk.Tk | tk.Toplevel) -> None:
        """Center the overlay on the parent window."""
        width = 800
        height = 500

        parent.update_idletasks()
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        ph = parent.winfo_height()

        x = px + (pw - width) // 2
        y = py + (ph - height) // 2

        self.geometry(f"{width}x{height}+{x}+{y}")

    # -- interaction ---------------------------------------------------------

    def _bind_keys(self) -> None:
        """Bind keyboard navigation."""
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Up>", self._navigate_up)
        self.bind("<Down>", self._navigate_down)
        self.bind("<Left>", self._navigate_left)
        self.bind("<Right>", self._navigate_right)
        self.bind("<Return>", self._activate_selected)

    def _navigate_up(self, event: tk.Event) -> str | None:
        """Move selection up one row."""
        cols = 3
        new = self._selected_index - cols
        if new >= 0:
            self._highlight_card(new)
        return "break"

    def _navigate_down(self, event: tk.Event) -> str | None:
        """Move selection down one row."""
        cols = 3
        new = self._selected_index + cols
        if new < len(self._card_widgets):
            self._highlight_card(new)
        return "break"

    def _navigate_left(self, event: tk.Event) -> str | None:
        """Move selection left one column."""
        new = self._selected_index - 1
        if new >= 0:
            self._highlight_card(new)
        return "break"

    def _navigate_right(self, event: tk.Event) -> str | None:
        """Move selection right one column."""
        new = self._selected_index + 1
        if new < len(self._card_widgets):
            self._highlight_card(new)
        return "break"

    def _activate_selected(self, event: tk.Event) -> str | None:
        """Activate the currently selected card."""
        if 0 <= self._selected_index < len(self._card_widgets):
            key = self._card_widgets[self._selected_index]._nav_key  # type: ignore[attr-defined]
            self._activate(key)
        return "break"

    def _highlight_card(self, index: int) -> None:
        """Highlight the card at *index* and unhighlight others."""
        self._selected_index = index

        for i, card in enumerate(self._card_widgets):
            if i == index:
                card.configure(bg="#007acc")
                card._icon_lbl.configure(bg="#007acc")  # type: ignore[attr-defined]
                card._text_lbl.configure(bg="#007acc", fg="#ffffff")  # type: ignore[attr-defined]
            else:
                card.configure(bg="#3c3c3c")
                card._icon_lbl.configure(bg="#3c3c3c")  # type: ignore[attr-defined]
                card._text_lbl.configure(bg="#3c3c3c", fg="#ffffff")  # type: ignore[attr-defined]

    def _activate(self, key: str) -> None:
        """Fire the callback and close the overlay."""
        self.destroy()
        self._callback(key)
