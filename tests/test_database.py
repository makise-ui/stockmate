"""Tests for the core database module."""

import os
import tempfile

import pytest

from core.database import SQLiteDatabase


# ---------------------------------------------------------------------------
# Fixture — per-test isolated database
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


# ---------------------------------------------------------------------------
# get_or_create_id — real IMEI dedup
# ---------------------------------------------------------------------------


class TestGetOrCreateIdRealImei:
    """Real IMEI (14-16 digits) should deduplicate on first match."""

    def test_first_insert_returns_new_id(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        assert isinstance(item_id, int)
        assert item_id > 0

    def test_same_real_imei_returns_existing_id(self, db: SQLiteDatabase) -> None:
        first = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        second = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="OtherSupplier",
            source_file="other.xlsx",
        )
        assert second == first

    def test_different_real_imei_returns_new_id(self, db: SQLiteDatabase) -> None:
        first = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        second = db.get_or_create_id(
            imei="860123456789013",
            model="iPhone 15",
            ram_rom="6/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        assert second != first


# ---------------------------------------------------------------------------
# get_or_create_id — text IMEI always-new
# ---------------------------------------------------------------------------


class TestGetOrCreateIdTextImei:
    """Text IMEI (non-digit, non-placeholder) should always create a new row."""

    def test_text_imei_always_new(self, db: SQLiteDatabase) -> None:
        first = db.get_or_create_id(
            imei="serial-abc-123",
            model="Nokia 3310",
            ram_rom="",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        second = db.get_or_create_id(
            imei="serial-abc-123",
            model="Nokia 3310",
            ram_rom="",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        assert second != first


# ---------------------------------------------------------------------------
# get_or_create_id — placeholder IMEI always-new
# ---------------------------------------------------------------------------


class TestGetOrCreateIdPlaceholderImei:
    """Placeholder IMEI (e.g. 'n/a', 'none') should always create a new row."""

    @pytest.mark.parametrize("placeholder", ["n/a", "none", "not on", "-", "unknown"])
    def test_placeholder_imei_always_new(
        self, db: SQLiteDatabase, placeholder: str
    ) -> None:
        first = db.get_or_create_id(
            imei=placeholder,
            model="Generic Phone",
            ram_rom="",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        second = db.get_or_create_id(
            imei=placeholder,
            model="Generic Phone",
            ram_rom="",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        assert second != first

    def test_none_imei_always_new(self, db: SQLiteDatabase) -> None:
        first = db.get_or_create_id(
            imei=None,
            model="Generic Phone",
            ram_rom="",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        second = db.get_or_create_id(
            imei=None,
            model="Generic Phone",
            ram_rom="",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        assert second != first


# ---------------------------------------------------------------------------
# update_metadata
# ---------------------------------------------------------------------------


class TestUpdateMetadata:
    """Metadata updates should only accept known fields."""

    def test_update_status(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        db.update_metadata(item_id, status="SOLD")
        meta = db.get_metadata(item_id)
        assert meta["status"] == "SOLD"

    def test_update_multiple_fields(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        db.update_metadata(
            item_id,
            status="SOLD",
            buyer="John Doe",
            buyer_contact="555-1234",
        )
        meta = db.get_metadata(item_id)
        assert meta["status"] == "SOLD"
        assert meta["buyer"] == "John Doe"
        assert meta["buyer_contact"] == "555-1234"

    def test_invalid_field_raises(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        with pytest.raises(ValueError, match="Invalid metadata fields"):
            db.update_metadata(item_id, nonexistent_field="bad")

    def test_empty_update_is_noop(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        db.update_metadata(item_id)  # should not raise


# ---------------------------------------------------------------------------
# get_item
# ---------------------------------------------------------------------------


class TestGetItem:
    """get_item returns combined item + metadata, or None."""

    def test_returns_combined_dict(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        db.update_metadata(item_id, status="IN")

        item = db.get_item(item_id)
        assert item is not None
        assert item["model"] == "Samsung A54"
        assert item["ram_rom"] == "8/128"
        assert item["status"] == "IN"

    def test_returns_none_for_missing_id(self, db: SQLiteDatabase) -> None:
        assert db.get_item(99999) is None


# ---------------------------------------------------------------------------
# resolve_conflict
# ---------------------------------------------------------------------------


class TestResolveConflict:
    """resolve_conflict hides duplicates and records history."""

    def test_hides_duplicate_items(self, db: SQLiteDatabase) -> None:
        # Create two items with the same real IMEI (insert first, then bypass dedup
        # by using text IMEI to force a second row, then manually verify).
        id_keep = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="SupplierA",
            source_file="test.xlsx",
        )
        # Second real IMEI returns the same ID — use text IMEI to force a new row
        id_hide = db.get_or_create_id(
            imei="duplicate-entry-1",
            model="Samsung A54 (dup)",
            ram_rom="8/128",
            supplier="SupplierB",
            source_file="test.xlsx",
        )

        db.resolve_conflict(
            keep_id=id_keep,
            hide_ids=[id_hide],
            reason="Duplicate entry from different source",
        )

        hidden_meta = db.get_metadata(id_hide)
        assert hidden_meta["is_hidden"] == 1
        assert hidden_meta["merged_into"] == id_keep

    def test_empty_hide_list_is_noop(self, db: SQLiteDatabase) -> None:
        item_id = db.get_or_create_id(
            imei="860123456789012",
            model="Samsung A54",
            ram_rom="8/128",
            supplier="TestSupplier",
            source_file="test.xlsx",
        )
        db.resolve_conflict(keep_id=item_id, hide_ids=[])  # should not raise
