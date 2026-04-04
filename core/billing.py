"""
GST Billing Manager for StockMate.

Generates professional PDF invoices with tax computation,
discount handling, and SHA-256 verification hashes.
"""

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Invoice number generation
# ---------------------------------------------------------------------------

_INVOICE_NUM_RE = re.compile(r"^INV-\d{8}-\d+$")


def _generate_invoice_number(invoice_dir: str) -> str:
    """Generate the next sequential invoice number for *invoice_dir*.

    Format: ``INV-{YYYYMMDD}-{counter}``
    Counter is derived from existing invoice files in the directory.
    """
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"invoice_INV-{today}-"

    counter = 1
    try:
        dir_path = Path(invoice_dir)
        if dir_path.is_dir():
            existing = [
                f.name
                for f in dir_path.iterdir()
                if f.name.startswith(prefix) and f.name.endswith(".pdf")
            ]
            counter = len(existing) + 1
    except OSError:
        pass

    return f"INV-{today}-{counter:04d}"


def _validate_invoice_number(number: str) -> bool:
    """Return True when *number* matches the expected invoice pattern."""
    return bool(_INVOICE_NUM_RE.match(number))


# ---------------------------------------------------------------------------
# Tax computation — pure, predictable, no side effects
# ---------------------------------------------------------------------------


def _compute_tax_components(
    subtotal: float,
    gst_rate: float,
    is_interstate: bool,
    tax_inclusive: bool,
) -> dict[str, float]:
    """Compute tax breakdown from *subtotal*.

    Returns dict with keys: subtotal, gst_rate, cgst, sgst, igst,
    tax_amount, total.
    """
    if tax_inclusive:
        tax_amount = subtotal * gst_rate / (100.0 + gst_rate)
        base = subtotal - tax_amount
    else:
        tax_amount = subtotal * gst_rate / 100.0
        base = subtotal

    if is_interstate:
        igst = round(tax_amount, 2)
        cgst = 0.0
        sgst = 0.0
    else:
        igst = 0.0
        cgst = round(tax_amount / 2.0, 2)
        sgst = round(tax_amount - cgst, 2)

    total = round(subtotal + tax_amount, 2) if not tax_inclusive else round(subtotal, 2)

    return {
        "subtotal": round(base, 2) if tax_inclusive else round(subtotal, 2),
        "gst_rate": gst_rate,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "tax_amount": round(tax_amount, 2),
        "total": total,
    }


def _compute_verification_hash(
    invoice_number: str,
    customer_name: str,
    total: float,
    timestamp: str,
) -> str:
    """Return SHA-256 hash for invoice integrity verification."""
    raw = f"{invoice_number}{customer_name}{total}{timestamp}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# PDF building helpers
# ---------------------------------------------------------------------------


def _build_store_header(store_info: dict[str, str]) -> list[Any]:
    """Build the store header section for the invoice."""
    elements: list[Any] = []
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    normal_style = styles["Normal"]

    elements.append(Paragraph(store_info.get("store_name", "Mobile Shop"), title_style))

    lines = []
    if store_info.get("store_address"):
        lines.append(store_info["store_address"])
    if store_info.get("store_gstin"):
        lines.append(f"GSTIN: {store_info['store_gstin']}")
    if store_info.get("store_contact"):
        lines.append(f"Phone: {store_info['store_contact']}")

    for line in lines:
        elements.append(Paragraph(line, normal_style))

    return elements


def _build_customer_section(customer: dict[str, str]) -> list[Any]:
    """Build the customer details section."""
    elements: list[Any] = []
    styles = getSampleStyleSheet()
    heading_style = styles["Heading2"]
    normal_style = styles["Normal"]

    elements.append(Paragraph("Bill To", heading_style))
    elements.append(Paragraph(customer.get("name", "Walk-in Customer"), normal_style))

    if customer.get("contact"):
        elements.append(Paragraph(f"Contact: {customer['contact']}", normal_style))
    if customer.get("address"):
        elements.append(Paragraph(customer["address"], normal_style))
    if customer.get("notes"):
        elements.append(Paragraph(f"Notes: {customer['notes']}", normal_style))

    return elements


def _build_items_table(items: list[dict[str, Any]]) -> Table:
    """Build the itemized table from *items*."""
    headers = ["S.No", "Model", "RAM/ROM", "IMEI", "Unit Price", "Qty", "Total"]

    rows = [headers]
    running_total = 0.0

    for idx, item in enumerate(items, start=1):
        unit_price = float(item.get("price", 0))
        qty = int(item.get("qty", 1))
        line_total = unit_price * qty
        running_total += line_total

        rows.append(
            [
                str(idx),
                str(item.get("model", "")),
                str(item.get("ram_rom", "")),
                str(item.get("imei", "")),
                f"\u20b9{unit_price:,.2f}",
                str(qty),
                f"\u20b9{line_total:,.2f}",
            ]
        )

    col_widths = [30, 120, 70, 100, 80, 40, 80]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f8f9fa")],
                ),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    return table


def _build_tax_breakdown(tax_info: dict[str, float]) -> Table:
    """Build the tax summary table."""
    rows = []

    if tax_info["cgst"] > 0:
        rows.append(
            [
                "CGST",
                f"{tax_info['gst_rate'] / 2:.1f}%",
                f"\u20b9{tax_info['cgst']:,.2f}",
            ]
        )
    if tax_info["sgst"] > 0:
        rows.append(
            [
                "SGST",
                f"{tax_info['gst_rate'] / 2:.1f}%",
                f"\u20b9{tax_info['sgst']:,.2f}",
            ]
        )
    if tax_info["igst"] > 0:
        rows.append(
            ["IGST", f"{tax_info['gst_rate']:.1f}%", f"\u20b9{tax_info['igst']:,.2f}"]
        )

    rows.append(["Tax Amount", "", f"\u20b9{tax_info['tax_amount']:,.2f}"])

    col_widths = [150, 100, 100]
    table = Table(rows, colWidths=col_widths)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ecf0f1")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ]
        )
    )

    return table


def _build_grand_total(total: float) -> Table:
    """Build the grand total line."""
    row = [["Grand Total", f"\u20b9{total:,.2f}"]]
    table = Table(row, colWidths=[250, 100])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 11),
                ("ALIGN", (1, 0), (-1, 0), "RIGHT"),
                ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ]
        )
    )
    return table


def _build_discount_line(
    discount_amount: float, discount_percent: float
) -> Table | None:
    """Build a discount line if applicable."""
    if discount_amount <= 0 and discount_percent <= 0:
        return None

    label = "Discount"
    if discount_percent > 0:
        label += f" ({discount_percent:.1f}%)"

    row = [[label, f"- \u20b9{discount_amount:,.2f}"]]
    table = Table(row, colWidths=[250, 100])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#c0392b")),
                ("ALIGN", (1, 0), (-1, 0), "RIGHT"),
            ]
        )
    )
    return table


def _build_footer(terms: str, verify_hash: str, timestamp: str) -> list[Any]:
    """Build the terms and verification footer."""
    elements: list[Any] = []
    styles = getSampleStyleSheet()
    small_style = styles["Normal"]
    small_style.fontSize = 7

    elements.append(Spacer(1, 12 * mm))
    elements.append(Paragraph("Terms & Conditions", styles["Heading3"]))
    elements.append(Paragraph(terms, small_style))
    elements.append(Spacer(1, 6 * mm))
    elements.append(
        Paragraph(
            f"Verification: <font face='Courier'>{verify_hash[:16]}...</font>",
            small_style,
        )
    )
    elements.append(Paragraph(f"Generated: {timestamp}", small_style))

    return elements


# ---------------------------------------------------------------------------
# BillingManager
# ---------------------------------------------------------------------------


class BillingManager:
    """Handle GST tax computation and PDF invoice generation.

    Takes a *config_manager* for store details and an *activity_logger*
    for audit trail recording.
    """

    def __init__(self, config_manager: Any, activity_logger: Any) -> None:
        self._config = config_manager
        self._logger = activity_logger

    # -- tax computation -----------------------------------------------------

    def calculate_tax(
        self,
        subtotal: float,
        gst_rate: float = 18.0,
        is_interstate: bool = False,
        tax_inclusive: bool = False,
    ) -> dict[str, float]:
        """Compute GST tax breakdown for *subtotal*.

        Returns dict with keys: subtotal, gst_rate, cgst, sgst, igst,
        tax_amount, total.
        """
        if subtotal < 0:
            raise ValueError(f"Subtotal cannot be negative: {subtotal}")
        if gst_rate < 0:
            raise ValueError(f"GST rate cannot be negative: {gst_rate}")

        return _compute_tax_components(subtotal, gst_rate, is_interstate, tax_inclusive)

    # -- invoice generation --------------------------------------------------

    def generate_invoice(
        self,
        items: list[dict[str, Any]],
        customer: dict[str, str],
        invoice_dir: str,
        *,
        discount_amount: float = 0,
        discount_percent: float = 0,
        gst_rate: float = 18.0,
        is_interstate: bool = False,
        tax_inclusive: bool = False,
        invoice_number: str | None = None,
    ) -> tuple[bool, str, float]:
        """Generate a professional PDF invoice.

        Returns ``(success, verify_hash, final_total)``.
        """
        # Guard: must have items
        if not items:
            return False, "", 0.0

        # Resolve invoice number
        if invoice_number is None:
            invoice_number = _generate_invoice_number(invoice_dir)
        elif not _validate_invoice_number(invoice_number):
            return False, "", 0.0

        # Ensure invoice directory exists
        try:
            Path(invoice_dir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"Cannot create invoice directory: {exc}", 0.0

        # Compute line subtotal
        line_subtotal = sum(
            float(item.get("price", 0)) * int(item.get("qty", 1)) for item in items
        )

        # Apply discount
        if discount_percent > 0:
            discount_amount = round(line_subtotal * discount_percent / 100.0, 2)

        taxable_subtotal = line_subtotal - discount_amount

        # Compute tax
        tax_info = self.calculate_tax(
            taxable_subtotal, gst_rate, is_interstate, tax_inclusive
        )
        final_total = tax_info["total"]

        # Build verification hash
        timestamp = datetime.now().isoformat()
        customer_name = customer.get("name", "Walk-in Customer")
        verify_hash = _compute_verification_hash(
            invoice_number, customer_name, final_total, timestamp
        )

        # Build PDF
        pdf_path = os.path.join(invoice_dir, f"invoice_{invoice_number}.pdf")

        try:
            doc = SimpleDocTemplate(
                pdf_path,
                pagesize=A4,
                topMargin=15 * mm,
                bottomMargin=15 * mm,
                leftMargin=15 * mm,
                rightMargin=15 * mm,
            )

            story: list[Any] = []

            # Store header
            store_info = {
                "store_name": self._config.get("store_name", "Mobile Shop"),
                "store_address": self._config.get("store_address", ""),
                "store_gstin": self._config.get("store_gstin", ""),
                "store_contact": self._config.get("store_contact", ""),
            }
            story.extend(_build_store_header(store_info))
            story.append(Spacer(1, 6 * mm))

            # Invoice meta
            styles = getSampleStyleSheet()
            meta_rows = [
                ["Invoice Number:", invoice_number],
                ["Date:", datetime.now().strftime("%d-%m-%Y %H:%M")],
            ]
            meta_table = Table(meta_rows, colWidths=[120, 200])
            meta_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(meta_table)
            story.append(Spacer(1, 6 * mm))

            # Customer section
            story.extend(_build_customer_section(customer))
            story.append(Spacer(1, 6 * mm))

            # Items table
            story.append(_build_items_table(items))
            story.append(Spacer(1, 6 * mm))

            # Discount line
            if discount_amount > 0:
                discount_table = _build_discount_line(discount_amount, discount_percent)
                if discount_table is not None:
                    story.append(discount_table)
                    story.append(Spacer(1, 3 * mm))

            # Tax breakdown
            story.append(_build_tax_breakdown(tax_info))
            story.append(Spacer(1, 3 * mm))

            # Grand total
            story.append(_build_grand_total(final_total))

            # Footer
            terms = self._config.get(
                "invoice_terms", "Goods once sold will not be taken back."
            )
            story.extend(_build_footer(terms, verify_hash, timestamp))

            doc.build(story)

            self._logger.info(
                f"Invoice generated: {invoice_number} | Total: \u20b9{final_total:,.2f}"
            )

            return True, verify_hash, final_total

        except Exception as exc:
            return False, f"PDF generation failed: {exc}", 0.0
