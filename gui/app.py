"""Main application window for StockMate."""

from __future__ import annotations

import logging
import os
import sys
import tkinter as tk
from tkinter import ttk
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import ttkbootstrap as tb
from ttkbootstrap.dialogs import Messagebox

from core.analytics import AnalyticsManager
from core.barcode_utils import BarcodeGenerator
from core.billing import BillingManager
from core.config import ConfigManager
from core.constants import ACTION_RELOAD, ACTION_RESOLVE_CONFLICT
from core.database import SQLiteDatabase
from core.inventory import InventoryManager
from core.printer import PrinterManager
from core.reporting import ReportGenerator
from core.updater import UpdateChecker
from core.version import APP_VERSION
from core.watcher import InventoryWatcher

from gui.dialogs import (
    ConflictResolutionDialog,
    SplashScreen,
    WelcomeDialog,
)
from gui.quick_nav import QuickNavOverlay
from gui.toast import show_toast

# Screen imports
from gui.screens.analytics import (
    ActivityLogScreen,
    AnalyticsScreen,
    ConflictScreen,
    DashboardScreen,
)
from gui.screens.billing import BillingScreen, InvoiceHistoryScreen
from gui.screens.inventory import InventoryScreen
from gui.screens.manual_scan import ManualScanScreen
from gui.screens.ops import EditDataScreen, SearchScreen, StatusScreen
from gui.screens.reporting import ReportingScreen
from gui.screens.settings import ManageDataScreen, ManageFilesScreen, SettingsScreen
from gui.screens.help import HelpScreen
from gui.quick_entry import QuickEntryScreen
from gui.zpl_designer import ZPLDesignerScreen

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight activity logger (no external dependency)
# ---------------------------------------------------------------------------


class ActivityLogger:
    """Simple in-memory activity logger with optional file output."""

    def __init__(self, log_path: str | None = None) -> None:
        self._log_path = log_path
        self._entries: list[dict[str, str]] = []

    def log(self, action: str, details: str) -> None:
        """Record an activity entry."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details,
        }
        self._entries.append(entry)

    def info(self, message: str) -> None:
        """Log an informational message."""
        self.log("INFO", message)

    def get_entries(self) -> list[dict[str, str]]:
        """Return all log entries."""
        return list(self._entries)


# ---------------------------------------------------------------------------
# PyInstaller resource path helper
# ---------------------------------------------------------------------------


def _resource_path(relative: str) -> str:
    """Return the absolute path to a bundled resource.

    Handles PyInstaller's ``sys._MEIPASS`` temp directory.
    """
    try:
        base = sys._MEIPASS  # type: ignore[attr-defined]
    except AttributeError:
        base = os.path.abspath(".")
    return os.path.join(base, relative)


# ---------------------------------------------------------------------------
# MainApp
# ---------------------------------------------------------------------------


class MainApp(tb.Window):
    """Main application window for StockMate.

    Orchestrates all core managers, screens, and the navigation chrome.
    """

    def __init__(self) -> None:
        # 1. Load config, resolve theme
        self._config = ConfigManager()
        theme = self._config.get("theme_name", "cosmo")

        # 2. Create themed window
        super().__init__(themename=theme)
        store_name = self._config.get("store_name", "Mobile Shop")
        self.title(f"{store_name} — StockMate v{APP_VERSION}")
        self.geometry("1100x700")
        self.minsize(900, 600)

        # 3. Bind global shortcuts
        self._bind_shortcuts()

        # 4. No license check in this version

        # 5. Start application
        self._start_application()

    # -- startup -------------------------------------------------------------

    def _start_application(self) -> None:
        """Initialize core managers and build the UI."""
        store_name = self._config.get("store_name", "Mobile Shop")

        # Show splash
        splash = SplashScreen(self, store_name)
        splash.update_progress("Loading database...", 10)

        # Initialize database
        self._db = SQLiteDatabase()
        splash.update_progress("Database ready", 20)

        # Initialize activity logger
        self._activity_logger = ActivityLogger()
        splash.update_progress("Activity logger ready", 25)

        # Initialize inventory manager
        self._inventory = InventoryManager(
            db=self._db,
            config_manager=self._config,
            activity_logger=self._activity_logger,
        )
        splash.update_progress("Inventory manager ready", 40)

        # Initialize barcode generator
        try:
            self._barcode = BarcodeGenerator(self._config)
        except Exception:
            self._barcode = None
        splash.update_progress("Barcode generator ready", 50)

        # Initialize printer manager
        self._printer = PrinterManager(self._config)
        splash.update_progress("Printer manager ready", 55)

        # Initialize billing manager
        self._billing = BillingManager(
            config_manager=self._config,
            activity_logger=self._activity_logger,
        )
        splash.update_progress("Billing manager ready", 60)

        # Initialize analytics manager
        self._analytics = AnalyticsManager(inventory_manager=self._inventory)
        splash.update_progress("Analytics ready", 70)

        # Initialize report generator
        self._reporting = ReportGenerator(inventory_manager=self._inventory)
        splash.update_progress("Reporting ready", 75)

        # Start file watcher (needed before UI build — screens reference it)
        self._watcher = InventoryWatcher(
            inventory_manager=self._inventory,
            config_manager=self._config,
        )
        self._watcher.start()
        splash.update_progress("File watcher started", 80)

        # Initialize updater placeholder (real instance created in _finish_init)
        self._updater = None

        # Build UI
        self._init_layout()
        splash.update_progress("UI built", 85)

        # Load inventory
        self._inventory.reload_all()
        splash.update_progress("Inventory loaded", 90)

        # Finish initialization after a brief delay
        self.after(600, lambda: self._finish_init(splash))

    def _finish_init(self, splash: SplashScreen) -> None:
        """Complete startup: destroy splash, check updates, show welcome."""
        splash.destroy()
        self.deiconify()

        # Check for updates
        self._updater = UpdateChecker(current_version=APP_VERSION)
        self._updater.check_for_updates()  # async-ish; callback via _on_update_found

        # Show welcome dialog if no mappings exist
        if not self._config.mappings:
            WelcomeDialog(self, on_choice=self._handle_welcome_choice)

    def _handle_welcome_choice(self, choice: str) -> None:
        """Handle the user's selection from the welcome dialog."""
        if choice == "add_excel":
            self._add_excel_file()
        elif choice == "guide":
            self.show_help_section("guide")
        # "explore" — do nothing, let user navigate

    # -- layout --------------------------------------------------------------

    def _init_layout(self) -> None:
        """Build the main application layout."""
        # Top navigation bar
        self._build_top_nav()

        # Content area
        self._content_area = ttk.Frame(self)
        self._content_area.pack(fill=tk.BOTH, expand=True)

        # Build screens
        self._build_screens()

        # Status bar
        self._build_status_bar()

        # Show default screen
        self.show_screen("dashboard")

    def _build_top_nav(self) -> None:
        """Build the top navigation bar."""
        nav_bar = ttk.Frame(self, bootstyle="primary")
        nav_bar.pack(fill=tk.X, side=tk.TOP)

        # App title
        store_name = self._config.get("store_name", "Mobile Shop")
        ttk.Label(
            nav_bar,
            text=f"  {store_name}",
            font=("Segoe UI", 12, "bold"),
            bootstyle="inverse-primary",
        ).pack(side=tk.LEFT, padx=4)

        # Nav buttons
        nav_buttons = [
            ("Inventory", "inventory", "primary-outline"),
            ("Search", "search", "info-outline"),
            ("Quick Status", "status", "secondary-outline"),
            ("Quick Entry", "quick_entry", "success-outline"),
            ("Billing", "billing", "warning-outline"),
            ("Dashboard", "dashboard", "dark-outline"),
        ]

        for label, key, style in nav_buttons:
            btn = ttk.Button(
                nav_bar,
                text=label,
                bootstyle=style,
                command=lambda k=key: self.show_screen(k),
            )
            btn.pack(side=tk.LEFT, padx=2, pady=4)

        # Reports menubutton
        reports_mb = ttk.Menubutton(nav_bar, text="Reports", bootstyle="light-outline")
        reports_menu = tk.Menu(reports_mb, tearoff=False)
        reports_menu.add_command(
            label="Analytics", command=lambda: self.show_screen("analytics")
        )
        reports_menu.add_command(
            label="Advanced Reporting", command=lambda: self.show_screen("reporting")
        )
        reports_menu.add_command(
            label="Manual Scan", command=lambda: self.show_screen("manual_scan")
        )
        reports_menu.add_command(
            label="Invoice History", command=lambda: self.show_screen("invoices")
        )
        reports_menu.add_command(
            label="Activity Logs", command=lambda: self.show_screen("activity")
        )
        reports_mb.configure(menu=reports_menu)
        reports_mb.pack(side=tk.LEFT, padx=2, pady=4)

        # Edit/More menubutton
        edit_mb = ttk.Menubutton(nav_bar, text="Edit / More", bootstyle="light-outline")
        edit_menu = tk.Menu(edit_mb, tearoff=False)
        edit_menu.add_command(
            label="Edit Mobile Data", command=lambda: self.show_screen("edit")
        )
        edit_mb.configure(menu=edit_menu)
        edit_mb.pack(side=tk.LEFT, padx=2, pady=4)

        # Manage menubutton
        manage_mb = ttk.Menubutton(nav_bar, text="Manage", bootstyle="light-outline")
        manage_menu = tk.Menu(manage_mb, tearoff=False)
        manage_menu.add_command(
            label="Manage Files", command=lambda: self.show_screen("files")
        )
        manage_menu.add_command(
            label="Manage Data", command=lambda: self.show_screen("managedata")
        )
        manage_menu.add_command(
            label="Label Designer", command=lambda: self.show_screen("designer")
        )
        manage_menu.add_command(
            label="Conflicts", command=lambda: self.show_screen("conflicts")
        )
        manage_menu.add_separator()
        manage_menu.add_command(label="Settings", command=self._open_settings)
        manage_menu.add_command(
            label="Help", command=lambda: self.show_help_section("index")
        )
        manage_mb.configure(menu=manage_menu)
        manage_mb.pack(side=tk.LEFT, padx=2, pady=4)

        # Right side: refresh + update buttons
        self._update_btn = ttk.Button(
            nav_bar,
            text="Update Available",
            bootstyle="danger-outline",
            command=self._show_update_dialog,
        )
        self._update_btn.pack(side=tk.RIGHT, padx=4, pady=4)
        self._update_btn.pack_forget()  # hidden initially

        self._refresh_btn = ttk.Button(
            nav_bar,
            text="↻ Refresh",
            bootstyle="light-outline",
            command=self.manual_refresh,
        )
        self._refresh_btn.pack(side=tk.RIGHT, padx=4, pady=4)

    def _build_screens(self) -> None:
        """Initialize all screen instances."""
        app_context = {
            "config": self._config,
            "db": self._db,
            "inventory": self._inventory,
            "analytics": self._analytics,
            "reporting": self._reporting,
            "billing": self._billing,
            "printer": self._printer,
            "barcode": self._barcode,
            "watcher": self._watcher,
            "activity_logger": self._activity_logger,
            "updater": self._updater,
            "app": self,
        }

        self.screens: dict[str, Any] = {
            "dashboard": DashboardScreen(self._content_area, app_context),
            "inventory": InventoryScreen(self._content_area, app_context),
            "search": SearchScreen(self._content_area, app_context),
            "status": StatusScreen(self._content_area, app_context),
            "quick_entry": QuickEntryScreen(self._content_area, app_context),
            "billing": BillingScreen(self._content_area, app_context),
            "analytics": AnalyticsScreen(self._content_area, app_context),
            "reporting": ReportingScreen(self._content_area, app_context),
            "manual_scan": ManualScanScreen(self._content_area, app_context),
            "invoices": InvoiceHistoryScreen(self._content_area, app_context),
            "activity": ActivityLogScreen(self._content_area, app_context),
            "files": ManageFilesScreen(self._content_area, app_context),
            "managedata": ManageDataScreen(self._content_area, app_context),
            "designer": ZPLDesignerScreen(self._content_area, app_context),
            "settings": SettingsScreen(self._content_area, app_context),
            "help": HelpScreen(self._content_area, app_context),
            "edit": EditDataScreen(self._content_area, app_context),
            "conflicts": ConflictScreen(self._content_area, app_context),
        }

    def _build_status_bar(self) -> None:
        """Build the bottom status bar."""
        self._status_bar = ttk.Frame(self, bootstyle="secondary")
        self._status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self._status_text = tk.StringVar(value="Ready")
        ttk.Label(
            self._status_bar,
            textvariable=self._status_text,
            bootstyle="inverse-secondary",
        ).pack(side=tk.LEFT, padx=8, pady=2)

        self._item_count_text = tk.StringVar(value="")
        ttk.Label(
            self._status_bar,
            textvariable=self._item_count_text,
            bootstyle="inverse-secondary",
        ).pack(side=tk.RIGHT, padx=8, pady=2)

        self._update_status_bar()

    # -- navigation ----------------------------------------------------------

    def show_screen(self, key: str) -> None:
        """Hide all screens and show the target screen.

        Args:
            key: Screen identifier.
        """
        screen = self.screens.get(key)
        if screen is None:
            return

        for s in self.screens.values():
            s.pack_forget()

        screen.pack(fill=tk.BOTH, expand=True)

        # Call lifecycle hooks
        if hasattr(screen, "on_show"):
            screen.on_show()
        if hasattr(screen, "focus_primary"):
            screen.focus_primary()

    def open_quick_nav(self, event: tk.Event | None = None) -> None:
        """Show the quick navigation overlay."""
        screens_map = {
            "dashboard": "Dashboard",
            "inventory": "Inventory",
            "billing": "Billing",
            "quick_entry": "Quick Entry",
            "search": "Search",
            "status": "Quick Status",
            "analytics": "Analytics",
            "invoices": "Invoice History",
            "designer": "Label Designer",
            "files": "Manage Files",
            "managedata": "Manage Data",
            "settings": "Settings",
            "edit": "Edit Mobile Data",
            "help": "Help",
            "reporting": "Advanced Reporting",
            "manual_scan": "Manual Scan",
            "activity": "Activity Logs",
            "conflicts": "Conflicts",
        }
        QuickNavOverlay(self, screens_map, callback=self.show_screen)

    def switch_to_billing(self, items: list[dict[str, Any]]) -> None:
        """Add items to the billing screen and switch to it.

        Args:
            items: List of item dicts to add to billing.
        """
        billing_screen = self.screens.get("billing")
        if billing_screen is not None:
            if hasattr(billing_screen, "add_items"):
                billing_screen.add_items(items)
        self.show_screen("billing")

    def show_help_section(self, section: str) -> None:
        """Show the help screen, optionally navigating to a section.

        Args:
            section: Help section identifier.
        """
        self.show_screen("help")
        help_screen = self.screens.get("help")
        if help_screen is not None and hasattr(help_screen, "navigate_to"):
            help_screen.navigate_to(section)

    # -- refresh -------------------------------------------------------------

    def manual_refresh(self) -> None:
        """Manually reload inventory and refresh the UI."""
        self._status_text.set("Refreshing inventory...")
        self.update_idletasks()

        self._inventory.reload_all()
        self._refresh_watch_list()
        self._refresh_ui()

        self._status_text.set("Refresh complete")

    def _refresh_watch_list(self) -> None:
        """Restart the file watcher with updated file list."""
        self._watcher.stop()
        self._watcher.start()

    def _refresh_ui(self) -> None:
        """Refresh visible screens and check for conflicts."""
        # Refresh inventory screen
        inv_screen = self.screens.get("inventory")
        if inv_screen is not None and hasattr(inv_screen, "refresh_data"):
            inv_screen.refresh_data()

        # Refresh dashboard
        dash_screen = self.screens.get("dashboard")
        if dash_screen is not None and hasattr(dash_screen, "refresh"):
            dash_screen.refresh()

        # Check conflicts
        self._check_conflicts()

        self._update_status_bar()

    # -- watcher callback ----------------------------------------------------

    def _on_inventory_update(self) -> None:
        """Called by the file watcher when a mapped file changes.

        Schedules a UI refresh on the main thread.
        """
        self.after(0, self._refresh_ui)

    # -- conflicts -----------------------------------------------------------

    def _check_conflicts(self) -> None:
        """Show conflict resolution dialog if conflicts exist."""
        conflicts = self._inventory.conflicts
        if not conflicts:
            return

        for conflict in conflicts:
            ConflictResolutionDialog(
                self,
                conflict_data=conflict,
                on_resolve=self._resolve_conflict_callback,
            )

    def _resolve_conflict_callback(
        self, conflict_data: dict[str, Any], action: str
    ) -> None:
        """Resolve a conflict and recheck for remaining conflicts.

        Args:
            conflict_data: The conflict that was resolved.
            action: Resolution action (``"merge"`` or ``"ignore"``).
        """
        if action == "merge":
            rows = conflict_data.get("rows", [])
            if len(rows) < 2:
                return

            keep_id = rows[0].get(FIELD_UNIQUE_ID)
            hide_ids = [r.get(FIELD_UNIQUE_ID) for r in rows[1:]]

            if keep_id is not None and hide_ids:
                self._inventory.resolve_conflict(
                    keep_id=int(keep_id),
                    hide_ids=[int(h) for h in hide_ids],
                    reason="User merged via conflict dialog",
                )
                self._activity_logger.log(
                    ACTION_RESOLVE_CONFLICT,
                    f"Merged conflict for IMEI {conflict_data.get('imei', 'N/A')}",
                )

        # Recheck for remaining conflicts
        self._check_conflicts()

    # -- updates -------------------------------------------------------------

    def _on_update_found(self, available: bool, tag: str = "", notes: str = "") -> None:
        """Show the update button in the nav bar if an update is available.

        Args:
            available: Whether an update was found.
            tag: Version tag of the update.
            notes: Release notes.
        """
        if available:
            self._update_btn.configure(text=f"Update to {tag}")
            self._update_btn.pack(side=tk.RIGHT, padx=4, pady=4)
            self._pending_update = {"tag": tag, "notes": notes}

    def _show_update_dialog(self) -> None:
        """Show the update download dialog with progress."""
        update_info = getattr(self, "_pending_update", None)
        if update_info is None:
            self.show_toast("No Updates", "You are running the latest version.", "info")
            return

        tag = update_info.get("tag", "")
        notes = update_info.get("notes", "")

        response = Messagebox.okcancel(
            title=f"Update Available — {tag}",
            message=f"Release notes:\n\n{notes}\n\nDownload and install?",
        )

        if response == "OK":
            self._download_and_install_update()

    def _download_and_install_update(self) -> None:
        """Download the update and restart to install."""
        update_info = getattr(self, "_pending_update", None)
        if update_info is None:
            return

        self._status_text.set("Downloading update...")
        self.update_idletasks()

        # Download would happen here; for now just show toast
        self.show_toast("Update", "Update download started.", "info")

    # -- misc ----------------------------------------------------------------

    def show_toast(self, title: str, message: str, kind: str = "info") -> None:
        """Show a toast notification.

        Args:
            title: Toast title.
            message: Toast body text.
            kind: Toast style — ``"success"``, ``"warning"``, ``"danger"``, ``"info"``.
        """
        show_toast(title, message, kind=kind)  # type: ignore[arg-type]

    def _open_settings(self) -> None:
        """Open the settings dialog."""
        from gui.dialogs import SettingsDialog

        SettingsDialog(self, self._config)

    def _add_excel_file(self) -> None:
        """Open file dialog to add an Excel file."""
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

        # Check if already mapped
        existing = self._config.get_file_mapping(file_path)
        if existing:
            self.show_toast("Already Mapped", "This file is already mapped.", "warning")
            return

        # Open column mapping dialog
        from gui.dialogs import MapColumnsDialog

        MapColumnsDialog(
            self,
            file_path=file_path,
            on_save_callback=self._save_mapping,
        )

    def _save_mapping(self, key: str, save_data: dict) -> None:
        """Save a file mapping and reload inventory.

        Args:
            key: Composite key for the mapping.
            save_data: Mapping data dict.
        """
        self._config.set_file_mapping(key, save_data)
        self._inventory.reload_all()
        self._refresh_watch_list()
        self._update_status_bar()
        self._refresh_ui()
        self.show_toast("File Mapped", "Excel file mapped successfully.", "success")

    def _update_status_bar(self) -> None:
        """Update the status bar with current inventory stats."""
        df = getattr(self._inventory, "inventory_df", None)
        if df is not None and not df.empty:
            count = len(df)
            self._item_count_text.set(f"{count} items loaded")
        else:
            self._item_count_text.set("No inventory loaded")

    # -- shortcuts -----------------------------------------------------------

    def _bind_shortcuts(self) -> None:
        """Bind global keyboard shortcuts."""
        self.bind("<Control-n>", self.open_quick_nav)
        self.bind("<Control-w>", self.open_quick_nav)
        self.bind("<F1>", lambda e: self.show_screen("inventory"))
        self.bind("<F2>", lambda e: self.show_screen("search"))
        self.bind("<F3>", lambda e: self.show_screen("status"))
        self.bind("<F4>", lambda e: self.show_screen("quick_entry"))
        self.bind("<F5>", lambda e: self.show_screen("billing"))
        self.bind("<Escape>", lambda e: self.show_screen("dashboard"))

    # -- shutdown ------------------------------------------------------------

    def on_close(self) -> None:
        """Clean up resources and close the application."""
        # Stop file watcher
        self._watcher.stop()

        # Shutdown inventory (drain write queue)
        self._inventory.shutdown()

        # Close database
        self._db.close()

        self.destroy()
