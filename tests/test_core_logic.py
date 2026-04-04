"""
Tests for core logic modules: config, billing, barcode_utils, analytics,
watcher, and reporting.

These cover areas not tested by the existing aggressive/database test suite.
"""

import os
import tempfile
import time
import threading
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from core.config import ConfigManager, DEFAULT_CONFIG
from core.billing import BillingManager
from core.barcode_utils import BarcodeGenerator
from core.analytics import AnalyticsManager
from core.watcher import FileChangeHandler, _is_watched_file
from core.reporting import ReportGenerator
from core.constants import (
    STATUS_IN,
    STATUS_OUT,
    FIELD_MODEL,
    FIELD_PRICE,
    FIELD_PRICE_ORIGINAL,
    FIELD_STATUS,
    FIELD_UNIQUE_ID,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_dir():
    """Yield a temporary directory, then clean it up."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def config_manager(temp_dir):
    """Yield a ConfigManager that stores data in temp_dir."""
    import core.config as config_mod

    old_config_dir = config_mod.CONFIG_DIR
    old_config_file = config_mod.CONFIG_FILE
    old_mappings_file = config_mod.MAPPINGS_FILE

    config_dir = Path(temp_dir) / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_mod.CONFIG_DIR = config_dir
    config_mod.CONFIG_FILE = config_dir / "config.json"
    config_mod.MAPPINGS_FILE = config_dir / "file_mappings.json"

    cm = ConfigManager()
    yield cm

    config_mod.CONFIG_DIR = old_config_dir
    config_mod.CONFIG_FILE = old_config_file
    config_mod.MAPPINGS_FILE = old_mappings_file


@pytest.fixture()
def mock_logger():
    """A minimal mock activity logger."""
    logger = MagicMock()
    logger.info = MagicMock()
    logger.log = MagicMock()
    return logger


@pytest.fixture()
def billing_manager(config_manager, mock_logger):
    """BillingManager backed by a temp config manager."""
    return BillingManager(config_manager, mock_logger)


@pytest.fixture()
def barcode_generator(config_manager):
    """BarcodeGenerator backed by a temp config manager."""
    return BarcodeGenerator(config_manager)


@pytest.fixture()
def mock_inventory_manager():
    """Mock inventory_manager that returns a configurable DataFrame."""
    im = MagicMock()
    im.get_inventory.return_value = pd.DataFrame()
    im.db.get_all_items.return_value = []
    return im


@pytest.fixture()
def analytics_manager(mock_inventory_manager):
    """AnalyticsManager backed by a mock inventory manager."""
    return AnalyticsManager(mock_inventory_manager)


@pytest.fixture()
def report_generator():
    """ReportGenerator backed by a mock inventory manager."""
    mock_inv = MagicMock()
    return ReportGenerator(mock_inv)


# ===================================================================
# 1. CONFIG TESTS
# ===================================================================


class TestConfigManager:
    """ConfigManager: get/set, file mappings, defaults, atomic persistence."""

    # -- get / set --

    def test_get_returns_default_value(self, config_manager):
        assert config_manager.get("store_name") == "My Mobile Shop"

    def test_get_returns_custom_default_when_key_missing(self, config_manager):
        assert config_manager.get("nonexistent_key", "fallback") == "fallback"

    def test_get_returns_none_when_key_missing_no_default(self, config_manager):
        assert config_manager.get("nonexistent_key") is None

    def test_set_and_get_roundtrip(self, config_manager):
        config_manager.set("store_name", "New Shop Name")
        assert config_manager.get("store_name") == "New Shop Name"

    def test_set_persists_to_disk(self, config_manager):
        config_manager.set("gst_default_percent", 20.0)
        # Reload from disk by creating a new ConfigManager
        cm2 = ConfigManager()
        assert cm2.get("gst_default_percent") == 20.0

    def test_get_all_returns_dict(self, config_manager):
        all_cfg = config_manager.get_all()
        assert isinstance(all_cfg, dict)
        assert "store_name" in all_cfg

    # -- file mappings CRUD --

    def test_set_file_mapping(self, config_manager):
        path = "/tmp/test_inventory.xlsx"
        data = {"sheet_name": 0, "mapping": {"model": "Model"}}
        config_manager.set_file_mapping(path, data)
        assert config_manager.get_file_mapping(path) == data

    def test_get_file_mapping_returns_none_for_missing(self, config_manager):
        assert config_manager.get_file_mapping("/nonexistent.xlsx") is None

    def test_remove_file_mapping(self, config_manager):
        path = "/tmp/to_remove.xlsx"
        config_manager.set_file_mapping(path, {"foo": "bar"})
        assert config_manager.get_file_mapping(path) is not None
        config_manager.remove_file_mapping(path)
        assert config_manager.get_file_mapping(path) is None

    def test_remove_nonexistent_mapping_no_error(self, config_manager):
        config_manager.remove_file_mapping("/does/not/exist.xlsx")

    # -- DEFAULT_CONFIG --

    def test_default_config_has_expected_keys(self):
        expected_keys = [
            "label_width_mm",
            "label_height_mm",
            "printer_type",
            "gst_default_percent",
            "price_markup_percent",
            "store_name",
            "store_address",
            "store_gstin",
            "store_contact",
            "invoice_terms",
            "output_folder",
            "theme_name",
            "theme_color",
            "font_size_ui",
            "enable_ai_scraper",
            "app_display_name",
        ]
        for key in expected_keys:
            assert key in DEFAULT_CONFIG, f"Missing key: {key}"

    def test_default_config_values(self):
        assert DEFAULT_CONFIG["label_width_mm"] == 50
        assert DEFAULT_CONFIG["label_height_mm"] == 22
        assert DEFAULT_CONFIG["gst_default_percent"] == 18.0
        assert DEFAULT_CONFIG["price_markup_percent"] == 0.0
        assert DEFAULT_CONFIG["enable_ai_scraper"] is True

    # -- atomic writes (persistence after reload) --

    def test_atomic_write_persists_after_reload(self, config_manager):
        """Config survives a full reload from disk, proving atomic writes work."""
        config_manager.set("theme_name", "darkly")
        config_manager.set("font_size_ui", 14)

        # Fresh instance reads from the same files
        cm2 = ConfigManager()
        assert cm2.get("theme_name") == "darkly"
        assert cm2.get("font_size_ui") == 14

    def test_mappings_persist_after_reload(self, config_manager):
        """File mappings survive a full reload."""
        path = "/tmp/persist_test.xlsx"
        config_manager.set_file_mapping(path, {"sheet": 0})

        cm2 = ConfigManager()
        assert cm2.get_file_mapping(path) == {"sheet": 0}


# ===================================================================
# 2. BILLING TESTS
# ===================================================================


class TestBillingManager:
    """BillingManager: tax computation (inclusive, exclusive, interstate),
    discount handling, zero subtotal edge case."""

    # -- inclusive tax (CGST + SGST for intrastate) --

    def test_calculate_tax_inclusive_intrastate(self, billing_manager):
        """Inclusive tax: subtotal already contains tax; CGST+SGST split."""
        result = billing_manager.calculate_tax(
            subtotal=1180.0, gst_rate=18.0, is_interstate=False, tax_inclusive=True
        )
        # Tax included in 1180 = 1180 * 18 / 118 = 180
        assert result["tax_amount"] == pytest.approx(180.0, abs=0.02)
        assert result["cgst"] > 0
        assert result["sgst"] > 0
        assert result["igst"] == 0.0
        assert result["total"] == 1180.0  # total = subtotal for inclusive
        assert result["subtotal"] == pytest.approx(1000.0, abs=0.02)

    # -- exclusive tax --

    def test_calculate_tax_exclusive_intrastate(self, billing_manager):
        """Exclusive tax: tax added on top; CGST+SGST split."""
        result = billing_manager.calculate_tax(
            subtotal=1000.0, gst_rate=18.0, is_interstate=False, tax_inclusive=False
        )
        assert result["tax_amount"] == pytest.approx(180.0, abs=0.01)
        assert result["cgst"] == pytest.approx(90.0, abs=0.01)
        assert result["sgst"] == pytest.approx(90.0, abs=0.01)
        assert result["igst"] == 0.0
        assert result["total"] == pytest.approx(1180.0, abs=0.01)

    # -- interstate tax (IGST) --

    def test_calculate_tax_interstate(self, billing_manager):
        """Interstate: all tax goes to IGST, CGST/SGST are zero."""
        result = billing_manager.calculate_tax(
            subtotal=1000.0, gst_rate=18.0, is_interstate=True, tax_inclusive=False
        )
        assert result["igst"] == pytest.approx(180.0, abs=0.01)
        assert result["cgst"] == 0.0
        assert result["sgst"] == 0.0
        assert result["total"] == pytest.approx(1180.0, abs=0.01)

    def test_calculate_tax_interstate_inclusive(self, billing_manager):
        """Interstate + inclusive: IGST extracted from the total."""
        result = billing_manager.calculate_tax(
            subtotal=1180.0, gst_rate=18.0, is_interstate=True, tax_inclusive=True
        )
        assert result["igst"] == pytest.approx(180.0, abs=0.02)
        assert result["cgst"] == 0.0
        assert result["sgst"] == 0.0
        assert result["total"] == 1180.0

    # -- discount calculation --

    def test_discount_reduces_taxable_subtotal(self, billing_manager):
        """Discount applied before tax: 1000 - 100 = 900 taxable."""
        taxable = 1000.0 - 100.0  # discount
        result = billing_manager.calculate_tax(
            subtotal=taxable, gst_rate=18.0, is_interstate=False, tax_inclusive=False
        )
        assert result["subtotal"] == 900.0
        assert result["tax_amount"] == pytest.approx(162.0, abs=0.01)
        assert result["total"] == pytest.approx(1062.0, abs=0.01)

    def test_percent_discount_computation(self, billing_manager):
        """10% discount on 1000 = 100 off, then tax on 900."""
        line_subtotal = 1000.0
        discount_percent = 10.0
        discount_amount = round(line_subtotal * discount_percent / 100.0, 2)
        taxable = line_subtotal - discount_amount

        result = billing_manager.calculate_tax(
            subtotal=taxable, gst_rate=18.0, is_interstate=False, tax_inclusive=False
        )
        assert result["subtotal"] == 900.0
        assert result["total"] == pytest.approx(1062.0, abs=0.01)

    # -- zero subtotal --

    def test_tax_with_zero_subtotal(self, billing_manager):
        """Zero subtotal should produce zero tax and zero total."""
        result = billing_manager.calculate_tax(
            subtotal=0.0, gst_rate=18.0, is_interstate=False, tax_inclusive=False
        )
        assert result["tax_amount"] == 0.0
        assert result["cgst"] == 0.0
        assert result["sgst"] == 0.0
        assert result["igst"] == 0.0
        assert result["total"] == 0.0

    # -- error handling --

    def test_negative_subtotal_raises(self, billing_manager):
        with pytest.raises(ValueError, match="Subtotal cannot be negative"):
            billing_manager.calculate_tax(subtotal=-100.0)

    def test_negative_gst_rate_raises(self, billing_manager):
        with pytest.raises(ValueError, match="GST rate cannot be negative"):
            billing_manager.calculate_tax(subtotal=100.0, gst_rate=-5.0)

    # -- return structure --

    def test_calculate_tax_returns_all_keys(self, billing_manager):
        result = billing_manager.calculate_tax(subtotal=500.0)
        expected_keys = {
            "subtotal",
            "gst_rate",
            "cgst",
            "sgst",
            "igst",
            "tax_amount",
            "total",
        }
        assert set(result.keys()) == expected_keys


# ===================================================================
# 3. BARCODE UTILS TESTS
# ===================================================================


class TestBarcodeGenerator:
    """BarcodeGenerator: barcode image generation, label preview."""

    def test_generate_barcode_image_valid_data(self, barcode_generator):
        """Valid alphanumeric data produces a PIL Image."""
        img = barcode_generator.generate_barcode_image("ABC123456")
        assert img is not None
        assert hasattr(img, "size")
        assert img.size == (300, 80)  # default dimensions

    def test_generate_barcode_image_custom_dimensions(self, barcode_generator):
        """Custom width and height are respected."""
        img = barcode_generator.generate_barcode_image("TEST789", width=500, height=120)
        assert img.size == (500, 120)

    def test_generate_barcode_image_empty_data_raises(self, barcode_generator):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="Barcode data cannot be empty"):
            barcode_generator.generate_barcode_image("")

    def test_generate_barcode_image_none_data_raises(self, barcode_generator):
        """None data raises ValueError (treated as empty)."""
        with pytest.raises(ValueError):
            barcode_generator.generate_barcode_image(None)

    def test_generate_barcode_image_cleans_special_chars(self, barcode_generator):
        """Special characters are stripped; if alphanumeric remains, image is produced."""
        img = barcode_generator.generate_barcode_image("ABC-123/XYZ")
        assert img is not None
        assert img.size == (300, 80)

    def test_generate_label_preview_returns_pil_image(self, barcode_generator):
        """Label preview returns a PIL Image in RGB mode."""
        item = {
            "model": "Samsung Galaxy S24",
            "ram_rom": "8/256",
            "unique_id": "12345",
            "price": 45000.0,
        }
        img = barcode_generator.generate_label_preview(item)
        assert img is not None
        assert img.mode == "RGB"
        assert img.size == (400, 200)  # default dimensions

    def test_generate_label_preview_custom_dimensions(self, barcode_generator):
        """Custom label dimensions are respected."""
        item = {
            "model": "iPhone 15",
            "ram_rom": "6/128",
            "unique_id": "99999",
            "price": 80000,
        }
        img = barcode_generator.generate_label_preview(item, width=600, height=300)
        assert img.size == (600, 300)

    def test_generate_label_preview_missing_optional_fields(self, barcode_generator):
        """Label works even with minimal item data."""
        item = {"price": 1000.0}
        img = barcode_generator.generate_label_preview(item)
        assert img is not None
        assert img.mode == "RGB"


# ===================================================================
# 4. ANALYTICS TESTS
# ===================================================================


class TestAnalyticsManager:
    """AnalyticsManager: summary, demand forecast, price simulation."""

    # -- empty DataFrame --

    def test_get_summary_empty_dataframe(
        self, analytics_manager, mock_inventory_manager
    ):
        """Empty inventory returns zeroed summary."""
        mock_inventory_manager.get_inventory.return_value = pd.DataFrame()
        summary = analytics_manager.get_summary()
        assert summary["total_items"] == 0
        assert summary["total_value"] == 0.0
        assert summary["total_cost"] == 0.0
        assert summary["est_profit"] == 0.0
        assert summary["realized_sales"] == 0
        assert summary["realized_profit"] == 0.0
        assert summary["status_counts"] == {}
        assert summary["top_models"] == []
        assert summary["supplier_dist"] == {}

    def test_get_demand_forecast_empty_data(
        self, analytics_manager, mock_inventory_manager
    ):
        """Empty inventory returns empty forecast list."""
        mock_inventory_manager.get_inventory.return_value = pd.DataFrame()
        forecast = analytics_manager.get_demand_forecast()
        assert forecast == []

    # -- sample data summary --

    def test_get_summary_with_sample_data(
        self, analytics_manager, mock_inventory_manager
    ):
        """Summary correctly aggregates sample inventory data."""
        df = pd.DataFrame(
            [
                {
                    FIELD_MODEL: "Phone A",
                    FIELD_PRICE: 10000,
                    FIELD_PRICE_ORIGINAL: 8000,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 1,
                    "supplier": "SupA",
                },
                {
                    FIELD_MODEL: "Phone B",
                    FIELD_PRICE: 15000,
                    FIELD_PRICE_ORIGINAL: 12000,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 2,
                    "supplier": "SupB",
                },
                {
                    FIELD_MODEL: "Phone C",
                    FIELD_PRICE: 20000,
                    FIELD_PRICE_ORIGINAL: 16000,
                    FIELD_STATUS: STATUS_OUT,
                    FIELD_UNIQUE_ID: 3,
                    "supplier": "SupA",
                },
            ]
        )
        mock_inventory_manager.get_inventory.return_value = df

        summary = analytics_manager.get_summary()
        assert summary["total_items"] == 2  # 2 IN stock
        assert summary["total_value"] == 25000.0  # 10000 + 15000
        assert summary["total_cost"] == 20000.0  # 8000 + 12000
        assert summary["est_profit"] == 5000.0
        assert summary["realized_sales"] == 1  # 1 OUT
        assert summary["realized_profit"] == 4000.0  # 20000 - 16000

    def test_get_summary_status_counts(self, analytics_manager, mock_inventory_manager):
        """Status counts reflect the actual distribution."""
        df = pd.DataFrame(
            [
                {
                    FIELD_MODEL: "X",
                    FIELD_PRICE: 100,
                    FIELD_PRICE_ORIGINAL: 50,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 1,
                    "supplier": "S",
                },
                {
                    FIELD_MODEL: "Y",
                    FIELD_PRICE: 200,
                    FIELD_PRICE_ORIGINAL: 100,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 2,
                    "supplier": "S",
                },
                {
                    FIELD_MODEL: "Z",
                    FIELD_PRICE: 300,
                    FIELD_PRICE_ORIGINAL: 150,
                    FIELD_STATUS: STATUS_OUT,
                    FIELD_UNIQUE_ID: 3,
                    "supplier": "S",
                },
            ]
        )
        mock_inventory_manager.get_inventory.return_value = df

        summary = analytics_manager.get_summary()
        assert summary["status_counts"].get(STATUS_IN) == 2
        assert summary["status_counts"].get(STATUS_OUT) == 1

    # -- price simulation --

    def test_get_summary_with_price_simulation(
        self, analytics_manager, mock_inventory_manager
    ):
        """Simulation parameters adjust prices before computing summary."""
        df = pd.DataFrame(
            [
                {
                    FIELD_MODEL: "Phone A",
                    FIELD_PRICE: 10000,
                    FIELD_PRICE_ORIGINAL: 8000,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 1,
                    "supplier": "S",
                },
            ]
        )
        mock_inventory_manager.get_inventory.return_value = df

        # Simulate 1.5x price multiplier
        sim_params = {"target": "price", "base": 0, "modifier": 1.5, "flat_adjust": 0}
        summary = analytics_manager.get_summary(sim_params=sim_params)

        assert summary["total_value"] == pytest.approx(15000.0, abs=0.01)
        assert summary["total_cost"] == 8000.0  # cost unchanged
        assert summary["est_profit"] == pytest.approx(7000.0, abs=0.01)

    def test_get_summary_with_cost_simulation(
        self, analytics_manager, mock_inventory_manager
    ):
        """Simulation on cost column adjusts total_cost."""
        df = pd.DataFrame(
            [
                {
                    FIELD_MODEL: "Phone A",
                    FIELD_PRICE: 10000,
                    FIELD_PRICE_ORIGINAL: 8000,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 1,
                    "supplier": "S",
                },
            ]
        )
        mock_inventory_manager.get_inventory.return_value = df

        # Simulate 1.2x cost multiplier
        sim_params = {"target": "cost", "base": 0, "modifier": 1.2, "flat_adjust": 0}
        summary = analytics_manager.get_summary(sim_params=sim_params)

        assert summary["total_value"] == 10000.0  # price unchanged
        assert summary["total_cost"] == pytest.approx(9600.0, abs=0.01)

    # -- demand forecast with data --

    def test_get_demand_forecast_with_data(
        self, analytics_manager, mock_inventory_manager
    ):
        """Forecast returns entries per model with stock info."""
        df = pd.DataFrame(
            [
                {
                    FIELD_MODEL: "Phone A",
                    FIELD_PRICE: 10000,
                    FIELD_PRICE_ORIGINAL: 8000,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 1,
                    "supplier": "S",
                },
                {
                    FIELD_MODEL: "Phone A",
                    FIELD_PRICE: 10000,
                    FIELD_PRICE_ORIGINAL: 8000,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 2,
                    "supplier": "S",
                },
                {
                    FIELD_MODEL: "Phone B",
                    FIELD_PRICE: 15000,
                    FIELD_PRICE_ORIGINAL: 12000,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 3,
                    "supplier": "S",
                },
            ]
        )
        mock_inventory_manager.get_inventory.return_value = df
        mock_inventory_manager.db.get_all_items.return_value = []

        forecast = analytics_manager.get_demand_forecast()
        models = [f["model"] for f in forecast]
        assert "Phone A" in models
        assert "Phone B" in models

        phone_a = next(f for f in forecast if f["model"] == "Phone A")
        assert phone_a["in_stock"] == 2
        assert phone_a["status_flag"] == "LOW_STOCK"  # < 5

    # -- top models --

    def test_summary_top_models(self, analytics_manager, mock_inventory_manager):
        """Top models are computed from in-stock items."""
        df = pd.DataFrame(
            [
                {
                    FIELD_MODEL: "Phone A",
                    FIELD_PRICE: 100,
                    FIELD_PRICE_ORIGINAL: 50,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 1,
                    "supplier": "S",
                },
                {
                    FIELD_MODEL: "Phone A",
                    FIELD_PRICE: 100,
                    FIELD_PRICE_ORIGINAL: 50,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 2,
                    "supplier": "S",
                },
                {
                    FIELD_MODEL: "Phone A",
                    FIELD_PRICE: 100,
                    FIELD_PRICE_ORIGINAL: 50,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 3,
                    "supplier": "S",
                },
                {
                    FIELD_MODEL: "Phone B",
                    FIELD_PRICE: 200,
                    FIELD_PRICE_ORIGINAL: 100,
                    FIELD_STATUS: STATUS_IN,
                    FIELD_UNIQUE_ID: 4,
                    "supplier": "S",
                },
            ]
        )
        mock_inventory_manager.get_inventory.return_value = df

        summary = analytics_manager.get_summary()
        assert summary["top_models"][0] == ("Phone A", 3)


# ===================================================================
# 5. WATCHER TESTS
# ===================================================================


class TestFileChangeHandler:
    """FileChangeHandler: file extension filtering, debounce behavior."""

    # -- _is_watched_file --

    def test_is_watched_file_xlsx_returns_true(self):
        assert _is_watched_file("/path/to/inventory.xlsx") is True

    def test_is_watched_file_xls_returns_true(self):
        assert _is_watched_file("/path/to/inventory.xls") is True

    def test_is_watched_file_uppercase_xlsx(self):
        assert _is_watched_file("/path/to/INVENTORY.XLSX") is True

    def test_is_watched_file_txt_returns_false(self):
        assert _is_watched_file("/path/to/notes.txt") is False

    def test_is_watched_file_csv_returns_false(self):
        assert _is_watched_file("/path/to/data.csv") is False

    def test_is_watched_file_pdf_returns_false(self):
        assert _is_watched_file("/path/to/report.pdf") is False

    # -- debounce behavior --

    def test_debounce_callback_not_called_immediately(self):
        """Callback should NOT fire immediately; it waits for debounce period."""
        call_count = {"value": 0}

        def callback():
            call_count["value"] += 1

        handler = FileChangeHandler(callback=callback, debounce_seconds=0.5)

        # Simulate a file modification event
        from watchdog.events import FileSystemEvent

        event = MagicMock(spec=FileSystemEvent)
        event.is_directory = False
        event.src_path = "/tmp/test.xlsx"

        handler.on_modified(event)

        # Callback should NOT have fired yet (still within debounce window)
        assert call_count["value"] == 0

        # Clean up
        handler.cancel()

    def test_debounce_callback_fires_after_delay(self):
        """Callback should fire once after the debounce period elapses."""
        call_count = {"value": 0}
        lock = threading.Lock()

        def callback():
            with lock:
                call_count["value"] += 1

        handler = FileChangeHandler(callback=callback, debounce_seconds=0.2)

        from watchdog.events import FileSystemEvent

        event = MagicMock(spec=FileSystemEvent)
        event.is_directory = False
        event.src_path = "/tmp/test.xlsx"

        handler.on_modified(event)

        # Wait for debounce to expire
        time.sleep(0.5)

        with lock:
            assert call_count["value"] == 1

        handler.cancel()

    def test_debounce_resets_on_rapid_events(self):
        """Multiple rapid events should result in only ONE callback firing."""
        call_count = {"value": 0}
        lock = threading.Lock()

        def callback():
            with lock:
                call_count["value"] += 1

        handler = FileChangeHandler(callback=callback, debounce_seconds=0.3)

        from watchdog.events import FileSystemEvent

        event = MagicMock(spec=FileSystemEvent)
        event.is_directory = False
        event.src_path = "/tmp/test.xlsx"

        # Fire 5 rapid events
        for _ in range(5):
            handler.on_modified(event)
            time.sleep(0.05)

        # Should not have fired yet
        with lock:
            assert call_count["value"] == 0

        # Wait for debounce after last event
        time.sleep(0.5)

        with lock:
            # Should have fired exactly once (all timers were cancelled except last)
            assert call_count["value"] == 1

        handler.cancel()

    def test_ignored_file_does_not_trigger_callback(self):
        """Non-watched file extensions should not trigger the callback."""
        call_count = {"value": 0}

        def callback():
            call_count["value"] += 1

        handler = FileChangeHandler(callback=callback, debounce_seconds=0.1)

        from watchdog.events import FileSystemEvent

        event = MagicMock(spec=FileSystemEvent)
        event.is_directory = False
        event.src_path = "/tmp/notes.txt"

        handler.on_modified(event)
        time.sleep(0.2)

        assert call_count["value"] == 0

        handler.cancel()

    def test_directory_event_ignored(self):
        """Directory modification events should be ignored."""
        call_count = {"value": 0}

        def callback():
            call_count["value"] += 1

        handler = FileChangeHandler(callback=callback, debounce_seconds=0.1)

        from watchdog.events import FileSystemEvent

        event = MagicMock(spec=FileSystemEvent)
        event.is_directory = True
        event.src_path = "/tmp/some_dir"

        handler.on_modified(event)
        time.sleep(0.2)

        assert call_count["value"] == 0

        handler.cancel()


# ===================================================================
# 6. REPORTING TESTS
# ===================================================================


class TestReportGenerator:
    """ReportGenerator: filtering (AND/OR), custom expressions, limits."""

    # -- apply_filters AND logic --

    def test_apply_filters_and_logic(self, report_generator):
        """AND: both conditions must match."""
        df = pd.DataFrame(
            [
                {"model": "Phone A", "price": 10000, "status": STATUS_IN},
                {"model": "Phone A", "price": 15000, "status": STATUS_OUT},
                {"model": "Phone B", "price": 10000, "status": STATUS_IN},
                {"model": "Phone B", "price": 20000, "status": STATUS_OUT},
            ]
        )

        conditions = [
            {
                "field": "model",
                "operator": "equals",
                "value": "Phone A",
                "logic": "AND",
            },
            {
                "field": "status",
                "operator": "equals",
                "value": STATUS_IN,
                "logic": "AND",
            },
        ]

        result = report_generator.apply_filters(df, conditions)
        assert len(result) == 1
        assert result.iloc[0]["model"] == "Phone A"
        assert result.iloc[0]["status"] == STATUS_IN

    # -- apply_filters OR logic --

    def test_apply_filters_or_logic(self, report_generator):
        """OR: either condition can match."""
        df = pd.DataFrame(
            [
                {"model": "Phone A", "price": 10000, "status": STATUS_IN},
                {"model": "Phone B", "price": 15000, "status": STATUS_IN},
                {"model": "Phone C", "price": 20000, "status": STATUS_OUT},
            ]
        )

        conditions = [
            {"field": "model", "operator": "equals", "value": "Phone A", "logic": "OR"},
            {"field": "model", "operator": "equals", "value": "Phone C", "logic": "OR"},
        ]

        result = report_generator.apply_filters(df, conditions)
        assert len(result) == 2
        models = set(result["model"].tolist())
        assert models == {"Phone A", "Phone C"}

    # -- apply_filters empty conditions --

    def test_apply_filters_empty_conditions_returns_all(self, report_generator):
        """No conditions means no filtering — return full DataFrame."""
        df = pd.DataFrame(
            [
                {"model": "Phone A", "price": 10000},
                {"model": "Phone B", "price": 15000},
            ]
        )

        result = report_generator.apply_filters(df, [])
        assert len(result) == 2
        assert list(result["model"]) == ["Phone A", "Phone B"]

    # -- apply_custom_expression --

    def test_apply_custom_expression_valid_query(self, report_generator):
        """Valid pandas query expression filters correctly."""
        df = pd.DataFrame(
            [
                {"model": "Phone A", "price": 10000},
                {"model": "Phone B", "price": 15000},
                {"model": "Phone C", "price": 20000},
            ]
        )

        result = report_generator.apply_custom_expression(df, "price > 12000")
        assert len(result) == 2
        assert all(result["price"] > 12000)

    def test_apply_custom_expression_invalid_query_raises(self, report_generator):
        """Invalid expression raises ValueError with helpful message."""
        df = pd.DataFrame([{"model": "Phone A", "price": 10000}])

        with pytest.raises(ValueError, match="Invalid query expression"):
            report_generator.apply_custom_expression(df, "nonexistent_column > 5")

    def test_apply_custom_expression_empty_string_returns_all(self, report_generator):
        """Empty expression returns the full DataFrame."""
        df = pd.DataFrame([{"model": "Phone A", "price": 10000}])
        result = report_generator.apply_custom_expression(df, "")
        assert len(result) == 1

    def test_apply_custom_expression_whitespace_returns_all(self, report_generator):
        """Whitespace-only expression returns the full DataFrame."""
        df = pd.DataFrame([{"model": "Phone A", "price": 10000}])
        result = report_generator.apply_custom_expression(df, "   ")
        assert len(result) == 1

    # -- apply_limit --

    def test_apply_limit_row_count(self, report_generator):
        """Limit returns only the first N rows."""
        df = pd.DataFrame(
            [{"model": f"Phone_{i}", "price": 10000 + i} for i in range(10)]
        )

        result = report_generator.apply_limit(df, limit=3)
        assert len(result) == 3
        assert result.iloc[0]["model"] == "Phone_0"
        assert result.iloc[2]["model"] == "Phone_2"

    def test_apply_limit_none_returns_all(self, report_generator):
        """No limit returns the full DataFrame."""
        df = pd.DataFrame(
            [
                {"model": "Phone A", "price": 10000},
                {"model": "Phone B", "price": 15000},
            ]
        )

        result = report_generator.apply_limit(df, limit=None)
        assert len(result) == 2

    def test_apply_limit_zero_returns_all(self, report_generator):
        """Limit of 0 is treated as no limit (code checks limit > 0)."""
        df = pd.DataFrame(
            [
                {"model": "Phone A", "price": 10000},
            ]
        )

        result = report_generator.apply_limit(df, limit=0)
        assert len(result) == 1

    def test_apply_limit_with_modulo(self, report_generator):
        """Modulo selects every Nth row."""
        df = pd.DataFrame(
            [{"model": f"Phone_{i}", "price": 10000 + i} for i in range(6)]
        )

        result = report_generator.apply_limit(df, modulo=2)
        assert len(result) == 3
        assert list(result["model"]) == ["Phone_0", "Phone_2", "Phone_4"]

    def test_apply_limit_combined_modulo_and_limit(self, report_generator):
        """Modulo applied first, then limit truncates."""
        df = pd.DataFrame(
            [{"model": f"Phone_{i}", "price": 10000 + i} for i in range(10)]
        )

        # Modulo 3 gives indices 0,3,6,9 → then limit 2 gives 0,3
        result = report_generator.apply_limit(df, modulo=3, limit=2)
        assert len(result) == 2
        assert list(result["model"]) == ["Phone_0", "Phone_3"]

    # -- filter operators --

    def test_apply_filters_contains_operator(self, report_generator):
        """Contains matches substring."""
        df = pd.DataFrame(
            [
                {"model": "Samsung Galaxy", "price": 15000},
                {"model": "iPhone 15", "price": 80000},
                {"model": "Samsung Note", "price": 12000},
            ]
        )

        conditions = [
            {
                "field": "model",
                "operator": "contains",
                "value": "Samsung",
                "logic": "AND",
            },
        ]

        result = report_generator.apply_filters(df, conditions)
        assert len(result) == 2
        assert all("Samsung" in m for m in result["model"])

    def test_apply_filters_gt_operator(self, report_generator):
        """Greater-than filters numeric columns."""
        df = pd.DataFrame(
            [
                {"model": "A", "price": 5000},
                {"model": "B", "price": 15000},
                {"model": "C", "price": 25000},
            ]
        )

        conditions = [
            {"field": "price", "operator": "gt", "value": 10000, "logic": "AND"},
        ]

        result = report_generator.apply_filters(df, conditions)
        assert len(result) == 2
        assert all(p > 10000 for p in result["price"])

    def test_apply_filters_is_empty_operator(self, report_generator):
        """is_empty matches NaN and blank strings."""
        df = pd.DataFrame(
            [
                {"model": "Phone A", "notes": "has notes"},
                {"model": "Phone B", "notes": ""},
                {"model": "Phone C", "notes": None},
            ]
        )

        conditions = [
            {"field": "notes", "operator": "is_empty", "logic": "AND"},
        ]

        result = report_generator.apply_filters(df, conditions)
        assert len(result) == 2
        models = set(result["model"].tolist())
        assert models == {"Phone B", "Phone C"}
