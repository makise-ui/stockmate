# StockMate — Project Context

## Project Overview

StockMate is a comprehensive desktop application for mobile phone retail shop inventory management, billing, and analytics. It is built with Python using Tkinter (via `ttkbootstrap`) for the GUI, SQLite for persistent metadata storage, and Excel/CSV files as the primary data source for inventory tracking.

### Key Capabilities
- **Inventory Management** — Excel-backed stock tracking with SQLite metadata, IMEI deduplication, and conflict resolution
- **Quick Entry** — High-speed data entry with IMEI scanning and auto-fetch
- **Quick Status** — Fast IN/OUT/RTN status updates via barcode scanning
- **Billing & Invoices** — GST-compliant invoice generation with PDF output
- **Label Design** — Drag-and-drop ZPL label designer with thermal printer support
- **Analytics** — Stock value, demand forecasting, brand distribution
- **Advanced Reporting** — Filter builder with AND/OR/XOR logic, export to Excel/PDF/Word
- **File Watching** — Auto-reload when mapped Excel files change externally (via `watchdog`)

## Architecture

The codebase is organized into three main packages:

```
stockmate/
├── main.py              # Entry point — launches gui.app.MainApp
├── core/                # Business logic & data layer
│   ├── database.py      # SQLite database (items, metadata, history tables)
│   ├── inventory.py     # InventoryManager — loads/merges Excel, normalizes, syncs to DB
│   ├── config.py        # ConfigManager — JSON-based app config & file mappings
│   ├── constants.py     # Status, action, and field canonical names
│   ├── analytics.py     # AnalyticsManager — stock value, forecasting, brand stats
│   ├── billing.py       # BillingManager — cart, invoice generation, PDF output
│   ├── barcode_utils.py # Barcode generation utilities
│   ├── printer.py       # PrinterManager — ZPL thermal printing
│   ├── reporting.py     # ReportGenerator — advanced filtering, multi-format export
│   ├── scraper.py       # Web scraping for device data auto-fetch
│   ├── updater.py       # UpdateChecker — GitHub release checking
│   ├── utils.py         # General utilities
│   ├── watcher.py       # InventoryWatcher — file watcher for mapped Excel changes
│   ├── zpl_server.py    # ZPL label server
│   ├── ai_manager.py    # AI manager (optional feature)
│   └── version.py       # APP_VERSION constant
├── gui/                 # Presentation layer (Tkinter + ttkbootstrap)
│   ├── app.py           # MainApp — orchestrates managers, screens, navigation
│   ├── base.py          # Base screen class
│   ├── dialogs.py       # Common dialogs (settings, column mapping, conflicts, etc.)
│   ├── quick_entry.py   # QuickEntryScreen
│   ├── quick_nav.py     # QuickNavOverlay (Ctrl+N)
│   ├── zpl_designer.py  # ZPLDesignerScreen
│   ├── toast.py         # Toast notifications
│   ├── widgets.py       # Reusable widget components
│   ├── markdown_renderer.py  # Markdown rendering for help
│   ├── ai_auth_dialog.py     # AI authentication dialog
│   └── screens/         # Individual screen modules
│       ├── inventory.py # InventoryScreen — main stock table
│       ├── ops.py       # SearchScreen, StatusScreen, EditDataScreen
│       ├── billing.py   # BillingScreen, InvoiceHistoryScreen
│       ├── analytics.py # AnalyticsScreen, DashboardScreen, ConflictScreen, ActivityLogScreen
│       ├── reporting.py # ReportingScreen — advanced filter builder
│       ├── settings.py  # SettingsScreen, ManageFilesScreen, ManageDataScreen
│       ├── help.py      # HelpScreen
│       ├── manual_scan.py # ManualScanScreen
│       └── ai_chat.py   # AI chat screen
├── tests/               # Unit tests
├── config/              # Static config assets (e.g., custom_template.zpl)
└── zpl-designer/        # ZPL designer assets
```

### Data Flow

1. **Loading**: Mapped Excel/CSV files are read via `pandas` → normalized to canonical schema → `unique_id` assigned via `SQLiteDatabase.get_or_create_id()` → merged into `inventory_df`
2. **Persistence**: SQLite stores metadata (status, buyer, notes, sold_date) alongside the Excel data. The Excel file is the source of truth for inventory rows; SQLite is the source of truth for state changes.
3. **Sync**: A background write queue (`write_queue` + daemon thread) pushes updates back to Excel files asynchronously.
4. **File Watching**: `watchdog` monitors mapped files for external changes and triggers auto-reload.

### ID System

- SQLite `AUTOINCREMENT` IDs for all items
- Real IMEIs (14-16 digits) are deduplicated — same IMEI returns existing ID
- Text/placeholder IMEIs ("NOT ON", "N/A", etc.) always create new IDs
- Conflict detection finds duplicate real IMEIs across files; resolution merges via `is_hidden` + `merged_into`

## Building and Running

### Prerequisites
- Python 3.10+
- Windows (for full printing features) or Linux/macOS (limited printing)

### Run from Source
```bash
pip install -r requirements.txt
python main.py
```

### Build Windows Executable
```bash
pyinstaller stockmate.spec
```
Output: `dist/StockMate.exe`

## Key Commands

| Task | Command |
|------|---------|
| Run app | `python main.py` |
| Install deps | `pip install -r requirements.txt` |
| Build executable | `pyinstaller stockmate.spec` |
| Run tests | `pytest tests/` |

## Data Storage Paths

| Data | Location |
|------|----------|
| Database | `~/Documents/StockMate/stockmate.db` (SQLite) |
| Config | `~/Documents/StockMate/config/config.json` |
| File Mappings | `~/Documents/StockMate/config/file_mappings.json` |
| Backups | `~/Documents/StockMate/backups/` |
| Invoices | `~/Documents/StockMate/Invoices/` |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `F1` | Inventory |
| `F2` | Search |
| `F3` | Quick Status |
| `F4` | Quick Entry |
| `F5` | Billing |
| `Escape` | Dashboard |
| `Ctrl+N` / `Ctrl+W` | Quick Navigation |
| `Ctrl+Shift+Up/Down` | Multi-select in inventory |

## Dependencies

| Package | Purpose |
|---------|---------|
| `pandas` | Data manipulation, Excel/CSV reading |
| `openpyxl` | Excel file support |
| `watchdog` | File system watching |
| `python-barcode` | Barcode generation |
| `Pillow` | Image processing |
| `reportlab` | PDF generation |
| `ttkbootstrap` | Themed Tkinter widgets |
| `pycryptodome` | Encryption (optional features) |
| `beautifulsoup4` | HTML parsing (scraper) |
| `requests` | HTTP requests (scraper, updater) |
| `python-docx` | Word document export |
| `pywin32` | Windows printing (win32 only) |
| `pyinstaller` | Executable packaging |

## Testing

Tests are located in `tests/` and use `pytest`:

- `test_core_logic.py` — Core business logic tests
- `test_database.py` — Database layer tests
- `test_aggressive.py` — Stress/edge-case tests

Run with: `pytest tests/`

## Development Conventions

- **Type hints**: The codebase uses type hints extensively (`from __future__ import annotations`)
- **Constants**: Canonical field names and status values are defined in `core/constants.py` — always import from there rather than hardcoding strings
- **Thread safety**: `InventoryManager` uses `threading.RLock` (`_df_lock`) for DataFrame access; `SQLiteDatabase` uses `threading.Lock` for writes
- **Background writes**: Excel writes are queued to a daemon thread to avoid blocking the UI
- **Screen lifecycle**: Screens have `on_show()` and `focus_primary()` lifecycle hooks called by `MainApp.show_screen()`
- **Error handling**: Graceful degradation — if barcode/printer init fails, the app continues with reduced functionality
- **PyInstaller**: The `.spec` file bundles `config/` and `zpl-designer/` as data files; hidden imports are explicitly listed
