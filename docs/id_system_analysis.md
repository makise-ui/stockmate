# ID Assignment System — Full Analysis & Data Loss Risk Assessment

## 1. How ID Assignment Works

### 1.1 Two-Source-of-Truth Architecture

StockMate uses a **dual-storage model**:

| Source | What it stores | Authority |
|--------|---------------|-----------|
| **Excel/CSV files** | Raw inventory rows (IMEI, model, color, price, etc.) | Source of truth for *what exists* |
| **SQLite (`stockmate.db`)** | `items` table (canonical identity), `metadata` table (status, buyer, notes, sold_date, hidden flags), `history` table (audit log) | Source of truth for *state changes* |

The `unique_id` in the in-memory DataFrame is the **SQLite row ID** — it is the single link between the Excel row and its persistent metadata.

### 1.2 ID Assignment Pipeline

```
Excel row loaded
    │
    ▼
_normalize_data() — builds canonical DataFrame
    │
    ▼
For each row, call db.get_or_create_id(imei, model, ram_rom, supplier, source_file, ...)
    │
    ▼
Classify IMEI → "real" (14-16 digits) | "text" (non-empty, non-placeholder) | "placeholder"
    │
    ├── REAL IMEI ──────────────────────────────────────────┐
    │   Lookup: SELECT id FROM items WHERE imei=? AND imei_type='real'  │
    │   ├── Found → return existing ID (dedup)              │
    │   └── Not found → INSERT new row → return new ID      │
    │                                                        │
    ├── TEXT IMEI ───────────────────────────────────────────┤
    │   Lookup: SELECT id FROM items WHERE imei=? AND model=? AND ram_rom=? AND supplier=? AND imei_type=? │
    │   ├── Found → return existing ID (composite dedup)    │
    │   └── Not found → INSERT new row → return new ID      │
    │                                                        │
    └── PLACEHOLDER IMEI ────────────────────────────────────┤
        Same composite-key dedup as TEXT                    │
        (imei, model, ram_rom, supplier, imei_type)          │
    │                                                        │
    ▼                                                        ▼
Row gets unique_id = returned ID                    INSERT happens under _lock
    │                                                        │
    ▼                                                        ▼
After all IDs assigned:                              Metadata row created:
Bulk-lookup all items from DB                        INSERT INTO metadata (id) VALUES (new_id)
Apply DB overrides to DataFrame                      (status=IN, buyer='', notes='', etc.)
(status, notes, buyer, color, grade, condition, price_override, sold_date)
```

### 1.3 The `get_or_create_id()` Method — Detailed Flow

**Location:** `core/database.py` → `SQLiteDatabase.get_or_create_id()`

```python
def get_or_create_id(self, imei, model, ram_rom, supplier, source_file,
                     *, color="", price_original=0.0, grade="", condition=""):
    # Step 1: Classify IMEI
    imei_type = _classify_imei(imei)  # → "real" | "text" | "placeholder"
    clean_imei = imei.strip() if isinstance(imei, str) else None

    # Step 2a: Real IMEI — dedup by IMEI only
    if imei_type == "real":
        existing = SELECT id FROM items WHERE imei=? AND imei_type='real'
        if found: return existing["id"]

    # Step 2b: Text/Placeholder — dedup by composite key
    if imei_type in ("text", "placeholder"):
        existing = SELECT id FROM items WHERE imei=? AND model=? AND ram_rom=? AND supplier=? AND imei_type=?
        if found: return existing["id"]

    # Step 3: Insert (under lock)
    with self._lock:
        INSERT INTO items (imei, imei_type, model, ram_rom, supplier, color, price_original, grade, condition, source_file)
        VALUES (...)
        new_id = cursor.lastrowid
        INSERT INTO metadata (id) VALUES (new_id)
        commit()
    return new_id
```

**Critical observation:** The **lookup** (step 2a/2b) is **NOT under the lock**. Only the **insert** (step 3) is. This creates a TOCTOU (time-of-check-time-of-use) race condition.

### 1.4 Metadata Override Pipeline

After IDs are assigned, `_normalize_data()` does a second pass:

```python
# Bulk-lookup all item metadata from DB
unique_ids = canonical[FIELD_UNIQUE_ID].unique().tolist()
items_data = self.db.get_items_by_ids([int(uid) for uid in unique_ids])
item_map = {item["id"]: item for item in items_data}

# Apply overrides row-by-row
def apply_overrides(row):
    uid = int(row[FIELD_UNIQUE_ID])
    item_data = item_map.get(uid)
    if item_data:
        # Override: status, notes, buyer, buyer_contact, color, grade, condition
        # Override: price_original → recalculates selling price with markup
        # Restore: date_added, date_sold
```

**Key point:** The DB metadata **overrides** what's in the Excel file for certain fields. This is how status changes persist even when the Excel file is edited externally.

### 1.5 Conflict Detection & Resolution

**Detection** (`_detect_conflicts`): After loading all files, finds real IMEIs (14-16 digits, purely numeric) that appear in multiple rows across files.

**Resolution** (`resolve_conflict`):
1. User picks a "keep" item
2. Other items get `is_hidden=1` and `merged_into=keep_id` in metadata
3. On next reload, hidden items are **filtered out** of the DataFrame
4. If a status update targets a hidden ID, it's **redirected** to `merged_into`

### 1.6 The Hidden Item Mechanism

Hidden items are:
- Still in the `items` table
- Still in the `metadata` table with `is_hidden=1`
- **Filtered out** during `reload_all()`: `full_df = full_df[~full_df[FIELD_UNIQUE_ID].isin(hidden_ids)]`
- **Not deleted** — data persists in DB

### 1.7 Background Excel Write Queue

When status/data is updated in the app:
1. DB metadata is updated **immediately** (synchronous, under lock)
2. In-memory DataFrame is updated **immediately**
3. Excel write is **queued** to a background daemon thread
4. Background worker: loads Excel → finds row by IMEI match → writes cell → saves to `.tmp` → `os.replace()`
5. Creates a **backup** of the Excel file before writing (`~/Documents/StockMate/backups/`)
6. Max 3 retries with 1.5s delay if file is locked by Excel

---

## 2. All Possible Data Loss Scenarios

### 🔴 CRITICAL — High Probability / High Impact

#### DL-1: TOCTOU Race in `get_or_create_id()` — Duplicate IDs for Real IMEIs

**What happens:**
- Two concurrent `reload_all()` calls (e.g., manual refresh + file watcher trigger) both process the same Excel file
- Thread A checks: "IMEI 123456789012345 exists?" → No
- Thread B checks: "IMEI 123456789012345 exists?" → No (A hasn't inserted yet)
- Thread A inserts → gets ID=42
- Thread B inserts → gets ID=43 (duplicate item for same real IMEI)
- Both IDs now exist in DB, same real IMEI → conflict created

**Impact:** Creates phantom duplicate items. The conflict resolution system catches this, but until resolved, the user sees two identical items. Metadata (status, buyer, notes) is split across two IDs.

**Root cause:** Lookup is outside the lock; only insert is locked.

#### DL-2: Excel Write Failure — Status Change Lost in Excel

**What happens:**
- User changes item status from IN → OUT in the app
- SQLite metadata is updated immediately ✅
- In-memory DataFrame is updated immediately ✅
- Excel write is queued to background thread
- Background write fails because:
  - File is open in Excel (retries 3×, then gives up)
  - File was moved/deleted between update and write
  - Row not found in Excel (IMEI was modified externally, breaking the match)
  - Backup creation fails (disk full, permission error) → write **aborted** for safety
- **SQLite has the new status, Excel has the old status**

**On next app restart:**
- Excel is reloaded → row still shows old status
- BUT: DB metadata override kicks in → DB status wins ✅
- **However**: If the user edits the Excel file externally (changes status back to IN) and the app reloads:
  - The `_normalize_data()` reads `norm_status()` from Excel → "IN"
  - Then applies DB override → "OUT" (from DB)
  - So DB wins... **but only if the item still exists in Excel**

**Worst case:** If the row is **deleted from Excel**, the item disappears from the DataFrame entirely. The DB still has the item (metadata + items row), but it won't appear in the UI because `reload_all()` only loads from Excel files.

**Impact:** **PERMANENT DATA LOSS** — if a row is deleted from Excel, all its DB metadata (status=OUT/sold, buyer info, notes, sold_date) becomes **orphaned**. The item won't appear in any view.

#### DL-3: Row Deletion from Excel → Orphaned DB Metadata

**What happens:**
- Item ID=42 is SOLD (status=OUT, buyer="John", notes="Warranty till Dec")
- User or another process deletes the row from Excel
- App reloads → row not in Excel → not in DataFrame → not visible in UI
- DB still has: items row (ID=42), metadata (status=OUT, buyer="John"), history entries
- **No mechanism exists to detect or recover orphaned DB entries**

**Impact:** **PERMANENT, SILENT DATA LOSS**. The sold record, buyer info, and all history are trapped in the DB with no way to surface them through the UI.

#### DL-4: IMEI Change in Excel → New ID, Orphaned Old Metadata

**What happens:**
- Item ID=42 has IMEI "123456789012345", status=OUT, buyer="John"
- User edits Excel externally, changes IMEI to "987654321098765"
- App reloads:
  - `clean_imei("987654321098765")` → "987654321098765"
  - `get_or_create_id(imei="987654321098765", ...)` → NOT found → **new ID=99**
  - Old ID=42 still exists in DB with all its metadata
  - New ID=99 is created with fresh metadata (status=IN, no buyer)
- **Result:** Two DB entries. Old one (ID=42) is orphaned. New one (ID=99) has lost all history.

**Impact:** **PERMANENT DATA LOSS** — the sold status, buyer info, and notes from ID=42 are lost. The item reappears as "IN" stock, potentially getting sold again (double-selling).

#### DL-5: File Watcher Triggers During Manual Edit → Lost Unsaved Changes

**What happens:**
- User is editing an Excel file (has it open in Excel)
- User saves the file → watchdog fires
- `reload_all()` is called → reads the file
- But Excel may write a partial file, then finish. If `reload_all()` reads during the write, it may get corrupted data
- The debouncing (1s) helps but isn't foolproof for large files

**Impact:** Temporary data corruption on reload. Usually self-corrects on next save, but can cause confusing UI state.

### 🟡 MODERATE — Medium Probability / Medium Impact

#### DL-6: Composite Key Dedup Insufficient — Different Items Get Same ID

**What happens:**
- Text IMEI item: `imei="NOT ON"`, `model="iPhone 14"`, `ram_rom="6/128"`, `supplier="ABC"`
- Same item re-enters inventory from a different supplier file: `imei="NOT ON"`, `model="iPhone 14"`, `ram_rom="6/128"`, `supplier="XYZ"`
- Composite key includes `supplier`, so these get **different IDs** ✅ (correct behavior)
- **But** if the same supplier sends the same text-IMEI item again, it gets the **same ID** and the old metadata (e.g., old status=OUT) is applied to the new physical item

**Impact:** A new physical item appears as "SOLD" because it shares a composite key with a previously sold item.

#### DL-7: Supplier Name Change → New IDs for All Items

**What happens:**
- Supplier file mapped with `supplier="ABC Corp"`
- User changes supplier name in config to `"ABC Corporation"`
- All items from this file now have a **different composite key** (supplier changed)
- `get_or_create_id()` → NOT found for any item → **all get new IDs**
- Old IDs still exist in DB with all metadata
- New IDs are created with fresh metadata

**Impact:** **MASSIVE DATA LOSS** — every item from this file loses its status, buyer, notes, and history. All items revert to "IN" status.

#### DL-8: Model/RAM_ROM Change in Excel → New ID

**What happens:**
- Item ID=42: `imei="NOT ON"`, `model="iPhone 13"`, `ram_rom="6/128"`, `supplier="ABC"`
- User corrects model in Excel: `model="iPhone 13 Pro"`
- `get_or_create_id()` → composite key mismatch → **new ID=99**
- Old ID=42 orphaned in DB

**Impact:** Same as DL-4 — orphaned metadata, item resets to "IN".

#### DL-9: Database Corruption or Deletion

**What happens:**
- `stockmate.db` is corrupted (disk failure, interrupted write)
- Or user accidentally deletes `~/Documents/StockMate/stockmate.db`
- App creates fresh DB on next launch
- All metadata (status, buyer, notes, sold dates, history, conflict resolutions) is **gone**
- Excel files are intact, so items reload as "IN" with no history

**Mitigation:** `backup_db()` exists but is only called manually (if at all — need to check if it's wired to any UI button).

**Impact:** **CATASTROPHIC** — complete loss of all state changes. Every item resets to factory state.

#### DL-10: Background Worker Dies — Queue Items Lost

**What happens:**
- The background worker thread is a **daemon** thread
- If the app crashes or is force-killed, any pending items in `write_queue` are lost
- The queue is in-memory (Python `queue.Queue`), not persisted
- DB metadata is already updated (happens before queuing), so this is less critical
- But the **Excel file** won't reflect the changes

**Impact:** Excel file out of sync with DB. On reload, Excel values are overridden by DB (usually correct), but external users of the Excel file see stale data.

#### DL-11: Atomic Excel Write — `.tmp` File Left Behind

**What happens:**
- `_write_excel_generic()` saves to `.tmp` file, then `os.replace()`
- If the save to `.tmp` succeeds but `os.replace()` fails (permission error, file locked), the `.tmp` file is left behind
- Next write attempt may see the `.tmp` file and fail
- The original Excel file is unchanged, but the write is silently dropped

**Impact:** Excel write silently fails. DB and Excel diverge.

#### DL-12: Conflict Resolution Loses Items

**What happens:**
- Two items share a real IMEI (IDs 42 and 99)
- User resolves: keep ID=42, hide ID=99
- ID=99 gets `is_hidden=1, merged_into=42`
- ID=99 is filtered out of the DataFrame on next reload
- If ID=99 had unique metadata (e.g., different color, grade, notes from a different source file), that data is **effectively hidden** from the user
- The merged-into redirect only applies to status updates, not to data viewing

**Impact:** User may not realize they're losing data from the hidden item. No merge of complementary fields (e.g., if ID=42 has color="Black" and ID=99 has color="White", the kept item keeps "Black").

### 🟢 LOW — Low Probability / Low Impact

#### DL-13: Price Markup Recalculation on Every Reload

**What happens:**
- `price_markup_percent` is configured as 10%
- Every `reload_all()`, the original price from Excel is multiplied by 1.10
- If `price_override` is set in DB, it uses that as the base, then applies markup
- If the user manually edits the selling price in Excel (not the original price column), the next reload **recalculates** it from the original, wiping the manual edit

**Impact:** Manual price edits in Excel are lost on reload. Only DB `price_override` persists.

#### DL-14: Sheet Name Changes in Excel File

**What happens:**
- File mapped to sheet "Sheet1"
- User renames sheet to "Inventory" in Excel
- `pd.read_excel(file, sheet_name="Sheet1")` → raises exception
- Fallback tries `sheet_name=0` → loads first sheet (may be wrong sheet)
- Data loads but from wrong sheet

**Impact:** Wrong data loaded silently. User may not notice.

#### DL-15: Column Renamed in Excel → Column Missing in DataFrame

**What happens:**
- Excel column "IMEI" is mapped to canonical "imei"
- User renames column to "IMEI Number" in Excel
- Mapping lookup fails → `get_col("imei")` returns None
- IMEI column becomes empty strings
- Real IMEI items become placeholder IMEIs → **new IDs assigned** on next reload

**Impact:** Same as DL-4 — orphaned metadata, items reset.

#### DL-16: App Closed Before File Watcher Fires

**What happens:**
- User edits Excel file externally
- File watcher fires `reload_all()` 
- User closes app immediately
- `InventoryManager.shutdown()` drains the queue and joins the writer thread (10s timeout)
- If drain takes longer than 10s, pending writes are abandoned

**Impact:** Partial state. Usually minimal since DB writes are synchronous.

---

## 3. Proposed Solutions

### For DL-1: TOCTOU Race — Duplicate IDs

**Fix:** Use SQLite `INSERT OR IGNORE` with a UNIQUE constraint, then always SELECT after.

```python
# Add UNIQUE constraints to schema
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
    ...
    UNIQUE(imei, imei_type) -- for real IMEIs
    ...
);
"""

def get_or_create_id(self, ...):
    imei_type = _classify_imei(imei)
    clean_imei = imei.strip() if isinstance(imei, str) else None

    with self._lock:  # Lock the ENTIRE check-and-insert
        if imei_type == "real":
            existing = self._conn.execute(
                "SELECT id FROM items WHERE imei = ? AND imei_type = 'real'",
                (clean_imei,),
            ).fetchone()
            if existing is not None:
                return existing["id"]

        if imei_type in ("text", "placeholder"):
            existing = self._conn.execute(
                "SELECT id FROM items WHERE imei = ? AND model = ? AND ram_rom = ? AND supplier = ? AND imei_type = ?",
                (clean_imei, model, ram_rom, supplier, imei_type),
            ).fetchone()
            if existing is not None:
                return existing["id"]

        # Insert (still under lock)
        cursor = self._conn.execute("INSERT INTO items ...", (...))
        new_id = cursor.lastrowid
        self._conn.execute("INSERT INTO metadata (id) VALUES (?)", (new_id,))
        self._conn.commit()
        return new_id
```

**Trade-off:** Slight performance hit (lock held longer), but eliminates the race. The lock is only held during the DB operation, not during DataFrame processing.

### For DL-2, DL-3, DL-4, DL-8, DL-15: Row Deletion / IMEI Change / Column Change → Orphaned Metadata

**Fix A: DB as Primary Source, Excel as Secondary**

Add a reconciliation mechanism that detects items in the DB that are no longer in Excel:

```python
def reload_all(self):
    # After loading Excel data into full_df:
    excel_ids = set(full_df[FIELD_UNIQUE_ID].astype(int).unique())

    # Get all non-hidden DB items
    all_db_items = self.db.get_all_items(hidden=False)
    db_ids = {item["id"] for item in all_db_items}

    # Find orphaned DB items (in DB but not in Excel)
    orphaned_ids = db_ids - excel_ids
    if orphaned_ids:
        # Option 1: Keep them in the DataFrame by reconstructing rows from DB
        orphaned_rows = []
        for item in self.db.get_items_by_ids(list(orphaned_ids)):
            orphaned_rows.append({
                FIELD_UNIQUE_ID: item["id"],
                FIELD_IMEI: item.get("imei", ""),
                FIELD_MODEL: item.get("model", "Unknown"),
                # ... fill all columns from DB items table + metadata
            })
        # Append to DataFrame so orphaned items remain visible
        full_df = pd.concat([full_df, pd.DataFrame(orphaned_rows)], ignore_index=True)

        # Option 2: Flag them in the UI as "Excel row missing"
        # Option 3: Move them to an "Archived" section
```

**Fix B: Immutable Item Identity Key**

Instead of the composite key `(imei, model, ram_rom, supplier, imei_type)` changing, introduce a **stable external ID** that the user can set:

```python
# Add a "stock_id" or "barcode" column to Excel
# This becomes the primary dedup key, immune to model/supplier changes
# Falls back to IMEI if stock_id is absent
```

**Fix C: Soft-Delete Detection**

When reloading, compare current Excel row count with previous load. If rows dropped significantly, warn the user:

```python
def reload_all(self):
    previous_count = len(self.inventory_df) if not self.inventory_df.empty else 0
    # ... load Excel ...
    current_count = len(full_df)

    if previous_count > 0 and current_count < previous_count * 0.8:
        # Warn user: "20% of items disappeared from Excel. Continue?"
        pass
```

### For DL-7: Supplier Name Change → Mass New IDs

**Fix:** Decouple supplier name from the dedup key. Use a **supplier ID** in the mapping, not the display name:

```python
# In file_mappings.json:
{
    "file_path": "/path/to/inventory.xlsx",
    "supplier_id": "SUP_001",  # stable identifier
    "supplier_name": "ABC Corp",  # display only
    ...
}

# In get_or_create_id, use supplier_id for dedup, not supplier_name
```

Or simpler: don't include supplier in the composite key for text/placeholder IMEIs. Dedup by `(imei, model, ram_rom)` only. Supplier is metadata, not identity.

### For DL-5: File Watcher Reads Partial File

**Fix:** Increase debounce time to 3-5 seconds and add file stability check:

```python
def _schedule_callback(self):
    with self._lock:
        if self._timer is not None:
            self._timer.cancel()
        # Wait for file to stop changing (size stability check)
        self._timer = threading.Timer(self._debounce_seconds, self._callback)
        self._timer.daemon = True
        self._timer.start()

def _callback(self):
    # Before reloading, check if file is still being written
    for mapping in self._config.mappings.values():
        path = mapping.get("file_path", "")
        if os.path.exists(path):
            size1 = os.path.getsize(path)
            time.sleep(0.5)
            size2 = os.path.getsize(path)
            if size1 != size2:
                # File still changing, reschedule
                self._schedule_callback()
                return
    # File is stable, proceed with reload
    self._inventory.reload_all()
```

### For DL-9: Database Corruption

**Fix A: Automatic Backups**

Schedule periodic automatic backups:

```python
# In main app, on a timer (e.g., every hour):
def auto_backup_db(self):
    backup_dir = str(Path.home() / "Documents" / "StockMate" / "backups")
    self._db.backup_db(backup_dir)
```

**Fix B: WAL Checkpoint on Close**

Ensure WAL is checkpointed on shutdown:

```python
def close(self):
    if self._conn:
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._conn.commit()
        self._conn.close()
        self._conn = None
```

**Fix C: DB Integrity Check on Startup**

```python
def __init__(self, db_path=None):
    # ... existing init ...
    result = self._conn.execute("PRAGMA integrity_check").fetchone()
    if result[0] != "ok":
        # Restore from latest backup
        self._restore_from_backup()
```

### For DL-10: Background Queue Loss on Crash

**Fix:** Persist the queue to disk so it survives crashes:

```python
# On queue put, also write to a JSON file:
def _persist_queue(self):
    items = []
    while not self.write_queue.empty():
        items.append(self.write_queue.get_nowait())
    # Write to disk
    with open(QUEUE_FILE, "w") as f:
        json.dump(items, f)
    # Re-enqueue
    for item in items:
        self.write_queue.put(item)

# On startup, replay persisted queue:
def _replay_queue(self):
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE) as f:
            items = json.load(f)
        for item in items:
            self.write_queue.put(item)
        os.unlink(QUEUE_FILE)
```

### For DL-11: Orphaned .tmp Files

**Fix:** Clean up `.tmp` files on startup:

```python
def _cleanup_tmp_files(self):
    for mapping in self._config.mappings.values():
        path = mapping.get("file_path", "")
        tmp_path = f"{path}.tmp"
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
```

### For DL-12: Conflict Resolution Data Loss

**Fix:** Before hiding items, **merge complementary fields** from hidden items into the kept item:

```python
def resolve_conflict(self, keep_id, hide_ids, reason=""):
    # Before hiding, merge data from hidden items
    for hid in hide_ids:
        hidden_item = self.db.get_item(hid)
        kept_item = self.db.get_item(keep_id)

        # Merge fields that are non-empty in hidden but empty in kept
        merge_fields = ["color", "grade", "condition", "notes"]
        for field in merge_fields:
            if hidden_item.get(field) and not kept_item.get(field):
                self.db.update_metadata(keep_id, **{field: hidden_item[field]})

    # Then proceed with hiding
    with self._lock:
        # ... existing hide logic ...
```

### For DL-13: Price Markup Overwriting Manual Edits

**Fix:** Add a `price_manual_override` field to metadata. If set, use it instead of recalculating from original:

```python
# In apply_overrides:
if item_data.get("price_manual_override") is not None:
    row[FIELD_PRICE] = float(item_data["price_manual_override"])
    row[FIELD_PRICE_ORIGINAL] = float(item_data["price_manual_override"])
```

### For DL-14: Sheet Name Changes

**Fix:** If sheet by name not found, try to find a sheet with matching column headers:

```python
def _load_file_internal(self, file_path, mapping_data):
    # ... existing code ...
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
    except (ValueError, IndexError, KeyError):
        # Try all sheets, find one with matching headers
        xls = pd.ExcelFile(file_path)
        for sheet in xls.sheet_names:
            df = pd.read_excel(file_path, sheet_name=sheet)
            if set(mapping.values()).issubset(set(df.columns)):
                break  # Found matching sheet
        else:
            return None, "NO_SHEET_MATCH"
```

---

## 4. Summary of Risk by Category

| Risk | Severity | Probability | Fix Priority |
|------|----------|-------------|-------------|
| DL-3: Row deleted from Excel → orphaned DB | **Critical** | High | **P0** |
| DL-4: IMEI changed in Excel → new ID, orphaned metadata | **Critical** | High | **P0** |
| DL-7: Supplier name change → mass new IDs | **Critical** | Medium | **P0** |
| DL-9: DB corruption → total metadata loss | **Critical** | Low | **P1** |
| DL-1: TOCTOU race → duplicate IDs | High | Medium | **P1** |
| DL-12: Conflict resolution loses data | High | Medium | **P1** |
| DL-2: Excel write failure → sync loss | High | High | **P1** |
| DL-5: File watcher reads partial file | Medium | Medium | **P2** |
| DL-6: Composite key dedup insufficient | Medium | Low | **P2** |
| DL-8: Model/RAM_ROM change → new ID | Medium | Medium | **P2** |
| DL-15: Column renamed → missing data | Medium | Medium | **P2** |
| DL-10: Queue lost on crash | Low | Low | **P3** |
| DL-11: Orphaned .tmp files | Low | Low | **P3** |
| DL-13: Price markup overwrites manual edits | Low | Medium | **P3** |
| DL-14: Sheet name changes | Low | Low | **P3** |
| DL-16: Close during watcher fire | Low | Low | **P3** |

## 5. Recommended Implementation Order

1. **P0 — Fix DL-3/DL-4/DL-8:** Add orphaned item recovery to `reload_all()`. DB items not found in Excel should be reconstructed and displayed with a "Missing from Excel" flag.
2. **P0 — Fix DL-7:** Remove `supplier` from the composite dedup key for text/placeholder IMEIs.
3. **P1 — Fix DL-1:** Move the lookup inside the lock in `get_or_create_id()`.
4. **P1 — Fix DL-9:** Add auto-backup on startup + integrity check.
5. **P1 — Fix DL-12:** Merge complementary fields before hiding items in conflict resolution.
6. **P2 — Fix DL-8/DL-15:** Add column mapping validation and warn on missing columns.
7. **P2 — Fix DL-5:** Add file stability check to the watcher.
8. **P3 — Remaining:** Queue persistence, .tmp cleanup, price override field.
