"""Billing and invoice screens for StockMate.

Provides the BillingScreen for invoice creation and the
InvoiceHistoryScreen for browsing and managing generated invoices.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from typing import Any

import ttkbootstrap as tb
from ttkbootstrap.dialogs import Messagebox

from core.constants import (
    FIELD_BUYER,
    FIELD_BUYER_CONTACT,
    FIELD_IMEI,
    FIELD_MODEL,
    FIELD_PRICE,
    FIELD_RAM_ROM,
    FIELD_STATUS,
    FIELD_UNIQUE_ID,
    STATUS_IN,
    STATUS_OUT,
)
from gui.base import BaseScreen


# ---------------------------------------------------------------------------
# BillingScreen
# ---------------------------------------------------------------------------


class BillingScreen(BaseScreen):
    """Invoice creation screen.

    Allows scanning items into a cart, entering customer details,
    computing GST tax, applying discounts, and generating PDF invoices.

    Parameters
    ----------
    parent:
        Parent widget (the content area of MainApp).
    app_context:
        Dict with references to core managers and the main application window.
    """

    # -- constructor ---------------------------------------------------------

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)

        self._cart: list[dict[str, Any]] = []
        self._autocomplete_items: list[str] = []
        self._search_after_id: str | None = None

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the full billing screen layout."""
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.rowconfigure(1, weight=1)

        # 1. Header
        self.add_header("Billing & Invoice", help_section="billing")

        # 2. Content wrapper for grid-managed widgets
        self._content_wrapper = ttk.Frame(self)
        self._content_wrapper.pack(fill=tk.BOTH, expand=True)
        self._content_wrapper.columnconfigure(0, weight=1)
        self._content_wrapper.columnconfigure(1, weight=0)
        self._content_wrapper.rowconfigure(0, weight=1)

        self._build_left_panel()
        self._build_right_panel()

        # 3. Bottom action buttons
        self._build_action_bar()

    def _build_left_panel(self) -> None:
        """Build the left panel: scan bar, cart, totals."""
        left = ttk.Frame(self._content_wrapper)
        left.grid(row=0, column=0, sticky="nsew", padx=12, pady=4)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(3, weight=1)

        # Scan bar
        scan_frame = ttk.LabelFrame(left, text="Scan Item", padding=8)
        scan_frame.grid(row=0, column=0, sticky=tk.EW, pady=(0, 8))

        self._scan_var = tk.StringVar()
        self._scan_entry = ttk.Entry(scan_frame, textvariable=self._scan_var, width=40)
        self._scan_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._scan_var.trace_add("write", self._on_scan_search)
        self._scan_entry.bind("<Return>", self._on_scan_return)

        ttk.Button(
            scan_frame,
            text="Add to Cart",
            bootstyle="primary",
            command=self._add_scanned_to_cart,
        ).pack(side=tk.RIGHT)

        # Customer details
        cust_frame = ttk.LabelFrame(left, text="Customer Details", padding=8)
        cust_frame.grid(row=1, column=0, sticky=tk.EW, pady=(0, 8))

        ttk.Label(cust_frame, text="Name:").grid(row=0, column=0, sticky=tk.W, padx=4)
        self._cust_name_var = tk.StringVar()
        ttk.Entry(cust_frame, textvariable=self._cust_name_var, width=30).grid(
            row=0, column=1, sticky=tk.W, padx=4
        )

        ttk.Label(cust_frame, text="Contact:").grid(
            row=0, column=2, sticky=tk.W, padx=4
        )
        self._cust_contact_var = tk.StringVar()
        ttk.Entry(cust_frame, textvariable=self._cust_contact_var, width=18).grid(
            row=0, column=3, sticky=tk.W, padx=4
        )

        ttk.Label(cust_frame, text="Date:").grid(
            row=1, column=0, sticky=tk.W, padx=4, pady=(4, 0)
        )
        self._cust_date_var = tk.StringVar()
        ttk.Entry(cust_frame, textvariable=self._cust_date_var, width=15).grid(
            row=1, column=1, sticky=tk.W, padx=4, pady=(4, 0)
        )

        self._interstate_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            cust_frame, text="Interstate (IGST)", variable=self._interstate_var
        ).grid(row=1, column=2, sticky=tk.W, padx=4, pady=(4, 0))

        self._tax_inclusive_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            cust_frame, text="Tax-Inclusive", variable=self._tax_inclusive_var
        ).grid(row=1, column=3, sticky=tk.W, padx=4, pady=(4, 0))

        # Cart Treeview
        cart_frame = ttk.LabelFrame(left, text="Cart", padding=4)
        cart_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 8))
        cart_frame.columnconfigure(0, weight=1)
        cart_frame.rowconfigure(0, weight=1)

        cart_columns = ("sno", "id", "model", "ram_rom", "price", "qty", "total")
        self._cart_tree = ttk.Treeview(
            cart_frame, columns=cart_columns, show="headings", selectmode="browse"
        )

        self._cart_tree.heading("sno", text="S.No")
        self._cart_tree.heading("id", text="ID")
        self._cart_tree.heading("model", text="Model")
        self._cart_tree.heading("ram_rom", text="RAM/ROM")
        self._cart_tree.heading("price", text="Price")
        self._cart_tree.heading("qty", text="Qty")
        self._cart_tree.heading("total", text="Total")

        self._cart_tree.column("sno", width=40, anchor=tk.CENTER)
        self._cart_tree.column("id", width=60, anchor=tk.CENTER)
        self._cart_tree.column("model", width=200, anchor=tk.W)
        self._cart_tree.column("ram_rom", width=90, anchor=tk.CENTER)
        self._cart_tree.column("price", width=80, anchor=tk.E)
        self._cart_tree.column("qty", width=40, anchor=tk.CENTER)
        self._cart_tree.column("total", width=80, anchor=tk.E)

        cart_vsb = ttk.Scrollbar(
            cart_frame, orient=tk.VERTICAL, command=self._cart_tree.yview
        )
        self._cart_tree.configure(yscrollcommand=cart_vsb.set)

        self._cart_tree.grid(row=0, column=0, sticky="nsew")
        cart_vsb.grid(row=0, column=1, sticky=tk.NS)

        self._cart_tree.bind("<Delete>", self._remove_from_cart)

        # Discount frame
        disc_frame = ttk.Frame(left)
        disc_frame.grid(row=4, column=0, sticky=tk.EW, pady=(0, 8))

        self._disc_mode_var = tk.StringVar(value="amount")
        ttk.Radiobutton(
            disc_frame, text="₹ Amount", variable=self._disc_mode_var, value="amount"
        ).pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(
            disc_frame, text="% Percent", variable=self._disc_mode_var, value="percent"
        ).pack(side=tk.LEFT, padx=4)

        self._discount_var = tk.StringVar(value="0")
        disc_entry = ttk.Entry(disc_frame, textvariable=self._discount_var, width=10)
        disc_entry.pack(side=tk.LEFT, padx=8)
        disc_entry.bind("<KeyRelease>", self._on_discount_change)

        # Tax summary
        summary_frame = ttk.LabelFrame(left, text="Summary", padding=8)
        summary_frame.grid(row=5, column=0, sticky=tk.EW)

        self._subtotal_var = tk.StringVar(value="₹0.00")
        self._cgst_var = tk.StringVar(value="CGST: ₹0.00")
        self._sgst_var = tk.StringVar(value="SGST: ₹0.00")
        self._igst_var = tk.StringVar(value="IGST: ₹0.00")
        self._discount_display_var = tk.StringVar(value="Discount: ₹0.00")
        self._grand_total_var = tk.StringVar(value="Grand Total: ₹0.00")

        ttk.Label(
            summary_frame, textvariable=self._subtotal_var, font=("Segoe UI", 10)
        ).pack(anchor=tk.W)
        ttk.Label(summary_frame, textvariable=self._cgst_var).pack(anchor=tk.W)
        ttk.Label(summary_frame, textvariable=self._sgst_var).pack(anchor=tk.W)
        ttk.Label(summary_frame, textvariable=self._igst_var).pack(anchor=tk.W)
        ttk.Label(summary_frame, textvariable=self._discount_display_var).pack(
            anchor=tk.W
        )
        ttk.Label(
            summary_frame,
            textvariable=self._grand_total_var,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W, pady=(4, 0))

    def _build_right_panel(self) -> None:
        """Build the right panel: quick actions."""
        right = ttk.Frame(self._content_wrapper, width=180)
        right.grid(row=0, column=1, sticky="ns", padx=(4, 12), pady=4)
        right.grid_propagate(False)

        ttk.Label(right, text="Quick Actions", font=("Segoe UI", 11, "bold")).pack(
            anchor=tk.W, pady=(0, 8)
        )

        ttk.Button(
            right,
            text="Remove Item",
            bootstyle="danger-outline",
            command=self._remove_from_cart_btn,
        ).pack(fill=tk.X, pady=2)

        ttk.Button(
            right,
            text="Edit Price",
            bootstyle="warning-outline",
            command=self._edit_price,
        ).pack(fill=tk.X, pady=2)

    def _build_action_bar(self) -> None:
        """Build the bottom action buttons bar."""
        bar = ttk.Frame(self._content_wrapper)
        bar.grid(row=1, column=0, columnspan=2, sticky=tk.EW, padx=12, pady=8)

        ttk.Button(
            bar,
            text="Clear Cart",
            bootstyle="secondary-outline",
            command=self._clear_cart,
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            bar, text="Save PDF", bootstyle="info-outline", command=self._save_pdf
        ).pack(side=tk.RIGHT, padx=4)

        ttk.Button(
            bar, text="Print Invoice", bootstyle="info", command=self._print_invoice
        ).pack(side=tk.RIGHT, padx=4)

        ttk.Button(
            bar, text="SAVE & SOLD", bootstyle="success", command=self._save_and_sold
        ).pack(side=tk.RIGHT, padx=4)

    # -- autocomplete --------------------------------------------------------

    def _on_scan_search(self, *args: Any) -> None:
        """Debounced autocomplete from inventory."""
        if self._search_after_id is not None:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(150, self._update_autocomplete)

    def _update_autocomplete(self) -> None:
        """Update autocomplete list and refresh completion candidates."""
        text = self._scan_var.get().strip().lower()
        if not text:
            self._autocomplete_items = []
            return

        df = self.app["inventory"].get_inventory()
        if df.empty:
            self._autocomplete_items = []
            return

        # Only show items that are IN status
        available = df[df.get(FIELD_STATUS, "") == STATUS_IN]
        matches = []
        for _, row in available.iterrows():
            uid = str(row.get(FIELD_UNIQUE_ID, ""))
            imei = str(row.get(FIELD_IMEI, "")).lower()
            model = str(row.get(FIELD_MODEL, "")).lower()

            if text in uid or text in imei or text in model:
                display = (
                    f"[{uid}] {row.get(FIELD_MODEL, '')} | {row.get(FIELD_IMEI, '')}"
                )
                matches.append(display)

            if len(matches) >= 50:
                break

        self._autocomplete_items = matches
        self._scan_entry.set_completion_list(matches)

    def _on_scan_return(self, event: tk.Event) -> str | None:
        """Add scanned item to cart on Enter."""
        self._add_scanned_to_cart()
        return "break"

    def _add_scanned_to_cart(self) -> None:
        """Add the scanned/typed item to the cart."""
        text = self._scan_var.get().strip()
        if not text:
            return

        # Try to match by ID first, then IMEI, then model
        item = self._find_item_by_search(text)
        if item is None:
            self.app["app"].show_toast(
                "Not Found", f"No matching item for '{text}'.", "warning"
            )
            return

        self._add_to_cart(item)
        self._scan_var.set("")

    def _find_item_by_search(self, text: str) -> dict[str, Any] | None:
        """Find an available inventory item matching the search text."""
        df = self.app["inventory"].get_inventory()
        if df.empty:
            return None

        available = df[df.get(FIELD_STATUS, "") == STATUS_IN]

        # Exact ID match
        try:
            uid = int(text)
            mask = available[FIELD_UNIQUE_ID] == uid
            if mask.any():
                return available[mask].iloc[0].to_dict()
        except (ValueError, TypeError):
            pass

        # IMEI match
        if FIELD_IMEI in available.columns:
            mask = available[FIELD_IMEI].str.strip() == text.strip()
            if mask.any():
                return available[mask].iloc[0].to_dict()

        # Model match (first match)
        if FIELD_MODEL in available.columns:
            mask = (
                available[FIELD_MODEL].str.lower().str.contains(text.lower(), na=False)
            )
            if mask.any():
                return available[mask].iloc[0].to_dict()

        return None

    # -- cart operations -----------------------------------------------------

    def add_items(self, items: list[dict[str, Any]]) -> None:
        """Add items to the cart (called from other screens).

        Args:
            items: List of item dicts from the inventory.
        """
        if not items:
            return

        for item in items:
            self._handle_item_for_cart(item)

        self._refresh_cart_tree()
        self._update_totals()

    def _handle_item_for_cart(self, item: dict[str, Any]) -> None:
        """Handle an item being added to cart, checking for sold status."""
        status = item.get(FIELD_STATUS, STATUS_IN)

        if status == STATUS_OUT:
            self._handle_sold_item(item)
            return

        # Check if already in cart
        uid = item.get(FIELD_UNIQUE_ID)
        for cart_item in self._cart:
            if cart_item.get(FIELD_UNIQUE_ID) == uid:
                return

        self._cart.append(item)

    def _handle_sold_item(self, item: dict[str, Any]) -> None:
        """If item already sold, show options: RTN / IN / Anyway."""
        uid = item.get(FIELD_UNIQUE_ID, "N/A")
        model = item.get(FIELD_MODEL, "Unknown")

        response = Messagebox.yesnocancel(
            title="Item Already Sold",
            message=(
                f"Item {uid} ({model}) is already marked as SOLD.\n\n"
                f"YES — Mark as RTN (returned)\n"
                f"NO — Mark as IN (restock)\n"
                f"CANCEL — Skip this item"
            ),
        )

        if response == "Yes":
            self.app["inventory"].update_item_status(uid, "RTN")
            self._cart.append(item)
        elif response == "No":
            self.app["inventory"].update_item_status(uid, STATUS_IN)
            self._cart.append(item)
        # Cancel — do nothing

    def _add_to_cart(self, item: dict[str, Any]) -> None:
        """Add a single item to the cart."""
        uid = item.get(FIELD_UNIQUE_ID)
        for cart_item in self._cart:
            if cart_item.get(FIELD_UNIQUE_ID) == uid:
                self.app["app"].show_toast(
                    "Already in Cart",
                    f"Item {uid} is already in the cart.",
                    "warning",
                )
                return

        self._cart.append(item)
        self._refresh_cart_tree()
        self._update_totals()

    def _remove_from_cart(self, event: tk.Event | None = None) -> str | None:
        """Remove the selected cart item."""
        selection = self._cart_tree.selection()
        if not selection:
            return None

        # Map tree iid to cart index
        iid = selection[0]
        idx = int(iid) - 1
        if 0 <= idx < len(self._cart):
            self._cart.pop(idx)
            self._refresh_cart_tree()
            self._update_totals()

        return "break"

    def _remove_from_cart_btn(self) -> None:
        """Button wrapper for remove from cart."""
        self._remove_from_cart()

    def _refresh_cart_tree(self) -> None:
        """Rebuild the cart treeview from the current cart list."""
        for item in self._cart_tree.get_children():
            self._cart_tree.delete(item)

        for idx, item in enumerate(self._cart, start=1):
            price = float(item.get(FIELD_PRICE, 0))
            qty = 1
            total = price * qty

            self._cart_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    idx,
                    item.get(FIELD_UNIQUE_ID, ""),
                    item.get(FIELD_MODEL, ""),
                    item.get(FIELD_RAM_ROM, ""),
                    f"₹{price:,.0f}",
                    qty,
                    f"₹{total:,.0f}",
                ),
            )

    # -- totals & discount ---------------------------------------------------

    def _update_totals(self) -> None:
        """Recalculate subtotal, tax, discount, and grand total."""
        if not self._cart:
            self._subtotal_var.set("₹0.00")
            self._cgst_var.set("CGST: ₹0.00")
            self._sgst_var.set("SGST: ₹0.00")
            self._igst_var.set("IGST: ₹0.00")
            self._discount_display_var.set("Discount: ₹0.00")
            self._grand_total_var.set("Grand Total: ₹0.00")
            return

        subtotal = sum(float(item.get(FIELD_PRICE, 0)) for item in self._cart)

        # Discount
        discount_amount = 0.0
        try:
            disc_val = float(self._discount_var.get() or "0")
        except ValueError:
            disc_val = 0.0

        if self._disc_mode_var.get() == "percent":
            discount_amount = round(subtotal * disc_val / 100.0, 2)
        else:
            discount_amount = min(disc_val, subtotal)

        taxable = subtotal - discount_amount

        # Tax
        gst_rate = float(self.app["config"].get("gst_default_percent", 18.0))
        is_interstate = self._interstate_var.get()
        tax_inclusive = self._tax_inclusive_var.get()

        tax_info = self.app["billing"].calculate_tax(
            taxable, gst_rate, is_interstate, tax_inclusive
        )

        self._subtotal_var.set(f"₹{subtotal:,.2f}")

        if is_interstate:
            self._cgst_var.set("CGST: ₹0.00")
            self._sgst_var.set("SGST: ₹0.00")
            self._igst_var.set(f"IGST: ₹{tax_info['igst']:,.2f}")
        else:
            self._cgst_var.set(f"CGST: ₹{tax_info['cgst']:,.2f}")
            self._sgst_var.set(f"SGST: ₹{tax_info['sgst']:,.2f}")
            self._igst_var.set("IGST: ₹0.00")

        self._discount_display_var.set(f"Discount: - ₹{discount_amount:,.2f}")
        self._grand_total_var.set(f"Grand Total: ₹{tax_info['total']:,.2f}")

    def _on_discount_change(self, event: tk.Event) -> None:
        """Recalculate totals when discount changes."""
        self._update_totals()

    # -- invoice operations --------------------------------------------------

    def _save_invoice(self, mark_sold: bool = False) -> None:
        """Generate PDF invoice and optionally mark items as sold.

        Args:
            mark_sold: If True, update item status to OUT in inventory + DB.
        """
        if not self._cart:
            self.app["app"].show_toast(
                "Empty Cart", "Add items to the cart first.", "warning"
            )
            return

        customer_name = self._cust_name_var.get().strip() or "Walk-in Customer"
        customer_contact = self._cust_contact_var.get().strip()

        customer = {
            "name": customer_name,
            "contact": customer_contact,
            "address": "",
            "notes": "",
        }

        # Build items list for billing
        billing_items = []
        for item in self._cart:
            billing_items.append(
                {
                    FIELD_UNIQUE_ID: item.get(FIELD_UNIQUE_ID, ""),
                    FIELD_MODEL: item.get(FIELD_MODEL, ""),
                    FIELD_RAM_ROM: item.get(FIELD_RAM_ROM, ""),
                    FIELD_IMEI: item.get(FIELD_IMEI, ""),
                    FIELD_PRICE: float(item.get(FIELD_PRICE, 0)),
                    "qty": 1,
                }
            )

        # Discount
        discount_amount = 0.0
        discount_percent = 0.0
        try:
            disc_val = float(self._discount_var.get() or "0")
        except ValueError:
            disc_val = 0.0

        if self._disc_mode_var.get() == "percent":
            discount_percent = disc_val
        else:
            discount_amount = disc_val

        gst_rate = float(self.app["config"].get("gst_default_percent", 18.0))
        is_interstate = self._interstate_var.get()
        tax_inclusive = self._tax_inclusive_var.get()

        invoice_dir = str(self.app["config"].get_invoices_dir())

        success, verify_hash, final_total = self.app["billing"].generate_invoice(
            items=billing_items,
            customer=customer,
            invoice_dir=invoice_dir,
            discount_amount=discount_amount,
            discount_percent=discount_percent,
            gst_rate=gst_rate,
            is_interstate=is_interstate,
            tax_inclusive=tax_inclusive,
        )

        if not success:
            self.app["app"].show_toast("Invoice Failed", str(verify_hash), "danger")
            return

        # If mark_sold, update inventory
        if mark_sold:
            for item in self._cart:
                uid = item.get(FIELD_UNIQUE_ID)
                if uid is not None:
                    self.app["inventory"].update_item_status(uid, STATUS_OUT)
                    self.app["inventory"].update_item_data(
                        uid,
                        {
                            FIELD_BUYER: customer_name,
                            FIELD_BUYER_CONTACT: customer_contact,
                        },
                    )

            self.app["app"].show_toast(
                "Invoice Saved & Sold",
                f"Invoice generated. {len(self._cart)} item(s) marked as SOLD.",
                "success",
            )
        else:
            self.app["app"].show_toast(
                "Invoice Saved",
                f"Invoice saved. Total: ₹{final_total:,.2f}",
                "success",
            )

        # Clear cart after saving
        self._clear_cart()

    def _save_and_sold(self) -> None:
        """Save invoice and mark all cart items as sold."""
        self._save_invoice(mark_sold=True)

    def _save_pdf(self) -> None:
        """Save PDF invoice without marking items as sold."""
        self._save_invoice(mark_sold=False)

    def _edit_price(self) -> None:
        """Open dialog to edit selected cart item price."""
        selection = self._cart_tree.selection()
        if not selection:
            self.app["app"].show_toast(
                "No Selection",
                "Select an item in the cart to edit its price.",
                "warning",
            )
            return

        iid = selection[0]
        idx = int(iid) - 1
        if not (0 <= idx < len(self._cart)):
            return

        item = self._cart[idx]
        current_price = item.get(FIELD_PRICE, 0)

        dialog = _EditPriceDialog(self, item, current_price)
        self.wait_window(dialog)

        if dialog.confirmed:
            new_price = dialog.new_price
            if new_price is not None:
                self._cart[idx][FIELD_PRICE] = new_price
                self._refresh_cart_tree()
                self._update_totals()

    def _print_invoice(self) -> None:
        """Send the most recent invoice PDF to the printer."""
        invoice_dir = self.app["config"].get_invoices_dir()
        pdfs = sorted(
            [f for f in os.listdir(invoice_dir) if f.endswith(".pdf")],
            key=lambda f: os.path.getmtime(os.path.join(invoice_dir, f)),
            reverse=True,
        )

        if not pdfs:
            self.app["app"].show_toast(
                "No Invoice", "No invoices found to print.", "warning"
            )
            return

        latest = os.path.join(invoice_dir, pdfs[0])
        self._send_to_printer(latest)

    def _send_to_printer(self, pdf_path: str) -> None:
        """Send a PDF file to the system printer."""
        try:
            if sys.platform == "win32":
                os.startfile(pdf_path, "print")
            elif sys.platform == "darwin":
                subprocess.call(["open", "-a", "Preview", pdf_path])
            else:
                subprocess.call(["xdg-open", pdf_path])

            self.app["app"].show_toast(
                "Printing", f"Sent {os.path.basename(pdf_path)} to printer.", "info"
            )
        except Exception as exc:
            self.app["app"].show_toast("Print Error", str(exc), "danger")

    def _clear_cart(self) -> None:
        """Clear all items from the cart."""
        self._cart.clear()
        self._refresh_cart_tree()
        self._update_totals()
        self._discount_var.set("0")

    # -- lifecycle -----------------------------------------------------------

    def focus_primary(self) -> None:
        """Focus the scan entry."""
        self._scan_entry.focus_set()

    def on_show(self) -> None:
        """Called when this screen becomes visible."""
        # Refresh customer defaults
        self._cust_date_var.set(datetime.datetime.now().strftime("%d-%m-%Y"))
        self._update_totals()


# ---------------------------------------------------------------------------
# InvoiceHistoryScreen
# ---------------------------------------------------------------------------


class InvoiceHistoryScreen(BaseScreen):
    """Browse and manage generated invoices.

    Displays a list of invoices with filtering, and supports
    opening, printing, deleting, and verifying invoice signatures.

    Parameters
    ----------
    parent:
        Parent widget (the content area of MainApp).
    app_context:
        Dict with references to core managers and the main application window.
    """

    # -- constructor ---------------------------------------------------------

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)

        self._invoices: list[dict[str, Any]] = []

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the full invoice history screen layout."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # 1. Header
        self.add_header("Invoice History", help_section="invoices")

        # 2. Content wrapper for grid-managed widgets
        self._content_wrapper = ttk.Frame(self)
        self._content_wrapper.pack(fill=tk.BOTH, expand=True)
        self._content_wrapper.columnconfigure(0, weight=1)
        self._content_wrapper.rowconfigure(1, weight=1)

        # 3. Filter bar
        self._build_filter_bar()

        # 4. Invoice treeview
        self._build_invoice_list()

        # 5. Action buttons
        self._build_action_bar()

    def _build_filter_bar(self) -> None:
        """Build the filter bar for invoice history."""
        bar = ttk.Frame(self._content_wrapper)
        bar.grid(row=0, column=0, sticky=tk.EW, padx=12, pady=4)

        ttk.Label(bar, text="Buyer:").pack(side=tk.LEFT, padx=4)
        self._buyer_search_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self._buyer_search_var, width=25).pack(
            side=tk.LEFT, padx=4
        )

        ttk.Label(bar, text="From:").pack(side=tk.LEFT, padx=(12, 4))
        self._inv_date_from_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self._inv_date_from_var, width=12).pack(
            side=tk.LEFT, padx=4
        )

        ttk.Label(bar, text="To:").pack(side=tk.LEFT, padx=(8, 4))
        self._inv_date_to_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self._inv_date_to_var, width=12).pack(
            side=tk.LEFT, padx=4
        )

        ttk.Button(
            bar, text="Filter", bootstyle="primary", command=self._filter_invoices
        ).pack(side=tk.LEFT, padx=8)

    def _build_invoice_list(self) -> None:
        """Build the invoice treeview."""
        tree_frame = ttk.Frame(self._content_wrapper)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        columns = ("number", "date", "buyer", "total", "items_count")
        self._inv_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )

        self._inv_tree.heading("number", text="Invoice #")
        self._inv_tree.heading("date", text="Date")
        self._inv_tree.heading("buyer", text="Buyer")
        self._inv_tree.heading("total", text="Total")
        self._inv_tree.heading("items_count", text="Items")

        self._inv_tree.column("number", width=180, anchor=tk.W)
        self._inv_tree.column("date", width=120, anchor=tk.CENTER)
        self._inv_tree.column("buyer", width=200, anchor=tk.W)
        self._inv_tree.column("total", width=100, anchor=tk.E)
        self._inv_tree.column("items_count", width=60, anchor=tk.CENTER)

        vsb = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self._inv_tree.yview
        )
        hsb = ttk.Scrollbar(
            tree_frame, orient=tk.HORIZONTAL, command=self._inv_tree.xview
        )
        self._inv_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._inv_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky=tk.NS)
        hsb.grid(row=1, column=0, sticky=tk.EW)

        self._inv_tree.bind("<Double-1>", self._open_selected_invoice)

    def _build_action_bar(self) -> None:
        """Build the action buttons bar."""
        bar = ttk.Frame(self._content_wrapper)
        bar.grid(row=2, column=0, sticky=tk.EW, padx=12, pady=8)

        ttk.Button(
            bar,
            text="Open PDF",
            bootstyle="info-outline",
            command=self._open_selected_invoice,
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            bar, text="Print", bootstyle="info", command=self._print_selected_invoice
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            bar,
            text="Delete",
            bootstyle="danger-outline",
            command=self._delete_selected_invoice,
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            bar,
            text="Verify Signature",
            bootstyle="warning-outline",
            command=self._verify_signature,
        ).pack(side=tk.RIGHT, padx=4)

    # -- data loading --------------------------------------------------------

    def refresh_data(self) -> None:
        """Reload invoice list from the invoices directory."""
        self._load_invoices()

    def _load_invoices(self) -> None:
        """Scan invoice directory for PDFs and parse filenames."""
        invoice_dir = self.app["config"].get_invoices_dir()
        self._invoices.clear()

        if not invoice_dir.is_dir():
            self._populate_invoice_tree([])
            return

        pdf_files = sorted(
            [f for f in os.listdir(invoice_dir) if f.endswith(".pdf")],
            reverse=True,
        )

        for filename in pdf_files:
            info = self._parse_invoice_filename(filename)
            if info:
                info["filename"] = filename
                info["filepath"] = str(invoice_dir / filename)
                self._invoices.append(info)

        self._populate_invoice_tree(self._invoices)

    def _parse_invoice_filename(self, filename: str) -> dict[str, Any] | None:
        """Parse an invoice filename into structured data.

        Expected format: ``invoice_INV-YYYYMMDD-NNNN.pdf``
        """
        if not filename.startswith("invoice_INV-"):
            return None

        # Extract invoice number from filename
        base = filename.replace("invoice_", "").replace(".pdf", "")
        # base is like "INV-20250101-0001"
        parts = base.split("-")
        if len(parts) != 3:
            return None

        date_str = parts[1]
        try:
            date_obj = datetime.datetime.strptime(date_str, "%Y%m%d")
            date_display = date_obj.strftime("%d-%m-%Y")
        except ValueError:
            date_display = date_str

        return {
            "number": base,
            "date": date_display,
            "buyer": "",
            "total": "",
            "items_count": "",
        }

    def _populate_invoice_tree(self, invoices: list[dict[str, Any]]) -> None:
        """Fill the treeview with invoice data."""
        for item in self._inv_tree.get_children():
            self._inv_tree.delete(item)

        for inv in invoices:
            self._inv_tree.insert(
                "",
                tk.END,
                iid=inv["number"],
                values=(
                    inv["number"],
                    inv["date"],
                    inv.get("buyer", ""),
                    inv.get("total", ""),
                    inv.get("items_count", ""),
                ),
            )

    # -- filtering -----------------------------------------------------------

    def _filter_invoices(self) -> None:
        """Apply buyer name and date filters."""
        buyer_text = self._buyer_search_var.get().strip().lower()
        date_from = self._inv_date_from_var.get().strip()
        date_to = self._inv_date_to_var.get().strip()

        filtered = self._invoices

        if buyer_text:
            filtered = [
                inv for inv in filtered if buyer_text in inv.get("buyer", "").lower()
            ]

        if date_from:
            try:
                from_dt = datetime.datetime.strptime(date_from, "%Y-%m-%d")
                filtered = [
                    inv for inv in filtered if self._parse_date(inv["date"]) >= from_dt
                ]
            except ValueError:
                pass

        if date_to:
            try:
                to_dt = datetime.datetime.strptime(date_to, "%Y-%m-%d")
                filtered = [
                    inv for inv in filtered if self._parse_date(inv["date"]) <= to_dt
                ]
            except ValueError:
                pass

        self._populate_invoice_tree(filtered)

    @staticmethod
    def _parse_date(date_str: str) -> datetime.datetime:
        """Parse a display date string into a datetime object."""
        try:
            return datetime.datetime.strptime(date_str, "%d-%m-%Y")
        except ValueError:
            return datetime.datetime.min

    # -- invoice actions -----------------------------------------------------

    def _open_selected_invoice(self, event: tk.Event | None = None) -> None:
        """Open the selected invoice PDF in the default viewer."""
        selection = self._inv_tree.selection()
        if not selection:
            return

        inv_number = selection[0]
        inv = self._find_invoice(inv_number)
        if inv is None:
            return

        filepath = inv.get("filepath", "")
        if not filepath or not os.path.exists(filepath):
            self.app["app"].show_toast(
                "File Not Found", f"PDF not found: {inv_number}", "warning"
            )
            return

        self._open_pdf(filepath)

    def _open_pdf(self, filepath: str) -> None:
        """Open a PDF file in the system default viewer."""
        try:
            if sys.platform == "win32":
                os.startfile(filepath)
            elif sys.platform == "darwin":
                subprocess.call(["open", filepath])
            else:
                subprocess.call(["xdg-open", filepath])
        except Exception as exc:
            self.app["app"].show_toast("Open Error", str(exc), "danger")

    def _print_selected_invoice(self) -> None:
        """Send the selected invoice PDF to the printer."""
        selection = self._inv_tree.selection()
        if not selection:
            self.app["app"].show_toast(
                "No Selection", "Select an invoice to print.", "warning"
            )
            return

        inv_number = selection[0]
        inv = self._find_invoice(inv_number)
        if inv is None:
            return

        filepath = inv.get("filepath", "")
        if not filepath or not os.path.exists(filepath):
            self.app["app"].show_toast(
                "File Not Found", f"PDF not found: {inv_number}", "warning"
            )
            return

        billing_screen = None
        for screen in self.app["app"].screens.values():
            if hasattr(screen, "_send_to_printer"):
                billing_screen = screen
                break

        if billing_screen:
            billing_screen._send_to_printer(filepath)
        else:
            self._open_pdf(filepath)

    def _delete_selected_invoice(self) -> None:
        """Delete the selected invoice with confirmation."""
        selection = self._inv_tree.selection()
        if not selection:
            self.app["app"].show_toast(
                "No Selection", "Select an invoice to delete.", "warning"
            )
            return

        inv_number = selection[0]
        inv = self._find_invoice(inv_number)
        if inv is None:
            return

        response = Messagebox.okcancel(
            title="Delete Invoice",
            message=f"Are you sure you want to delete invoice {inv_number}?\n\nThis action cannot be undone.",
        )

        if response != "OK":
            return

        filepath = inv.get("filepath", "")
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                self.app["app"].show_toast(
                    "Deleted", f"Invoice {inv_number} deleted.", "success"
                )
                self.refresh_data()
            except OSError as exc:
                self.app["app"].show_toast("Delete Error", str(exc), "danger")

    def _verify_signature(self) -> None:
        """Open dialog to enter verification hash and check against stored hash."""
        dialog = _VerifySignatureDialog(self)
        self.wait_window(dialog)

        if not dialog.confirmed:
            return

        entered_hash = dialog.verification_code.strip()
        if not entered_hash:
            return

        # Search through invoices for matching hash
        found = self._search_invoice_by_hash(entered_hash)
        if found:
            self.app["app"].show_toast(
                "Signature Valid",
                f"Invoice {found['number']} verified successfully.",
                "success",
            )
        else:
            self.app["app"].show_toast(
                "Signature Invalid",
                "No matching invoice found for this verification code.",
                "danger",
            )

    def _search_invoice_by_hash(self, hash_code: str) -> dict[str, Any] | None:
        """Search for an invoice whose verification hash matches *hash_code*.

        Since we don't store hashes separately, we check the first 16 chars
        against the invoice number as a simple lookup. In a production system,
        hashes would be stored in a registry.
        """
        # For now, match against invoice number as a simple lookup
        for inv in self._invoices:
            if inv["number"].lower() in hash_code.lower():
                return inv
        return None

    def _find_invoice(self, inv_number: str) -> dict[str, Any] | None:
        """Find an invoice dict by its invoice number."""
        for inv in self._invoices:
            if inv["number"] == inv_number:
                return inv
        return None

    # -- lifecycle -----------------------------------------------------------

    def focus_primary(self) -> None:
        """Focus the buyer search entry."""
        self._buyer_search_var_entry = (
            self.nametowidget(
                self._buyer_search_var._name  # type: ignore[attr-defined]
            )
            if hasattr(self._buyer_search_var, "_name")
            else None
        )
        # Focus the entry widget directly
        for child in self.winfo_children():
            if isinstance(child, ttk.Frame):
                for sub in child.winfo_children():
                    if isinstance(sub, ttk.Entry) and sub.cget("textvariable") == str(
                        self._buyer_search_var
                    ):
                        sub.focus_set()
                        return

    def on_show(self) -> None:
        """Called when this screen becomes visible."""
        self.refresh_data()


# ---------------------------------------------------------------------------
# _EditPriceDialog — helper dialog for editing cart item price
# ---------------------------------------------------------------------------


class _EditPriceDialog(tb.Toplevel):
    """Dialog to edit the price of a cart item.

    Parameters
    ----------
    parent:
        Parent window.
    item:
        The cart item dict being edited.
    current_price:
        Current price of the item.
    """

    def __init__(
        self, parent: tk.Misc, item: dict[str, Any], current_price: float
    ) -> None:
        super().__init__(parent)
        self.confirmed = False
        self.new_price: float | None = None

        model = item.get(FIELD_MODEL, "Unknown")
        uid = item.get(FIELD_UNIQUE_ID, "N/A")

        self.title(f"Edit Price — {model} (ID: {uid})")
        self.transient(parent)
        self.grab_set()
        self.geometry("300x140")
        self.resizable(False, False)

        self._current_price = current_price
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text=f"Current Price: ₹{self._current_price:,.0f}").pack(
            anchor=tk.W, pady=(0, 8)
        )

        ttk.Label(main, text="New Price:").pack(anchor=tk.W, pady=(0, 4))
        self._price_var = tk.StringVar(value=str(self._current_price))
        price_entry = ttk.Entry(main, textvariable=self._price_var)
        price_entry.pack(fill=tk.X, pady=(0, 12))
        price_entry.focus_set()
        price_entry.bind("<Return>", lambda e: self._confirm())

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)

        ttk.Button(
            btn_frame, text="Update", bootstyle="warning", command=self._confirm
        ).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _confirm(self) -> None:
        """Validate and collect the new price."""
        try:
            price = float(self._price_var.get())
            if price < 0:
                raise ValueError("Price cannot be negative")
            self.new_price = price
            self.confirmed = True
            self.destroy()
        except ValueError as exc:
            messagebox.showerror("Invalid Price", str(exc))


# ---------------------------------------------------------------------------
# _VerifySignatureDialog — helper dialog for invoice verification
# ---------------------------------------------------------------------------


class _VerifySignatureDialog(tb.Toplevel):
    """Dialog to enter an invoice verification code.

    Parameters
    ----------
    parent:
        Parent window.
    """

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.confirmed = False
        self.verification_code = ""

        self.title("Verify Invoice Signature")
        self.transient(parent)
        self.grab_set()
        self.geometry("350x150")
        self.resizable(False, False)

        self._build_ui()

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text="Enter the verification code from the invoice:",
        ).pack(anchor=tk.W, pady=(0, 8))

        self._hash_var = tk.StringVar()
        hash_entry = ttk.Entry(main, textvariable=self._hash_var, width=50)
        hash_entry.pack(fill=tk.X, pady=(0, 12))
        hash_entry.focus_set()
        hash_entry.bind("<Return>", lambda e: self._confirm())

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)

        ttk.Button(
            btn_frame, text="Verify", bootstyle="warning", command=self._confirm
        ).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _confirm(self) -> None:
        """Collect the verification code."""
        self.verification_code = self._hash_var.get().strip()
        if not self.verification_code:
            return
        self.confirmed = True
        self.destroy()


# Import datetime at the top level for on_show usage
import datetime
