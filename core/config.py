import json
from pathlib import Path

from .utils import SafeJsonWriter

APP_DIR = Path.home() / "Documents" / "StockMate"
CONFIG_DIR = APP_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "config.json"
MAPPINGS_FILE = CONFIG_DIR / "file_mappings.json"

CONFIG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "label_width_mm": 50,
    "label_height_mm": 22,
    "printer_type": "windows",
    "gst_default_percent": 18.0,
    "price_markup_percent": 0.0,
    "store_name": "My Mobile Shop",
    "app_display_name": "StockMate",
    "store_address": "",
    "store_gstin": "",
    "store_contact": "",
    "invoice_terms": "Goods once sold will not be taken back.",
    "output_folder": str(APP_DIR),
    "theme_name": "cosmo",
    "theme_color": "#007acc",
    "font_size_ui": 10,
    "enable_ai_scraper": True,
}


class ConfigManager:
    """Manage application config and file-mapping persistence."""

    def __init__(self):
        self.config = self._load_config()
        self.mappings = self._load_mappings()

    # -- config access --

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self._save_config()

    def get_all(self):
        return dict(self.config)

    # -- mappings CRUD --

    def get_file_mapping(self, file_path):
        return self.mappings.get(str(file_path))

    def set_file_mapping(self, file_path, data):
        self.mappings[str(file_path)] = data
        self._save_mappings()

    def remove_file_mapping(self, file_path):
        self.mappings.pop(str(file_path), None)
        self._save_mappings()

    # -- directories --

    def get_invoices_dir(self):
        d = APP_DIR / "Invoices"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_config_dir(self):
        return CONFIG_DIR

    # -- internal persistence --

    def _load_config(self):
        if not CONFIG_FILE.exists():
            cfg = dict(DEFAULT_CONFIG)
            self._save_config(cfg)
            return cfg
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return dict(DEFAULT_CONFIG)

    def _save_config(self, config=None):
        if config is not None:
            self.config = config
        SafeJsonWriter.write(CONFIG_FILE, self.config)

    def _load_mappings(self):
        if not MAPPINGS_FILE.exists():
            return {}
        try:
            with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_mappings(self, mappings=None):
        if mappings is not None:
            self.mappings = mappings
        SafeJsonWriter.write(MAPPINGS_FILE, self.mappings)
