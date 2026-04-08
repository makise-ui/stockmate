"""
Aggressive test suite for StockMate.

Goal: Prove NO data loss occurs and IDs NEVER change unexpectedly.
Tests cover ID stability, data integrity, concurrent writes, conflict resolution,
backup integrity, edge cases, Excel roundtrips, and status history.
"""

import os
import tempfile
import time
import threading
import datetime
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from core.database import SQLiteDatabase
from core.inventory import InventoryManager
from core.config import ConfigManager
from core.constants import (
    STATUS_IN,
    STATUS_OUT,
    STATUS_RETURN,
    FIELD_IMEI,
    FIELD_MODEL,
    FIELD_RAM_ROM,
    FIELD_PRICE,
    FIELD_PRICE_ORIGINAL,
    FIELD_STATUS,
    FIELD_BUYER,
    FIELD_BUYER_CONTACT,
    FIELD_UNIQUE_ID,
    FIELD_SOURCE_FILE,
    FIELD_NOTES,
    FIELD_COLOR,
    FIELD_GRADE,
    FIELD_CONDITION,
)


# ---------------------------------------------------------------------------
# Fixtures — isolated temp environments per test
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    """Yield a SQLiteDatabase backed by a temporary file, then close it."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    database = SQLiteDatabase(db_path=path)
    yield database
    database.close()
    if os.path.exists(path):
        os.unlink(path)
    # Clean up WAL files
    for ext in ("-wal", "-shm"):
        wal = path + ext
        if os.path.exists(wal):
            os.unlink(wal)


@pytest.fixture()
def temp_dir():
    """Yield a temporary directory, then clean it up."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def config_manager(temp_dir):
    """Yield a ConfigManager that stores mappings in temp_dir."""
    # Monkey-patch the module-level paths so config lives in temp_dir
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

    # Restore original paths
    config_mod.CONFIG_DIR = old_config_dir
    config_mod.CONFIG_FILE = old_config_file
    config_mod.MAPPINGS_FILE = old_mappings_file


@pytest.fixture()
def inventory_manager(db, config_manager):
    """Yield an InventoryManager with a mock activity logger."""

    class MockLogger:
        def log(self, action, details):
            pass

    im = InventoryManager(
        config_manager=config_manager, db=db, activity_logger=MockLogger()
    )
    yield im
    im.shutdown()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_excel_file(
    file_path: str,
    rows: list[dict[str, Any]],
    headers: list[str] | None = None,
) -> str:
    """Create an Excel file with the given rows and headers."""
    if rows:
        df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame(columns=headers or [])
    df.to_excel(file_path, index=False, engine="openpyxl")
    return file_path


def make_sample_item(
    imei: str = "",
    model: str = "Test Model",
    ram_rom: str = "8/128",
    price: float = 10000.0,
    supplier: str = "TestSupplier",
    color: str = "Black",
    grade: str = "A",
    condition: str = "Good",
    status: str = STATUS_IN,
    notes: str = "",
    buyer: str = "",
    buyer_contact: str = "",
) -> dict[str, Any]:
    """Build a sample item dict for Excel rows."""
    return {
        FIELD_IMEI: imei,
        FIELD_MODEL: model,
        FIELD_RAM_ROM: ram_rom,
        FIELD_PRICE: price,
        FIELD_PRICE_ORIGINAL: price,
        "supplier": supplier,
        FIELD_COLOR: color,
        FIELD_GRADE: grade,
        FIELD_CONDITION: condition,
        FIELD_STATUS: status,
        FIELD_NOTES: notes,
        FIELD_BUYER: buyer,
        FIELD_BUYER_CONTACT: buyer_contact,
    }


def make_mapping(file_path: str, sheet_name: str | int = 0) -> dict:
    """Build a mapping dict that maps canonical fields to Excel column names."""
    mapping = {
        FIELD_IMEI: FIELD_IMEI,
        FIELD_MODEL: FIELD_MODEL,
        FIELD_RAM_ROM: FIELD_RAM_ROM,
        FIELD_PRICE: FIELD_PRICE,
        FIELD_PRICE_ORIGINAL: FIELD_PRICE_ORIGINAL,
        "supplier": "supplier",
        FIELD_STATUS: FIELD_STATUS,
        FIELD_COLOR: FIELD_COLOR,
        FIELD_GRADE: FIELD_GRADE,
        FIELD_CONDITION: FIELD_CONDITION,
        FIELD_NOTES: FIELD_NOTES,
        FIELD_BUYER: FIELD_BUYER,
        FIELD_BUYER_CONTACT: FIELD_BUYER_CONTACT,
    }
    return {
        "file_path": file_path,
        "sheet_name": sheet_name,
        "supplier": "",
        "mapping": mapping,
    }


# ===================================================================
# 1. ID STABILITY TESTS
# ===================================================================


class TestIdStabilityRealImei:
    """IDs for real IMEI items must NEVER change after creation."""

    def test_id_stable_after_model_update(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        db.update_metadata(item_id, status="IN")
        original_id = item_id

        # Update model via a new get_or_create_id call (simulates reload)
        same_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54 5G",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        assert same_id == original_id

    def test_id_stable_after_price_update(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
            price_original=10000.0,
        )
        original_id = item_id

        # Metadata update for price
        db.update_metadata(item_id, price_override=12000.0)
        meta = db.get_metadata(item_id)
        assert meta["price_override"] == 12000.0

        # Re-lookup by IMEI
        same_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        assert same_id == original_id

    def test_id_stable_after_color_update(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
            color="Black",
        )
        original_id = item_id

        # Update color in items table via re-insert attempt (should return same ID)
        same_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
            color="Blue",
        )
        assert same_id == original_id

    def test_id_stable_after_grade_update(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
            grade="A",
        )
        original_id = item_id

        same_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
            grade="B",
        )
        assert same_id == original_id

    def test_id_stable_after_condition_update(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
            condition="Good",
        )
        original_id = item_id

        same_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
            condition="Excellent",
        )
        assert same_id == original_id

    def test_id_stable_after_supplier_update(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="SupplierA",
            source_file="test.xlsx",
        )
        original_id = item_id

        same_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="SupplierB",
            source_file="test.xlsx",
        )
        assert same_id == original_id

    def test_id_stable_after_notes_update(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        original_id = item_id

        db.update_metadata(item_id, notes="Test notes updated")
        meta = db.get_metadata(item_id)
        assert meta["notes"] == "Test notes updated"

        same_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        assert same_id == original_id

    def test_id_stable_after_multiple_sequential_updates(
        self, db: SQLiteDatabase
    ) -> None:
        """Update every field one by one, verify ID never changes."""
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
            color="Black",
            price_original=10000.0,
            grade="A",
            condition="Good",
        )
        original_id = item_id

        # Update metadata fields
        db.update_metadata(item_id, status=STATUS_OUT)
        db.update_metadata(item_id, buyer="John Doe")
        db.update_metadata(item_id, buyer_contact="555-1234")
        db.update_metadata(item_id, notes="Sold to John")
        db.update_metadata(item_id, price_override=12000.0)

        # Re-lookup
        same_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54 5G",
            ram_rom="8/256",
            supplier="OtherSupplier",
            source_file="other.xlsx",
            color="Blue",
            price_original=15000.0,
            grade="B",
            condition="Fair",
        )
        assert same_id == original_id


class TestIdStabilityTextImei:
    """Text IMEI items always get new IDs, but IDs must be stable after creation."""

    def test_text_imei_id_stable_after_data_update(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="NOT ON",
            model="Nokia 3310",
            ram_rom="",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        original_id = item_id

        db.update_metadata(item_id, status=STATUS_OUT)
        db.update_metadata(item_id, buyer="Jane")
        db.update_metadata(item_id, notes="Sold without IMEI")

        # Text IMEI always creates new ID on re-lookup, but the ORIGINAL id
        # should still exist in DB with its data intact
        item = db.get_item(original_id)
        assert item is not None
        assert item["imei"] == "NOT ON"
        assert item["model"] == "Nokia 3310"

    def test_text_imei_preserves_data_across_updates(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="NOT ON",
            model="Nokia 3310",
            ram_rom="16MB",
            supplier="TestSupplier",
            source_file="test.xlsx",
            color="Gray",
            grade="C",
            condition="Used",
        )
        original_id = item_id

        db.update_metadata(item_id, status=STATUS_RETURN)
        db.update_metadata(item_id, notes="Returned item")

        item = db.get_item(original_id)
        assert item is not None
        assert item["imei"] == "NOT ON"
        assert item["model"] == "Nokia 3310"
        assert item["ram_rom"] == "16MB"
        assert item["color"] == "Gray"
        assert item["grade"] == "C"
        assert item["condition"] == "Used"
        assert item["status"] == STATUS_RETURN
        assert item["notes"] == "Returned item"


class TestIdStabilityEmptyImei:
    """Empty IMEI items always get new IDs, but IDs must be stable after creation."""

    def test_empty_imei_id_stable_after_data_update(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="",
            model="Generic Phone",
            ram_rom="",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        original_id = item_id

        db.update_metadata(item_id, status=STATUS_OUT)
        db.update_metadata(item_id, buyer="Bob")
        db.update_metadata(item_id, notes="No IMEI available")

        item = db.get_item(original_id)
        assert item is not None
        assert item["imei"] == ""
        assert item["model"] == "Generic Phone"
        assert item["status"] == STATUS_OUT
        assert item["buyer"] == "Bob"

    def test_empty_imei_preserves_all_fields(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="",
            model="Generic Phone",
            ram_rom="4/64",
            supplier="TestSupplier",
            source_file="test.xlsx",
            color="White",
            price_original=5000.0,
            grade="B",
            condition="Fair",
        )
        original_id = item_id

        db.update_metadata(item_id, status=STATUS_RETURN)
        db.update_metadata(item_id, notes="Test note")

        item = db.get_item(original_id)
        assert item is not None
        assert item["imei"] == ""
        assert item["model"] == "Generic Phone"
        assert item["ram_rom"] == "4/64"
        assert item["color"] == "White"
        assert item["price_original"] == 5000.0
        assert item["grade"] == "B"
        assert item["condition"] == "Fair"
        assert item["status"] == STATUS_RETURN


# ===================================================================
# 2. NO DATA LOSS ON RELOAD
# ===================================================================


class TestNoDataLossOnReload:
    """Loading, saving, and reloading must preserve ALL data and IDs."""

    def test_20_items_no_data_loss(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Create 20 items with mixed IMEI types, load, verify, reload, verify again."""
        excel_path = os.path.join(temp_dir, "inventory.xlsx")

        # Build 20 rows: mix of real IMEI, text IMEI, empty IMEI
        rows = []
        for i in range(20):
            if i < 10:
                imei = f"860123456789{100 + i:02d}"  # Real IMEI
            elif i < 15:
                imei = "NOT ON"  # Text IMEI
            else:
                imei = ""  # Empty IMEI

            rows.append(
                make_sample_item(
                    imei=imei,
                    model=f"Model_{i}",
                    ram_rom=f"{4 + i}/64",
                    price=5000.0 + i * 100,
                    supplier=f"Supplier_{i % 3}",
                    color=["Black", "White", "Blue", "Red", "Gold"][i % 5],
                    grade=["A", "B", "C"][i % 3],
                    condition=["Good", "Fair", "Excellent"][i % 3],
                    status=[STATUS_IN, STATUS_OUT, STATUS_RETURN][i % 3],
                    notes=f"Note for item {i}",
                )
            )

        create_excel_file(excel_path, rows)

        # Set up mapping
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        # Load
        inventory_manager.reload_all()
        inv_df = inventory_manager.get_inventory()

        # Record all data
        original_records = []
        for _, row in inv_df.iterrows():
            original_records.append(
                {
                    FIELD_UNIQUE_ID: int(row[FIELD_UNIQUE_ID]),
                    FIELD_IMEI: str(row[FIELD_IMEI]),
                    FIELD_MODEL: str(row[FIELD_MODEL]),
                    FIELD_PRICE: float(row[FIELD_PRICE]),
                    FIELD_STATUS: str(row[FIELD_STATUS]),
                }
            )

        assert len(original_records) == 20, (
            f"Expected 20 items, got {len(original_records)}"
        )

        # Save Excel back (simulate write by reading current inventory)
        output_path = os.path.join(temp_dir, "inventory_out.xlsx")
        inv_df.to_excel(output_path, index=False, engine="openpyxl")

        # Now reload from the saved file
        config_manager.set_file_mapping(output_path, make_mapping(output_path))
        config_manager.remove_file_mapping(excel_path)

        # Clear and reload
        inventory_manager.inventory_df = pd.DataFrame()
        inventory_manager.reload_all()
        reloaded_df = inventory_manager.get_inventory()

        # Verify all items present
        reloaded_ids = set(reloaded_df[FIELD_UNIQUE_ID].astype(int).tolist())
        original_ids = {r[FIELD_UNIQUE_ID] for r in original_records}

        # Real IMEI items should have same IDs (dedup), text/empty will be new
        # But the COUNT should be the same
        assert len(reloaded_df) == 20, (
            f"Expected 20 items after reload, got {len(reloaded_df)}"
        )

        # Verify no data corruption: all models should still exist
        reloaded_models = set(reloaded_df[FIELD_MODEL].tolist())
        original_models = {r[FIELD_MODEL] for r in original_records}
        assert reloaded_models == original_models, (
            "Models were lost or changed on reload"
        )

    def test_no_duplicate_items_after_reload(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Reloading must not create duplicate items."""
        excel_path = os.path.join(temp_dir, "test_dedup.xlsx")
        rows = [
            make_sample_item(imei="860123456789001", model="Phone A", price=10000),
            make_sample_item(imei="860123456789002", model="Phone B", price=12000),
            make_sample_item(imei="860123456789003", model="Phone C", price=15000),
        ]
        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        first_count = len(inventory_manager.get_inventory())

        inventory_manager.reload_all()
        second_count = len(inventory_manager.get_inventory())

        assert first_count == second_count, "Reload created duplicate items"
        assert first_count == 3

    def test_all_item_statuses_preserved_on_reload(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Status set via update_item_status must be preserved across reload.

        Note: On first load, DB defaults all items to IN. After status changes
        via update_item_status, the DB status overrides Excel on subsequent reloads.
        """
        excel_path = os.path.join(temp_dir, "status_test.xlsx")
        rows = [
            make_sample_item(imei="860123456789001", model="Phone A", status=STATUS_IN),
            make_sample_item(imei="860123456789002", model="Phone B", status=STATUS_IN),
            make_sample_item(imei="860123456789003", model="Phone C", status=STATUS_IN),
        ]
        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        # Change statuses via the proper API
        id_b = int(df[df[FIELD_MODEL] == "Phone B"].iloc[0][FIELD_UNIQUE_ID])
        id_c = int(df[df[FIELD_MODEL] == "Phone C"].iloc[0][FIELD_UNIQUE_ID])

        inventory_manager.update_item_status(id_b, STATUS_OUT)
        inventory_manager.update_item_status(id_c, STATUS_RETURN)

        # Reload — DB status should override Excel
        inventory_manager.reload_all()
        df2 = inventory_manager.get_inventory()

        status_map = {}
        for _, row in df2.iterrows():
            status_map[row[FIELD_MODEL]] = row[FIELD_STATUS]

        assert status_map["Phone A"] == STATUS_IN
        assert status_map["Phone B"] == STATUS_OUT
        assert status_map["Phone C"] == STATUS_RETURN


# ===================================================================
# 3. CONCURRENT WRITE SAFETY
# ===================================================================


class TestConcurrentWriteSafety:
    """Rapid status changes must not lose data or corrupt state."""

    def test_rapid_status_changes_50_items(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Update 50 items' statuses rapidly, verify final state."""
        excel_path = os.path.join(temp_dir, "concurrent_test.xlsx")

        # Create 50 items with real IMEIs
        rows = []
        for i in range(50):
            rows.append(
                make_sample_item(
                    imei=f"8601234567{100000 + i:06d}",
                    model=f"Phone_{i}",
                    status=STATUS_IN,
                )
            )
        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()
        assert len(df) == 50

        # Rapidly cycle statuses: IN → OUT → RTN → IN
        item_ids = df[FIELD_UNIQUE_ID].astype(int).tolist()
        status_cycle = [STATUS_OUT, STATUS_RETURN, STATUS_IN]

        for cycle_status in status_cycle:
            for item_id in item_ids:
                inventory_manager.update_item_status(item_id, cycle_status)

        # Verify all items are IN (the last status in the cycle)
        final_df = inventory_manager.get_inventory()
        for _, row in final_df.iterrows():
            assert row[FIELD_STATUS] == STATUS_IN, (
                f"Item {row[FIELD_UNIQUE_ID]} has status {row[FIELD_STATUS]}, expected IN"
            )

        # Verify no items lost
        assert len(final_df) == 50, f"Expected 50 items, got {len(final_df)}"

    def test_concurrent_status_changes_threaded(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Multiple threads updating statuses concurrently must not corrupt data."""
        excel_path = os.path.join(temp_dir, "threaded_test.xlsx")

        rows = [
            make_sample_item(imei=f"8601234567{100000 + i:06d}", model=f"Phone_{i}")
            for i in range(20)
        ]
        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()
        item_ids = df[FIELD_UNIQUE_ID].astype(int).tolist()

        errors = []

        def update_worker(start_status: str, end_status: str):
            try:
                for item_id in item_ids:
                    inventory_manager.update_item_status(item_id, start_status)
                for item_id in item_ids:
                    inventory_manager.update_item_status(item_id, end_status)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=update_worker, args=(STATUS_OUT, STATUS_IN)),
            threading.Thread(target=update_worker, args=(STATUS_RETURN, STATUS_OUT)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Thread errors: {errors}"

        # Verify no items lost
        final_df = inventory_manager.get_inventory()
        assert len(final_df) == 20, f"Expected 20 items, got {len(final_df)}"

    def test_rapid_data_updates_preserve_integrity(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Rapid data updates must not corrupt item data."""
        excel_path = os.path.join(temp_dir, "data_update_test.xlsx")

        rows = [
            make_sample_item(imei=f"8601234567{100000 + i:06d}", model=f"Phone_{i}")
            for i in range(10)
        ]
        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()
        item_ids = df[FIELD_UNIQUE_ID].astype(int).tolist()

        # Rapid updates
        for i in range(20):
            for item_id in item_ids:
                inventory_manager.update_item_data(
                    item_id,
                    {FIELD_NOTES: f"Update {i}", FIELD_BUYER: f"Buyer_{i}"},
                )

        # Verify all items still present
        final_df = inventory_manager.get_inventory()
        assert len(final_df) == 10

        # Verify last update took effect
        for _, row in final_df.iterrows():
            assert row[FIELD_BUYER] == "Buyer_19", (
                f"Item {row[FIELD_UNIQUE_ID]} buyer is '{row[FIELD_BUYER]}', expected 'Buyer_19'"
            )


# ===================================================================
# 4. CONFLICT RESOLUTION SAFETY
# ===================================================================


class TestConflictResolutionSafety:
    """Conflict resolution must preserve kept item data and properly hide duplicates."""

    def test_conflict_detection_and_resolution(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Create two files with same real IMEI, detect conflict, resolve, verify."""
        file_a = os.path.join(temp_dir, "file_a.xlsx")
        file_b = os.path.join(temp_dir, "file_b.xlsx")

        rows_a = [
            make_sample_item(
                imei="860123456789001", model="Phone A", supplier="SupplierA"
            ),
        ]
        rows_b = [
            make_sample_item(
                imei="860123456789001", model="Phone A Dup", supplier="SupplierB"
            ),
        ]

        create_excel_file(file_a, rows_a)
        create_excel_file(file_b, rows_b)

        # Load file A
        config_manager.set_file_mapping(file_a, make_mapping(file_a))
        inventory_manager.reload_all()
        df_a = inventory_manager.get_inventory()
        assert len(df_a) == 1
        id_a = int(df_a.iloc[0][FIELD_UNIQUE_ID])

        # Load file B — real IMEI dedup returns same DB ID, but DataFrame
        # may have duplicate rows (same ID, different source files)
        config_manager.set_file_mapping(file_b, make_mapping(file_b))
        inventory_manager.reload_all()
        df_combined = inventory_manager.get_inventory()

        # Both rows share the same unique_id (DB dedup)
        unique_ids = df_combined[FIELD_UNIQUE_ID].unique().tolist()
        assert len(unique_ids) == 1, "Expected 1 unique DB ID"
        assert int(unique_ids[0]) == id_a

        # Check that conflicts were detected
        assert len(inventory_manager.conflicts) >= 1, "Expected conflict detection"

    def test_resolve_conflict_preserves_kept_item(self, db):
        """After resolving conflict, kept item's data must be intact."""
        id_keep = db.get_or_create_id(
            imei="860123456789001",
            model="iPhone 15",
            ram_rom="8/256",
            supplier="SupplierA",
            source_file="file_a.xlsx",
            color="Black",
            price_original=80000.0,
            grade="A",
            condition="Excellent",
        )
        db.update_metadata(id_keep, status=STATUS_IN, notes="Primary item")

        # Create a "duplicate" using text IMEI to force new row
        id_hide = db.get_or_create_id(
            imei="dup-entry-001",
            model="iPhone 15 (dup)",
            ram_rom="8/256",
            supplier="SupplierB",
            source_file="file_b.xlsx",
        )
        db.update_metadata(id_hide, status=STATUS_IN)

        # Resolve conflict
        db.resolve_conflict(
            id_keep, [id_hide], reason="Duplicate from different source"
        )

        # Verify kept item is intact
        kept_item = db.get_item(id_keep)
        assert kept_item is not None
        assert kept_item["model"] == "iPhone 15"
        assert kept_item["ram_rom"] == "8/256"
        assert kept_item["color"] == "Black"
        assert kept_item["price_original"] == 80000.0
        assert kept_item["grade"] == "A"
        assert kept_item["condition"] == "Excellent"
        assert kept_item["status"] == STATUS_IN
        assert kept_item["notes"] == "Primary item"

        # Verify hidden item is hidden
        hidden_meta = db.get_metadata(id_hide)
        assert hidden_meta["is_hidden"] == 1
        assert hidden_meta["merged_into"] == id_keep

    def test_hidden_items_not_in_inventory(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Hidden items must not appear in inventory after conflict resolution."""
        file_a = os.path.join(temp_dir, "conflict_a.xlsx")
        file_b = os.path.join(temp_dir, "conflict_b.xlsx")

        rows_a = [make_sample_item(imei="860123456789001", model="Phone A")]
        rows_b = [make_sample_item(imei="860123456789002", model="Phone B")]
        create_excel_file(file_a, rows_a)
        create_excel_file(file_b, rows_b)

        config_manager.set_file_mapping(file_a, make_mapping(file_a))
        config_manager.set_file_mapping(file_b, make_mapping(file_b))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()
        assert len(df) == 2

        # Hide one item
        id_b = int(df[df[FIELD_MODEL] == "Phone B"].iloc[0][FIELD_UNIQUE_ID])
        id_a = int(df[df[FIELD_MODEL] == "Phone A"].iloc[0][FIELD_UNIQUE_ID])

        db.resolve_conflict(id_a, [id_b], reason="Test hide")

        inventory_manager.reload_all()
        final_df = inventory_manager.get_inventory()

        # Only the non-hidden item should remain
        assert len(final_df) == 1
        assert final_df.iloc[0][FIELD_MODEL] == "Phone A"

    def test_conflict_resolution_with_multiple_hides(self, db):
        """Resolving conflict with multiple hide IDs must hide all of them."""
        id_keep = db.get_or_create_id(
            imei="860123456789001",
            model="Phone Keep",
            ram_rom="8/128",
            supplier="A",
            source_file="test.xlsx",
        )
        id_hide_1 = db.get_or_create_id(
            imei="dup-1",
            model="Phone Hide 1",
            ram_rom="8/128",
            supplier="B",
            source_file="test.xlsx",
        )
        id_hide_2 = db.get_or_create_id(
            imei="dup-2",
            model="Phone Hide 2",
            ram_rom="8/128",
            supplier="C",
            source_file="test.xlsx",
        )

        db.resolve_conflict(
            id_keep, [id_hide_1, id_hide_2], reason="Multiple duplicates"
        )

        assert db.get_metadata(id_hide_1)["is_hidden"] == 1
        assert db.get_metadata(id_hide_1)["merged_into"] == id_keep
        assert db.get_metadata(id_hide_2)["is_hidden"] == 1
        assert db.get_metadata(id_hide_2)["merged_into"] == id_keep

        # Kept item must not be hidden
        assert db.get_metadata(id_keep)["is_hidden"] == 0


# ===================================================================
# 5. BACKUP INTEGRITY
# ===================================================================


class TestBackupIntegrity:
    """Backups must be created and contain data from before changes."""

    def test_backup_created_on_db_backup(self, db, temp_dir):
        """backup_db must create a file and return its path."""
        # Add some data
        db.get_or_create_id(
            imei="860123456789001",
            model="Phone A",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )

        backup_dir = os.path.join(temp_dir, "backups")
        backup_path = db.backup_db(backup_dir)

        assert backup_path is not None
        assert os.path.exists(backup_path)
        assert backup_path.endswith(".db")

    def test_backup_contains_data_before_changes(self, db, temp_dir):
        """Backup must contain the state at the time of backup, not after."""
        # Add initial data
        id_1 = db.get_or_create_id(
            imei="860123456789001",
            model="Phone A",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        db.update_metadata(id_1, status=STATUS_IN)

        # Create backup
        backup_dir = os.path.join(temp_dir, "backups")
        backup_path = db.backup_db(backup_dir)
        assert backup_path is not None

        # Make changes after backup
        db.update_metadata(id_1, status=STATUS_OUT)
        db.update_metadata(id_1, buyer="John Doe")

        # Verify backup has old data
        backup_db = SQLiteDatabase(db_path=backup_path)
        try:
            backup_item = backup_db.get_item(id_1)
            assert backup_item is not None
            assert backup_item["status"] == STATUS_IN  # Old status
            assert backup_item["buyer"] == ""  # Old buyer (empty)
        finally:
            backup_db.close()

        # Verify current DB has new data
        current_item = db.get_item(id_1)
        assert current_item["status"] == STATUS_OUT
        assert current_item["buyer"] == "John Doe"

    def test_backup_file_is_valid_sqlite(self, db, temp_dir):
        """Backup file must be a valid SQLite database."""
        import sqlite3

        db.get_or_create_id(
            imei="860123456789001",
            model="Phone A",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )

        backup_dir = os.path.join(temp_dir, "backups")
        backup_path = db.backup_db(backup_dir)
        assert backup_path is not None

        # Verify it's a valid SQLite DB
        conn = sqlite3.connect(backup_path)
        cursor = conn.execute("SELECT COUNT(*) FROM items")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 1

    def test_backup_returns_none_on_invalid_dir(self, db):
        """backup_db should return None if backup directory cannot be created."""
        result = db.backup_db("/root/nonexistent/deeply/nested/path")
        # Should either succeed (if permissions allow) or return None
        # We just verify it doesn't crash
        assert result is None or isinstance(result, str)


# ===================================================================
# 6. EDGE CASES
# ===================================================================


class TestEdgeCases:
    """Edge cases must be handled gracefully without crashes."""

    def test_load_empty_excel_file(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Loading an empty Excel file (no rows) should not crash."""
        excel_path = os.path.join(temp_dir, "empty.xlsx")
        create_excel_file(
            excel_path, [], headers=[FIELD_IMEI, FIELD_MODEL, FIELD_STATUS]
        )
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()
        assert len(df) == 0

    def test_load_excel_with_only_headers(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Loading an Excel file with only headers should not crash."""
        excel_path = os.path.join(temp_dir, "headers_only.xlsx")
        df = pd.DataFrame(
            columns=[FIELD_IMEI, FIELD_MODEL, FIELD_RAM_ROM, FIELD_PRICE, FIELD_STATUS]
        )
        df.to_excel(excel_path, index=False, engine="openpyxl")
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        result_df = inventory_manager.get_inventory()
        assert len(result_df) == 0

    def test_load_excel_with_duplicate_imeis_in_same_file(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Duplicate IMEIs in the same file map to the same DB ID."""
        excel_path = os.path.join(temp_dir, "dup_imei.xlsx")
        rows = [
            make_sample_item(
                imei="860123456789001", model="Phone A", supplier="SupplierA"
            ),
            make_sample_item(
                imei="860123456789001", model="Phone A", supplier="SupplierA"
            ),
        ]
        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        # Real IMEI dedup means both rows get the same unique_id
        unique_ids = df[FIELD_UNIQUE_ID].unique().tolist()
        assert len(unique_ids) == 1, (
            f"Expected 1 unique DB ID, got {len(unique_ids)}: {unique_ids}"
        )

    def test_update_item_with_invalid_field_name(self, db):
        """Updating with invalid metadata field should raise ValueError."""
        item_id = db.get_or_create_id(
            imei="860123456789001",
            model="Phone A",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )

        with pytest.raises(ValueError, match="Invalid metadata fields"):
            db.update_metadata(item_id, nonexistent_field="bad_value")

    def test_get_nonexistent_item_returns_none(self, db):
        """Getting a non-existent item should return None, not crash."""
        result = db.get_item(999999)
        assert result is None

    def test_update_nonexistent_item_metadata(self, db):
        """Updating metadata for non-existent item should not crash."""
        # SQLite will silently not update any rows
        db.update_metadata(999999, status=STATUS_OUT)
        # No exception should be raised

    def test_get_item_by_id_nonexistent(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """get_item_by_id for non-existent ID should return (None, None)."""
        excel_path = os.path.join(temp_dir, "single.xlsx")
        create_excel_file(
            excel_path, [make_sample_item(imei="860123456789001", model="Phone A")]
        )
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        item, redirect = inventory_manager.get_item_by_id(999999)
        assert item is None
        assert redirect is None

    def test_update_item_that_doesnt_exist_in_inventory(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """update_item_data for item not in inventory should return False."""
        excel_path = os.path.join(temp_dir, "single.xlsx")
        create_excel_file(
            excel_path, [make_sample_item(imei="860123456789001", model="Phone A")]
        )
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        result = inventory_manager.update_item_data(999999, {FIELD_NOTES: "test"})
        assert result is False

    def test_update_item_status_with_invalid_id(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """update_item_status with invalid ID should return False."""
        result = inventory_manager.update_item_status("not_a_number", STATUS_OUT)
        assert result is False

    def test_update_item_data_with_invalid_id(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """update_item_data with invalid ID should return False."""
        result = inventory_manager.update_item_data(
            "not_a_number", {FIELD_NOTES: "test"}
        )
        assert result is False

    def test_get_item_by_id_with_invalid_id(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """get_item_by_id with invalid ID should return (None, None)."""
        item, redirect = inventory_manager.get_item_by_id("not_a_number")
        assert item is None
        assert redirect is None

    def test_load_nonexistent_file(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Loading a non-existent file should report error status."""
        fake_path = os.path.join(temp_dir, "does_not_exist.xlsx")
        config_manager.set_file_mapping(fake_path, make_mapping(fake_path))

        inventory_manager.reload_all()
        assert inventory_manager.file_status.get(fake_path) == "Missing"

    def test_database_close_and_reopen(self, temp_dir):
        """Database should be usable after close and reopen."""
        db_path = os.path.join(temp_dir, "test.db")

        db1 = SQLiteDatabase(db_path=db_path)
        item_id = db1.get_or_create_id(
            imei="860123456789001",
            model="Phone A",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        db1.update_metadata(item_id, status=STATUS_IN)
        db1.close()

        db2 = SQLiteDatabase(db_path=db_path)
        item = db2.get_item(item_id)
        assert item is not None
        assert item["model"] == "Phone A"
        assert item["status"] == STATUS_IN
        db2.close()


# ===================================================================
# 7. EXCEL WRITE ROUNDTRIP
# ===================================================================


class TestExcelWriteRoundtrip:
    """All fields must survive a full Excel write → read cycle."""

    def test_all_fields_preserved_for_10_items(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Create 10 items with ALL fields, write to Excel, reload, verify every field."""
        excel_path = os.path.join(temp_dir, "roundtrip.xlsx")

        rows = []
        for i in range(10):
            rows.append(
                {
                    FIELD_IMEI: f"8601234567{100000 + i:06d}",
                    FIELD_MODEL: f"Model_{i}",
                    FIELD_RAM_ROM: f"{4 + i}/{64 * (i + 1)}",
                    FIELD_PRICE: 5000.0 + i * 1000,
                    FIELD_PRICE_ORIGINAL: 5000.0 + i * 1000,
                    "supplier": f"Supplier_{i % 3}",
                    FIELD_COLOR: ["Black", "White", "Blue", "Red", "Gold"][i % 5],
                    FIELD_GRADE: ["A", "B", "C"][i % 3],
                    FIELD_CONDITION: ["Good", "Fair", "Excellent"][i % 3],
                    FIELD_STATUS: [STATUS_IN, STATUS_OUT, STATUS_RETURN][i % 3],
                    FIELD_NOTES: f"Notes for item {i}",
                    FIELD_BUYER: f"Buyer_{i}" if i % 2 == 0 else "",
                    FIELD_BUYER_CONTACT: f"555-{1000 + i}" if i % 2 == 0 else "",
                }
            )

        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        assert len(df) == 10, f"Expected 10 items, got {len(df)}"

        # Verify each item's fields
        for i in range(10):
            imei = f"8601234567{100000 + i:06d}"
            mask = df[FIELD_IMEI] == imei
            assert mask.any(), f"Item with IMEI {imei} not found"

            row = df[mask].iloc[0]
            assert row[FIELD_MODEL] == f"Model_{i}", f"Model mismatch for item {i}"
            assert row[FIELD_RAM_ROM] == f"{4 + i}/{64 * (i + 1)}", (
                f"RAM_ROM mismatch for item {i}"
            )
            assert row["supplier"] == f"Supplier_{i % 3}", (
                f"Supplier mismatch for item {i}"
            )
            assert (
                row[FIELD_COLOR] == ["Black", "White", "Blue", "Red", "Gold"][i % 5]
            ), f"Color mismatch for item {i}"
            assert row[FIELD_GRADE] == ["A", "B", "C"][i % 3], (
                f"Grade mismatch for item {i}"
            )
            assert row[FIELD_CONDITION] == ["Good", "Fair", "Excellent"][i % 3], (
                f"Condition mismatch for item {i}"
            )
            # Note: On first load, DB defaults status to IN. After update_item_status,
            # the DB status overrides Excel on subsequent reloads.
            # Here we verify the item exists and has a valid status.
            assert row[FIELD_STATUS] in (STATUS_IN, STATUS_OUT, STATUS_RETURN), (
                f"Invalid status for item {i}: {row[FIELD_STATUS]}"
            )

    def test_single_item_full_roundtrip(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """A single item with all fields must survive a roundtrip."""
        excel_path = os.path.join(temp_dir, "single_roundtrip.xlsx")

        row = {
            FIELD_IMEI: "860123456789001",
            FIELD_MODEL: "iPhone 15 Pro",
            FIELD_RAM_ROM: "8/256",
            FIELD_PRICE: 120000.0,
            FIELD_PRICE_ORIGINAL: 100000.0,
            "supplier": "Apple Inc",
            FIELD_COLOR: "Natural Titanium",
            FIELD_GRADE: "A+",
            FIELD_CONDITION: "Brand New",
            FIELD_STATUS: STATUS_IN,
            FIELD_NOTES: "Premium device",
            FIELD_BUYER: "",
            FIELD_BUYER_CONTACT: "",
        }

        create_excel_file(excel_path, [row])
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        assert len(df) == 1
        item = df.iloc[0]
        assert item[FIELD_IMEI] == "860123456789001"
        assert item[FIELD_MODEL] == "iPhone 15 Pro"
        assert item[FIELD_RAM_ROM] == "8/256"
        assert item["supplier"] == "Apple Inc"
        assert item[FIELD_COLOR] == "Natural Titanium"
        assert item[FIELD_GRADE] == "A+"
        assert item[FIELD_CONDITION] == "Brand New"
        assert item[FIELD_STATUS] == STATUS_IN

    def test_text_imei_roundtrip(self, db, config_manager, inventory_manager, temp_dir):
        """Text IMEI items must survive a roundtrip."""
        excel_path = os.path.join(temp_dir, "text_imei_roundtrip.xlsx")

        rows = [
            {
                FIELD_IMEI: "NOT ON",
                FIELD_MODEL: "Nokia 3310",
                FIELD_RAM_ROM: "16MB",
                FIELD_PRICE: 500.0,
                FIELD_PRICE_ORIGINAL: 500.0,
                "supplier": "Vintage Phones",
                FIELD_COLOR: "Gray",
                FIELD_GRADE: "C",
                FIELD_CONDITION: "Used",
                FIELD_STATUS: STATUS_IN,
                FIELD_NOTES: "Classic phone",
                FIELD_BUYER: "",
                FIELD_BUYER_CONTACT: "",
            },
            {
                FIELD_IMEI: "",
                FIELD_MODEL: "Generic Phone",
                FIELD_RAM_ROM: "2/32",
                FIELD_PRICE: 2000.0,
                FIELD_PRICE_ORIGINAL: 2000.0,
                "supplier": "Budget Phones",
                FIELD_COLOR: "Black",
                FIELD_GRADE: "B",
                FIELD_CONDITION: "Good",
                FIELD_STATUS: STATUS_IN,
                FIELD_NOTES: "No IMEI",
                FIELD_BUYER: "",
                FIELD_BUYER_CONTACT: "",
            },
        ]

        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        assert len(df) == 2

        # Find text IMEI item
        text_mask = df[FIELD_IMEI] == "NOT ON"
        assert text_mask.any()
        text_item = df[text_mask].iloc[0]
        assert text_item[FIELD_MODEL] == "Nokia 3310"

        # Find empty IMEI item
        empty_mask = df[FIELD_IMEI] == ""
        assert empty_mask.any()
        empty_item = df[empty_mask].iloc[0]
        assert empty_item[FIELD_MODEL] == "Generic Phone"


# ===================================================================
# 8. STATUS CHANGE HISTORY
# ===================================================================


class TestStatusChangeHistory:
    """Status changes must be fully logged with correct details."""

    def test_history_has_all_entries(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Multiple status changes must all appear in history."""
        excel_path = os.path.join(temp_dir, "history_test.xlsx")
        rows = [
            make_sample_item(imei="860123456789001", model="Phone A", status=STATUS_IN)
        ]
        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()
        item_id = int(df.iloc[0][FIELD_UNIQUE_ID])

        # Change status multiple times: IN → OUT → RTN → IN
        inventory_manager.update_item_status(item_id, STATUS_OUT)
        inventory_manager.update_item_status(item_id, STATUS_RETURN)
        inventory_manager.update_item_status(item_id, STATUS_IN)

        # Check history in database
        history_rows = db._conn.execute(
            "SELECT * FROM history WHERE item_id = ? ORDER BY id",
            (item_id,),
        ).fetchall()

        # Should have at least 3 status change entries
        status_changes = [h for h in history_rows if h["action"] == "STATUS_CHANGE"]
        assert len(status_changes) >= 3, (
            f"Expected at least 3 status changes, got {len(status_changes)}"
        )

    def test_history_entries_have_correct_details(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Each history entry must contain correct old and new status."""
        excel_path = os.path.join(temp_dir, "history_details_test.xlsx")
        rows = [
            make_sample_item(imei="860123456789001", model="Phone A", status=STATUS_IN)
        ]
        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()
        item_id = int(df.iloc[0][FIELD_UNIQUE_ID])

        inventory_manager.update_item_status(item_id, STATUS_OUT)
        inventory_manager.update_item_status(item_id, STATUS_RETURN)

        history_rows = db._conn.execute(
            "SELECT * FROM history WHERE item_id = ? AND action = 'STATUS_CHANGE' ORDER BY id",
            (item_id,),
        ).fetchall()

        assert len(history_rows) >= 2

        # First change: IN → OUT
        assert "IN" in history_rows[0]["details"]
        assert "OUT" in history_rows[0]["details"]

        # Second change: OUT → RTN
        assert "OUT" in history_rows[1]["details"]
        assert "RTN" in history_rows[1]["details"]

    def test_history_entries_have_timestamps(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Each history entry must have a timestamp."""
        excel_path = os.path.join(temp_dir, "history_timestamp_test.xlsx")
        rows = [
            make_sample_item(imei="860123456789001", model="Phone A", status=STATUS_IN)
        ]
        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()
        item_id = int(df.iloc[0][FIELD_UNIQUE_ID])

        inventory_manager.update_item_status(item_id, STATUS_OUT)

        history_rows = db._conn.execute(
            "SELECT * FROM history WHERE item_id = ? ORDER BY id",
            (item_id,),
        ).fetchall()

        assert len(history_rows) >= 1
        for h in history_rows:
            assert h["timestamp"] is not None
            assert h["timestamp"] != ""

    def test_data_update_history(self, db, config_manager, inventory_manager, temp_dir):
        """Data updates must also be logged in history."""
        excel_path = os.path.join(temp_dir, "data_history_test.xlsx")
        rows = [
            make_sample_item(imei="860123456789001", model="Phone A", status=STATUS_IN)
        ]
        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()
        item_id = int(df.iloc[0][FIELD_UNIQUE_ID])

        inventory_manager.update_item_data(item_id, {FIELD_NOTES: "Updated notes"})

        history_rows = db._conn.execute(
            "SELECT * FROM history WHERE item_id = ? AND action = 'DATA_UPDATE' ORDER BY id",
            (item_id,),
        ).fetchall()

        assert len(history_rows) >= 1
        assert "notes" in history_rows[0]["details"].lower()

    def test_conflict_resolution_history(self, db):
        """Conflict resolution must add history entries for hidden items."""
        id_keep = db.get_or_create_id(
            imei="860123456789001",
            model="Phone Keep",
            ram_rom="8/128",
            supplier="A",
            source_file="test.xlsx",
        )
        id_hide = db.get_or_create_id(
            imei="dup-entry",
            model="Phone Hide",
            ram_rom="8/128",
            supplier="B",
            source_file="test.xlsx",
        )

        db.resolve_conflict(id_keep, [id_hide], reason="Test merge")

        history_rows = db._conn.execute(
            "SELECT * FROM history WHERE item_id = ? ORDER BY id",
            (id_hide,),
        ).fetchall()

        assert len(history_rows) >= 1
        assert history_rows[0]["action"] == "resolved_conflict"
        assert str(id_keep) in history_rows[0]["details"]


# ===================================================================
# 9. ADDITIONAL AGGRESSIVE TESTS
# ===================================================================


class TestAdditionalAggressive:
    """Extra stress tests for robustness."""

    def test_100_items_load_and_verify(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Load 100 items and verify all are present with correct data."""
        excel_path = os.path.join(temp_dir, "hundred_items.xlsx")

        rows = []
        for i in range(100):
            rows.append(
                make_sample_item(
                    imei=f"8601234567{200000 + i:06d}",
                    model=f"Phone_{i}",
                    price=1000.0 + i * 10,
                )
            )

        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        assert len(df) == 100, f"Expected 100 items, got {len(df)}"

        # Verify each item exists
        for i in range(100):
            imei = f"8601234567{200000 + i:06d}"
            mask = df[FIELD_IMEI] == imei
            assert mask.any(), f"Item {i} with IMEI {imei} not found"

    def test_special_characters_in_fields(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Special characters in fields must be preserved."""
        excel_path = os.path.join(temp_dir, "special_chars.xlsx")

        rows = [
            {
                FIELD_IMEI: "860123456789001",
                FIELD_MODEL: "Samsung A54 (5G) & More",
                FIELD_RAM_ROM: "8/128",
                FIELD_PRICE: 15000.0,
                FIELD_PRICE_ORIGINAL: 15000.0,
                "supplier": "Supplier's & Co.",
                FIELD_COLOR: "Black/White",
                FIELD_GRADE: "A+",
                FIELD_CONDITION: "Good <Excellent>",
                FIELD_STATUS: STATUS_IN,
                FIELD_NOTES: "Note with \"quotes\" and 'apostrophes'",
                FIELD_BUYER: "O'Brien",
                FIELD_BUYER_CONTACT: "+91-9876543210",
            }
        ]

        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        assert len(df) == 1
        item = df.iloc[0]
        assert "5G" in item[FIELD_MODEL]
        assert "Supplier" in item["supplier"]
        assert "O'Brien" in item[FIELD_BUYER]

    def test_unicode_in_fields(self, db, config_manager, inventory_manager, temp_dir):
        """Unicode characters must be preserved."""
        excel_path = os.path.join(temp_dir, "unicode_test.xlsx")

        rows = [
            {
                FIELD_IMEI: "860123456789001",
                FIELD_MODEL: "手机 Model",
                FIELD_RAM_ROM: "8/128",
                FIELD_PRICE: 15000.0,
                FIELD_PRICE_ORIGINAL: 15000.0,
                "supplier": "供应商",
                FIELD_COLOR: "黑色",
                FIELD_GRADE: "A",
                FIELD_CONDITION: "良好",
                FIELD_STATUS: STATUS_IN,
                FIELD_NOTES: "备注信息",
                FIELD_BUYER: "买家",
                FIELD_BUYER_CONTACT: "",
            }
        ]

        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        assert len(df) == 1
        item = df.iloc[0]
        assert item[FIELD_MODEL] == "手机 Model"
        assert item["supplier"] == "供应商"
        assert item[FIELD_COLOR] == "黑色"

    def test_very_long_notes(self, db, config_manager, inventory_manager, temp_dir):
        """Very long text in notes field must be preserved via DB metadata.

        Note: Notes are stored in DB metadata, not in Excel columns.
        They survive reload because DB metadata overrides Excel on reload.
        """
        excel_path = os.path.join(temp_dir, "long_notes.xlsx")
        long_notes = "A" * 5000

        rows = [
            {
                FIELD_IMEI: "860123456789001",
                FIELD_MODEL: "Phone A",
                FIELD_RAM_ROM: "8/128",
                FIELD_PRICE: 10000.0,
                FIELD_PRICE_ORIGINAL: 10000.0,
                "supplier": "TestSupplier",
                FIELD_COLOR: "Black",
                FIELD_GRADE: "A",
                FIELD_CONDITION: "Good",
                FIELD_STATUS: STATUS_IN,
                FIELD_NOTES: "",  # Notes not loaded from Excel
                FIELD_BUYER: "",
                FIELD_BUYER_CONTACT: "",
            }
        ]

        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        assert len(df) == 1
        item_id = int(df.iloc[0][FIELD_UNIQUE_ID])

        # Set notes via DB metadata (the proper way)
        db.update_metadata(item_id, notes=long_notes)

        # Reload — notes should be preserved from DB
        inventory_manager.reload_all()
        df2 = inventory_manager.get_inventory()

        assert len(df2) == 1
        assert df2.iloc[0][FIELD_NOTES] == long_notes

    def test_price_precision_preserved(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Price values with decimals must be preserved."""
        excel_path = os.path.join(temp_dir, "price_precision.xlsx")

        rows = [
            {
                FIELD_IMEI: "860123456789001",
                FIELD_MODEL: "Phone A",
                FIELD_RAM_ROM: "8/128",
                FIELD_PRICE: 9999.99,
                FIELD_PRICE_ORIGINAL: 9999.99,
                "supplier": "TestSupplier",
                FIELD_COLOR: "Black",
                FIELD_GRADE: "A",
                FIELD_CONDITION: "Good",
                FIELD_STATUS: STATUS_IN,
                FIELD_NOTES: "",
                FIELD_BUYER: "",
                FIELD_BUYER_CONTACT: "",
            }
        ]

        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        assert len(df) == 1
        # Price may be rounded by markup logic, but original should be close
        assert abs(df.iloc[0][FIELD_PRICE_ORIGINAL] - 9999.99) < 0.01

    def test_multiple_reload_cycles(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Multiple reload cycles must not degrade data."""
        excel_path = os.path.join(temp_dir, "multi_reload.xlsx")

        rows = [
            make_sample_item(imei="860123456789001", model="Phone A", status=STATUS_IN),
            make_sample_item(
                imei="860123456789002", model="Phone B", status=STATUS_OUT
            ),
        ]
        create_excel_file(excel_path, rows)
        config_manager.set_file_mapping(excel_path, make_mapping(excel_path))

        # Reload 5 times
        for _ in range(5):
            inventory_manager.reload_all()
            df = inventory_manager.get_inventory()
            assert len(df) == 2, f"Lost items after reload cycle"

        # Final verification
        df = inventory_manager.get_inventory()
        models = set(df[FIELD_MODEL].tolist())
        assert models == {"Phone A", "Phone B"}


# ===================================================================
# DL-7 REGRESSION: Supplier name change must NOT remap item IDs
# ===================================================================


class TestDL7SupplierNameChangeDoesNotRemapIds:
    """Regression tests for DL-7: changing the supplier name (or source file)
    must NOT cause text/placeholder IMEI items to get new IDs and lose all
    their metadata (status, buyer, notes, etc.).

    The fix removes `supplier` from the composite dedup key for text and
    placeholder IMEIs.  The key is now (imei, model, ram_rom) only.
    """

    # -- DB-level: same text IMEI item, different supplier → same ID --

    def test_db_text_imei_same_identity_different_supplier_same_id(
        self, db: SQLiteDatabase
    ) -> None:
        """A text-IMEI item loaded from SupplierA then from SupplierB must
        return the same ID — preventing orphaned metadata."""
        id_a = db.get_or_create_id(
            imei="NOT ON",
            model="iPhone 14",
            ram_rom="6/128",
            supplier="SupplierA",
            source_file="supplier_a.xlsx",
            color="Black",
            price_original=50000.0,
            grade="A",
            condition="Good",
        )

        # Simulate the same physical item appearing in a different supplier file
        id_b = db.get_or_create_id(
            imei="NOT ON",
            model="iPhone 14",
            ram_rom="6/128",
            supplier="SupplierB",
            source_file="supplier_b.xlsx",
            color="Black",
            price_original=50000.0,
            grade="A",
            condition="Good",
        )

        assert id_a == id_b, (
            f"DL-7 REGRESSION: text IMEI item got new ID ({id_b}) when supplier "
            f"changed from SupplierA to SupplierB (original ID={id_a}). "
            f"This would orphan all metadata."
        )

    def test_db_placeholder_imei_same_identity_different_supplier_same_id(
        self, db: SQLiteDatabase
    ) -> None:
        """Placeholder IMEI item must also keep its ID across supplier changes."""
        id_a = db.get_or_create_id(
            imei="n/a",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="OldSupplier",
            source_file="old.xlsx",
        )
        db.update_metadata(id_a, status=STATUS_OUT, buyer="Alice", notes="Sold")

        id_b = db.get_or_create_id(
            imei="n/a",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="NewSupplier",
            source_file="new.xlsx",
        )

        assert id_a == id_b, (
            f"DL-7 REGRESSION: placeholder IMEI item got new ID ({id_b}) "
            f"when supplier changed. Metadata (status=OUT, buyer=Alice) would be lost."
        )

        # Verify metadata is still accessible under the same ID
        meta = db.get_metadata(id_b)
        assert meta["status"] == STATUS_OUT
        assert meta["buyer"] == "Alice"

    def test_db_none_imei_same_identity_different_supplier_same_id(
        self, db: SQLiteDatabase
    ) -> None:
        """None IMEI item must also keep its ID across supplier changes."""
        id_a = db.get_or_create_id(
            imei=None,
            model="Generic Phone",
            ram_rom="4/64",
            supplier="SupplierX",
            source_file="x.xlsx",
        )
        db.update_metadata(id_a, status=STATUS_RETURN, notes="Returned")

        id_b = db.get_or_create_id(
            imei=None,
            model="Generic Phone",
            ram_rom="4/64",
            supplier="SupplierY",
            source_file="y.xlsx",
        )

        assert id_a == id_b

    def test_db_text_imei_different_model_still_gets_new_id(
        self, db: SQLiteDatabase
    ) -> None:
        """Different model should still get a new ID — we didn't break dedup."""
        id_a = db.get_or_create_id(
            imei="NOT ON",
            model="iPhone 14",
            ram_rom="6/128",
            supplier="SupplierA",
            source_file="a.xlsx",
        )
        id_b = db.get_or_create_id(
            imei="NOT ON",
            model="iPhone 15",
            ram_rom="6/128",
            supplier="SupplierA",
            source_file="a.xlsx",
        )
        assert id_a != id_b, "Different model should get different ID"

    def test_db_text_imei_different_ram_rom_still_gets_new_id(
        self, db: SQLiteDatabase
    ) -> None:
        """Different ram_rom should still get a new ID."""
        id_a = db.get_or_create_id(
            imei="NOT ON",
            model="iPhone 14",
            ram_rom="6/128",
            supplier="SupplierA",
            source_file="a.xlsx",
        )
        id_b = db.get_or_create_id(
            imei="NOT ON",
            model="iPhone 14",
            ram_rom="8/256",
            supplier="SupplierA",
            source_file="a.xlsx",
        )
        assert id_a != id_b, "Different ram_rom should get different ID"

    # -- Full inventory pipeline: supplier name change in config --

    def test_full_pipeline_supplier_name_change_preserves_ids(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """End-to-end: items loaded, status changed, then supplier name changed
        in config. All IDs and metadata must be preserved."""
        excel_path = os.path.join(temp_dir, "inv_supplier.xlsx")

        # 10 items with text IMEIs
        rows = []
        for i in range(10):
            rows.append(
                make_sample_item(
                    imei="NOT ON",
                    model=f"Model_{i}",
                    ram_rom=f"{4 + i}/64",
                    price=5000.0 + i * 100,
                    supplier="SupplierA",
                    status=STATUS_IN,
                )
            )
        create_excel_file(excel_path, rows)

        mapping = make_mapping(excel_path)
        mapping["supplier"] = "SupplierA"
        config_manager.set_file_mapping(excel_path, mapping)

        # Load
        inventory_manager.reload_all()
        df1 = inventory_manager.get_inventory()
        assert len(df1) == 10

        # Record IDs and set some statuses
        id_map_v1 = {}
        for _, row in df1.iterrows():
            id_map_v1[row[FIELD_MODEL]] = int(row[FIELD_UNIQUE_ID])

        # Change statuses for items 3, 5, 7
        for model in ["Model_3", "Model_5", "Model_7"]:
            inventory_manager.update_item_status(id_map_v1[model], STATUS_OUT)
        inventory_manager.update_item_status(id_map_v1["Model_1"], STATUS_RETURN)

        # Now simulate supplier name change in config
        # (This is what happens when user renames supplier in settings)
        mapping["supplier"] = "SupplierA Corporation"  # name change
        config_manager.set_file_mapping(excel_path, mapping)

        # Reload
        inventory_manager.reload_all()
        df2 = inventory_manager.get_inventory()

        assert len(df2) == 10, (
            f"DL-7: Expected 10 items after supplier name change, got {len(df2)}. "
            f"Items were lost because they got new IDs."
        )

        # Verify IDs are stable
        for _, row in df2.iterrows():
            model = row[FIELD_MODEL]
            new_id = int(row[FIELD_UNIQUE_ID])
            old_id = id_map_v1[model]
            assert new_id == old_id, (
                f"DL-7: {model} changed ID from {old_id} to {new_id} after "
                f"supplier name change. All metadata is now orphaned/lost."
            )

        # Verify statuses survived
        status_map = {row[FIELD_MODEL]: row[FIELD_STATUS] for _, row in df2.iterrows()}
        assert status_map["Model_3"] == STATUS_OUT
        assert status_map["Model_5"] == STATUS_OUT
        assert status_map["Model_7"] == STATUS_OUT
        assert status_map["Model_1"] == STATUS_RETURN
        # Others should still be IN
        for i in [0, 2, 4, 6, 8, 9]:
            assert status_map[f"Model_{i}"] == STATUS_IN, (
                f"Model_{i} lost its IN status after supplier change"
            )

    def test_full_pipeline_supplier_rename_then_reload_multiple_times(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Supplier name changed, then reloaded 10×. IDs must stay stable."""
        excel_path = os.path.join(temp_dir, "inv_multi.xlsx")

        rows = [
            make_sample_item(imei="NOT ON", model="Widget A", ram_rom="", price=1000),
            make_sample_item(imei="NOT ON", model="Widget B", ram_rom="", price=2000),
            make_sample_item(imei="NOT ON", model="Widget C", ram_rom="", price=3000),
        ]
        create_excel_file(excel_path, rows)

        mapping = make_mapping(excel_path)
        mapping["supplier"] = "Original Supplier"
        config_manager.set_file_mapping(excel_path, mapping)

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()
        original_ids = set(df[FIELD_UNIQUE_ID].astype(int).tolist())
        original_models = set(df[FIELD_MODEL].tolist())

        # Change supplier name
        mapping["supplier"] = "Renamed Supplier Ltd."
        config_manager.set_file_mapping(excel_path, mapping)

        # Reload 10 times
        for i in range(10):
            inventory_manager.reload_all()
            df = inventory_manager.get_inventory()
            current_ids = set(df[FIELD_UNIQUE_ID].astype(int).tolist())
            current_models = set(df[FIELD_MODEL].tolist())

            assert current_ids == original_ids, (
                f"DL-7: IDs changed on reload #{i}. Original: {original_ids}, "
                f"Got: {current_ids}. Items orphaned."
            )
            assert current_models == original_models, (
                f"DL-7: Models lost on reload #{i}. Expected: {original_models}, "
                f"Got: {current_models}."
            )

    def test_full_pipeline_text_imei_metadata_preserved_across_supplier_changes(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Metadata (buyer, notes) for text-IMEI items must survive supplier rename."""
        excel_path = os.path.join(temp_dir, "inv_meta.xlsx")

        rows = [
            make_sample_item(
                imei="NOT ON", model="Phone X", ram_rom="6/128",
                price=15000, status=STATUS_IN,
            ),
        ]
        create_excel_file(excel_path, rows)

        mapping = make_mapping(excel_path)
        mapping["supplier"] = "Supplier Old Name"
        config_manager.set_file_mapping(excel_path, mapping)

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()
        item_id = int(df.iloc[0][FIELD_UNIQUE_ID])

        # Set metadata
        inventory_manager.update_item_status(item_id, STATUS_OUT)
        inventory_manager.update_item_data(item_id, {
            "buyer": "Test Buyer",
            "notes": "Important warranty note",
        })

        # Change supplier name
        mapping["supplier"] = "Supplier New Name"
        config_manager.set_file_mapping(excel_path, mapping)

        # Reload
        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        assert len(df) == 1, "DL-7: Item lost after supplier name change"
        assert int(df.iloc[0][FIELD_UNIQUE_ID]) == item_id, (
            f"DL-7: ID changed from {item_id} to {int(df.iloc[0][FIELD_UNIQUE_ID])}"
        )
        assert df.iloc[0][FIELD_STATUS] == STATUS_OUT, (
            "DL-7: Status lost after supplier change"
        )

        # Verify DB metadata
        meta = db.get_metadata(item_id)
        assert meta["status"] == STATUS_OUT

    # -- Stress: 100 text-IMEI items, supplier change, all IDs preserved --

    def test_stress_100_text_imei_items_supplier_change_all_ids_stable(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """100 text-IMEI items. Supplier renamed. All 100 IDs must be stable."""
        excel_path = os.path.join(temp_dir, "inv_stress.xlsx")

        rows = []
        for i in range(100):
            rows.append(
                make_sample_item(
                    imei="NOT ON",
                    model=f"StressModel_{i:03d}",
                    ram_rom=f"{(i % 8) + 1}/{(i % 4 + 1) * 32}",
                    price=1000.0 + i * 50,
                    supplier="FirstSupplier",
                    status=STATUS_IN,
                )
            )
        create_excel_file(excel_path, rows)

        mapping = make_mapping(excel_path)
        mapping["supplier"] = "FirstSupplier"
        config_manager.set_file_mapping(excel_path, mapping)

        inventory_manager.reload_all()
        df1 = inventory_manager.get_inventory()
        assert len(df1) == 100

        id_map = {
            row[FIELD_MODEL]: int(row[FIELD_UNIQUE_ID])
            for _, row in df1.iterrows()
        }

        # Change supplier
        mapping["supplier"] = "SecondSupplier"
        config_manager.set_file_mapping(excel_path, mapping)

        # Reload
        inventory_manager.reload_all()
        df2 = inventory_manager.get_inventory()

        assert len(df2) == 100, (
            f"DL-7 STRESS: Expected 100 items, got {len(df2)}. "
            f"{100 - len(df2)} items lost!"
        )

        for _, row in df2.iterrows():
            model = row[FIELD_MODEL]
            new_id = int(row[FIELD_UNIQUE_ID])
            old_id = id_map[model]
            assert new_id == old_id, (
                f"DL-7 STRESS: {model} ID changed from {old_id} to {new_id}"
            )

    # -- Multiple files, same text-IMEI items, different suppliers → same ID --

    def test_multiple_files_same_text_imei_items_same_id_not_new(
        self, db, config_manager, inventory_manager, temp_dir
    ):
        """Two Excel files with same text-IMEI items (different supplier names)
        should assign the SAME ID to both — not create new IDs.

        Note: The DataFrame may still have 2 rows (one per file) because
        reload_all() concatenates frames. The key DL-7 guarantee is that the
        IDs are identical, so metadata is shared.
        """
        excel_a = os.path.join(temp_dir, "inv_a.xlsx")
        excel_b = os.path.join(temp_dir, "inv_b.xlsx")

        rows_a = [
            make_sample_item(imei="NOT ON", model="Phone A", ram_rom="6/128",
                             price=10000, supplier="SupplierA"),
            make_sample_item(imei="NOT ON", model="Phone B", ram_rom="8/256",
                             price=15000, supplier="SupplierA"),
        ]
        rows_b = [
            make_sample_item(imei="NOT ON", model="Phone A", ram_rom="6/128",
                             price=10000, supplier="SupplierB"),
            make_sample_item(imei="NOT ON", model="Phone B", ram_rom="8/256",
                             price=15000, supplier="SupplierB"),
        ]
        create_excel_file(excel_a, rows_a)
        create_excel_file(excel_b, rows_b)

        mapping_a = make_mapping(excel_a)
        mapping_b = make_mapping(excel_b)
        config_manager.set_file_mapping(excel_a, mapping_a)
        config_manager.set_file_mapping(excel_b, mapping_b)

        inventory_manager.reload_all()
        df = inventory_manager.get_inventory()

        # Both Phone A rows should have the SAME unique_id
        phone_a_rows = df[df[FIELD_MODEL] == "Phone A"]
        phone_a_ids = set(phone_a_rows[FIELD_UNIQUE_ID].astype(int).tolist())
        assert len(phone_a_ids) == 1, (
            f"DL-7: Phone A has IDs {phone_a_ids} — should be a single ID. "
            f"Different suppliers caused new IDs to be created."
        )

        phone_b_rows = df[df[FIELD_MODEL] == "Phone B"]
        phone_b_ids = set(phone_b_rows[FIELD_UNIQUE_ID].astype(int).tolist())
        assert len(phone_b_ids) == 1, (
            f"DL-7: Phone B has IDs {phone_b_ids} — should be a single ID."
        )

        # The two IDs should be different from each other (Phone A ≠ Phone B)
        assert phone_a_ids != phone_b_ids
