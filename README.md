# StockMate

A comprehensive desktop application for mobile phone retail shop inventory management, billing, and analytics.

## Features

- **Inventory Management** — Excel-backed stock tracking with SQLite metadata
- **Quick Entry** — High-speed data entry with IMEI scanning and auto-fetch
- **Quick Status** — Fast IN/OUT/RTN status updates via barcode scanning
- **Billing & Invoices** — GST-compliant invoice generation with PDF output
- **Label Design** — Drag-and-drop ZPL label designer with thermal printer support
- **Analytics** — Stock value, demand forecasting, brand distribution
- **Advanced Reporting** — Filter builder with AND/OR/XOR logic, export to Excel/PDF/Word
- **File Watching** — Auto-reload when mapped Excel files change externally

## Quick Start

### Prerequisites

- Python 3.10+
- Windows (for printing features) or Linux/macOS (limited printing)

### Installation

```bash
pip install -r requirements.txt
python main.py
```

### Building Windows Executable

```bash
pyinstaller stockmate.spec
```

The built executable will be in `dist/StockMate.exe`.

## First-Time Setup

1. Launch the application
2. Go to **Manage > Manage Files**
3. Click **Add File** and select your Excel inventory file
4. Map your spreadsheet columns to the app fields
5. Your inventory loads automatically

## Excel File Format

Your Excel file should have columns like: IMEI, Model, Brand, Color, Storage, Condition, Grade, Price, Supplier, Status, etc. The app auto-detects column headers and lets you map them during setup.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `F1` | Inventory |
| `F2` | Search |
| `F3` | Quick Status |
| `F4` | Quick Entry |
| `F5` | Billing |
| `Escape` | Dashboard |
| `Ctrl+N` | Quick Navigation |
| `Ctrl+Shift+Up/Down` | Multi-select in inventory |

## Data Storage

- **Database**: `~/Documents/StockMate/inventory.db` (SQLite)
- **Config**: `~/Documents/StockMate/config/config.json`
- **File Mappings**: `~/Documents/StockMate/config/file_mappings.json`
- **Backups**: `~/Documents/StockMate/backups/`
- **Invoices**: `~/Documents/StockMate/Invoices/`

## Architecture

- **Core**: SQLite database + Excel file sync with background write queue
- **GUI**: Tkinter with ttkbootstrap theming, 18 screens
- **ID System**: AUTOINCREMENT SQLite IDs — real IMEIs deduplicate, text/placeholder IMEIs always create new IDs
- **Printing**: ZPL thermal labels, Windows GDI, PDF export

## License

Apache 2.0
