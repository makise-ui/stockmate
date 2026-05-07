"""Help screen for StockMate.

Provides a Markdown-rendered help viewer with navigation to different sections.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from gui.base import BaseScreen
from gui.markdown_renderer import MarkdownText
from gui.screens.help_content import HELP_SECTIONS


class HelpScreen(BaseScreen):
    """Simple help screen with section navigation."""

    NAV_ITEMS: list[tuple[str, str]] = [
        ("📋  Index", "index"),
        ("🚀  Getting Started", "getting_started"),
        ("📦  Inventory Screen", "inventory_screen"),
        ("⚡  Quick Entry", "quick_entry"),
        ("🔄  Quick Status", "quick_status"),
        ("🔍  Search & Details", "search_details"),
        ("✏️  Bulk Edit", "bulk_edit"),
        ("💰  Billing & Invoice", "billing_invoice"),
        ("🏷️  Label Designer", "label_designer"),
        ("📊  Analytics Dashboard", "analytics_dashboard"),
        ("📈  Reporting", "reporting"),
        ("📱  Manual Scan", "manual_scan"),
        ("⚙️  Settings", "settings"),
        ("📁  Manage Files", "manage_files"),
        ("📝  Manage Data", "manage_data"),
        ("⚠️  Conflicts", "conflicts"),
        ("📄  File Formats", "file_formats"),
        ("🔧  Troubleshooting", "troubleshooting"),
    ]

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)
        self._text: tk.Text | None = None
        self._nav_listbox: tk.Listbox | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        """Construct the help interface with a navigation sidebar."""
        self.add_header("Help")

        main_container = ttk.Frame(self)
        main_container.pack(fill=tk.BOTH, expand=True)

        self._build_nav_panel(main_container)
        self._build_content_panel(main_container)

        self._show_section("index")

    def _build_nav_panel(self, parent: ttk.Frame) -> None:
        """Build the left-side navigation panel with clickable section list."""
        nav_frame = ttk.Frame(parent, width=200)
        nav_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(12, 0), pady=8)
        nav_frame.pack_propagate(False)

        nav_label = ttk.Label(nav_frame, text="Topics", font=("", 10, "bold"))
        nav_label.pack(anchor=tk.W, padx=4, pady=(0, 4))

        listbox_frame = ttk.Frame(nav_frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True)

        self._nav_listbox = tk.Listbox(
            listbox_frame,
            font=("", 9),
            selectmode=tk.SINGLE,
            activestyle="none",
            exportselection=False,
        )
        nav_scrollbar = ttk.Scrollbar(
            listbox_frame,
            orient=tk.VERTICAL,
            command=self._nav_listbox.yview,
        )
        self._nav_listbox.configure(yscrollcommand=nav_scrollbar.set)

        self._nav_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        nav_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for display_name, _section_key in self.NAV_ITEMS:
            self._nav_listbox.insert(tk.END, display_name)

        self._nav_listbox.bind("<<ListboxSelect>>", self._on_nav_select)

    def _build_content_panel(self, parent: ttk.Frame) -> None:
        """Build the right-side content panel with MarkdownText viewer."""
        content_frame = ttk.Frame(parent)
        content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=12, pady=8)

        self._text = MarkdownText(content_frame)
        scrollbar = ttk.Scrollbar(
            content_frame,
            orient=tk.VERTICAL,
            command=self._text.yview,
        )
        self._text.configure(yscrollcommand=scrollbar.set)

        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_nav_select(self, _event: tk.Event) -> None:
        """Handle navigation listbox selection change."""
        if self._nav_listbox is None:
            return

        selection = self._nav_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        if index < len(self.NAV_ITEMS):
            section_key = self.NAV_ITEMS[index][1]
            self._show_section(section_key)

    def _show_section(self, section: str) -> None:
        """Display the help content for the given section."""
        if self._text is None:
            return

        content = self._get_content(section)

        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.insert_markdown("1.0", content)
        self._text.configure(state=tk.DISABLED)

        self._sync_nav_selection(section)

    def _sync_nav_selection(self, section: str) -> None:
        """Highlight the navigation item matching the current section."""
        if self._nav_listbox is None:
            return

        for index, (_display_name, key) in enumerate(self.NAV_ITEMS):
            if key == section:
                self._nav_listbox.selection_clear(0, tk.END)
                self._nav_listbox.selection_set(index)
                self._nav_listbox.see(index)
                return

    def navigate_to(self, section: str) -> None:
        """Navigate to a help section. Called by MainApp.show_help_section."""
        self._show_section(section)

    def _get_content(self, section: str) -> str:
        """Return help text for the requested section."""
        return HELP_SECTIONS.get(section, HELP_SECTIONS["index"])

    def on_show(self) -> None:
        """No data refresh needed for help."""

    def focus_primary(self) -> None:
        """No primary focus target for help screen."""
