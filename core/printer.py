"""
Print Manager for StockMate.

Handles PDF printing, ZPL label printing, GDI image printing,
ESC/POS thermal printing, and batch PDF label export.
Gracefully degrades when Windows-specific libraries are unavailable.
"""

import os
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional Windows imports — graceful degradation
# ---------------------------------------------------------------------------

try:
    import win32con
    import win32print
    import win32ui
    from pywintypes import error as Win32Error

    _HAS_WIN32 = True
except ImportError:
    win32con = None  # type: ignore[assignment]
    win32print = None  # type: ignore[assignment]
    win32ui = None  # type: ignore[assignment]
    Win32Error = Exception  # type: ignore[misc,assignment]
    _HAS_WIN32 = False

# ---------------------------------------------------------------------------
# ZPL template variable substitution
# ---------------------------------------------------------------------------

_ZPL_VARS = {
    "ID",
    "MODEL",
    "PRICE",
    "RAM/ROM",
    "IMEI",
    "GRADE",
    "STORE_NAME",
}


def _substitute_zpl(template: str, item: dict[str, Any], store_name: str) -> str:
    """Replace ``${VAR}`` placeholders in *template* with item values."""
    replacements = {
        "${ID}": str(item.get("unique_id", item.get("id", ""))),
        "${MODEL}": str(item.get("model", "")),
        "${PRICE}": f"${item.get('price', 0):.2f}",
        "${RAM/ROM}": str(item.get("ram_rom", "")),
        "${IMEI}": str(item.get("imei", "")),
        "${GRADE}": str(item.get("grade", "")),
        "${STORE_NAME}": store_name,
    }

    result = template
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)

    return result


def _load_zpl_template(template_path: str | None) -> str | None:
    """Load a ZPL template file, returning ``None`` on failure."""
    if template_path is None:
        return None

    path = Path(template_path)
    if not path.is_file():
        return None

    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# PrinterManager
# ---------------------------------------------------------------------------


class PrinterManager:
    """Manage printing operations across multiple backends.

    Supports Windows GDI printing, raw ZPL label printers,
    ESC/POS thermal printers, and PDF batch export.
    """

    def __init__(self, config_manager: Any) -> None:
        self._config = config_manager

    # -- system printer discovery --------------------------------------------

    def get_system_printers(self) -> list[str]:
        """Return a list of available Windows printer names.

        Returns an empty list when ``win32print`` is unavailable.
        """
        if not _HAS_WIN32:
            return []

        try:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            printers = win32print.EnumPrinters(flags)
            return [p[2] for p in printers]
        except Exception:
            return []

    # -- PDF printing --------------------------------------------------------

    def print_pdf(self, pdf_path: str, printer_name: str | None = None) -> bool:
        """Send a PDF file to a Windows printer.

        If *printer_name* is provided, it is set as the default printer
        before printing.
        """
        path = Path(pdf_path)
        if not path.is_file():
            return False

        try:
            if printer_name and _HAS_WIN32:
                previous = win32print.GetDefaultPrinter()
                try:
                    win32print.SetDefaultPrinter(printer_name)
                    os.startfile(str(path), "print")
                    return True
                finally:
                    try:
                        win32print.SetDefaultPrinter(previous)
                    except Exception:
                        pass
            else:
                os.startfile(str(path), "print")
                return True

        except Exception:
            return False

    # -- raw ZPL printing ----------------------------------------------------

    def send_raw_zpl(self, zpl_data: str, printer_name: str | None = None) -> bool:
        """Send raw ZPL data to a printer via ``win32print``.

        Returns ``False`` when ``win32print`` is unavailable or the
        print job fails.
        """
        if not _HAS_WIN32:
            return False

        if not zpl_data:
            return False

        target = printer_name or win32print.GetDefaultPrinter()
        if not target:
            return False

        zpl_bytes = zpl_data.encode("utf-8")

        try:
            h_printer = win32print.OpenPrinter(target)
            job = win32print.StartDocPrinter(
                h_printer, 1, ("MobileShopLabel", None, "RAW")
            )
            win32print.StartPagePrinter(h_printer)
            win32print.WritePrinter(h_printer, zpl_bytes)
            win32print.EndPagePrinter(h_printer)
            win32print.EndDocPrinter(h_printer)
            win32print.ClosePrinter(h_printer)
            return True

        except Win32Error:
            return False
        except Exception:
            return False

    # -- ZPL label printing --------------------------------------------------

    def print_label_zpl(
        self,
        item: dict[str, Any],
        printer_name: str | None = None,
        template_path: str | None = None,
    ) -> bool:
        """Print a single label using a ZPL template.

        Loads the template from *template_path*, falling back to
        ``custom_template.zpl`` in the config directory.
        """
        # Try explicit path first
        template = _load_zpl_template(template_path)

        # Fall back to config directory template
        if template is None:
            config_dir = self._config.get_config_dir()
            fallback = config_dir / "custom_template.zpl"
            template = _load_zpl_template(str(fallback))

        # Guard: no template available
        if template is None:
            return False

        store_name = self._config.get("store_name", "Mobile Shop")
        zpl = _substitute_zpl(template, item, store_name)

        return self.send_raw_zpl(zpl, printer_name)

    # -- ZPL batch printing (2-up) -------------------------------------------

    def print_batch_zpl(
        self,
        items: list[dict[str, Any]],
        printer_name: str | None = None,
        template_path: str | None = None,
    ) -> bool:
        """Print labels in 2-up layout (pairs side by side).

        Each label is ~400 dots wide; combined width is 830 dots.
        """
        if not items:
            return False

        # Load template
        template = _load_zpl_template(template_path)
        if template is None:
            config_dir = self._config.get_config_dir()
            fallback = config_dir / "custom_template.zpl"
            template = _load_zpl_template(str(fallback))

        if template is None:
            return False

        store_name = self._config.get("store_name", "Mobile Shop")
        combined_zpl_parts: list[str] = []

        # Process items in pairs
        for i in range(0, len(items), 2):
            left_item = items[i]
            right_item = items[i + 1] if i + 1 < len(items) else None

            left_zpl = _substitute_zpl(template, left_item, store_name)

            # Shift right label by ~415 dots (half of 830)
            if right_item:
                right_zpl = _substitute_zpl(template, right_item, store_name)
                # Offset X coordinates for right label
                right_zpl = self._offset_zpl_x(right_zpl, 415)
                combined_zpl_parts.append(left_zpl + right_zpl)
            else:
                combined_zpl_parts.append(left_zpl)

        combined_zpl = (
            "^XA"
            + "".join(
                part.replace("^XA", "").replace("^XZ", "")
                for part in combined_zpl_parts
            )
            + "^XZ"
        )

        return self.send_raw_zpl(combined_zpl, printer_name)

    @staticmethod
    def _offset_zpl_x(zpl: str, offset: int) -> str:
        """Shift all ``^FOx,y`` field origin X coordinates by *offset*."""
        import re

        def shift(match):
            x = int(match.group(1)) + offset
            y = match.group(2)
            return f"^FO{x},{y}"

        return re.sub(r"\^FO(\d+),(\d+)", shift, zpl)

    # -- GDI image printing (Windows fallback) --------------------------------

    def print_label_windows(
        self,
        item: dict[str, Any],
        printer_name: str | None = None,
    ) -> bool:
        """Print a label image using Windows GDI.

        Generates a label preview via ``BarcodeGenerator``, saves it
        to a temporary PNG, and prints via ``win32print``/``win32ui``.
        """
        if not _HAS_WIN32:
            return False

        from .barcode_utils import BarcodeGenerator

        generator = BarcodeGenerator(self._config)

        try:
            label_img = generator.generate_label_preview(item)
        except Exception:
            return False

        # Save to temp PNG
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            label_img.save(tmp_path, "PNG")

            target = printer_name or win32print.GetDefaultPrinter()
            if not target:
                return False

            h_printer = win32print.OpenPrinter(target)
            printer_info = win32print.GetPrinter(h_printer, 2)
            devmode = printer_info["pDevMode"]

            dc = win32ui.CreateDC()
            dc.CreatePrinterDC(target)
            dc.StartDoc("MobileShopLabel")
            dc.StartPage()

            # Scale image to printable area
            img_w, img_h = label_img.size
            printable_w = devmode.PelsWidth
            printable_h = devmode.PelsHeight

            # Maintain aspect ratio
            scale = min(printable_w / img_w, printable_h / img_h)
            draw_w = int(img_w * scale)
            draw_h = int(img_h * scale)
            offset_x = (printable_w - draw_w) // 2
            offset_y = (printable_h - draw_h) // 2

            dc.SetMapMode(win32con.MM_TEXT)
            dib = win32ui.CreateDIBitmap(
                dc,
                label_img.tobytes(),
                win32con.CB_INIT,
                seed=None,
            )
            dc.BitBlt(
                (offset_x, offset_y),
                (draw_w, draw_h),
                dc,
                (0, 0),
                win32con.SRCCOPY,
            )

            dc.EndPage()
            dc.EndDoc()
            dc.DeleteDC()
            win32print.ClosePrinter(h_printer)

            return True

        except Exception:
            return False
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # -- ESC/POS thermal printing (stub) -------------------------------------

    def print_label_escpos(self, item: dict[str, Any], printer_uri: str) -> bool:
        """Print a label to an ESC/POS thermal printer.

        Requires the ``python-escpos`` package. Returns ``False``
        when the package is not installed.
        """
        try:
            from escpos.printer import NetworkPrinter, UsbPrinter
        except ImportError:
            return False

        from .barcode_utils import BarcodeGenerator

        generator = BarcodeGenerator(self._config)

        try:
            label_img = generator.generate_label_preview(item)
        except Exception:
            return False

        try:
            if printer_uri.startswith("usb:"):
                # Parse USB vendor/product IDs
                parts = printer_uri.replace("usb:", "").split(":")
                vid = int(parts[0], 16) if len(parts) > 0 else 0
                pid = int(parts[1], 16) if len(parts) > 1 else 0
                printer = UsbPrinter(vid, pid)
            else:
                # Network printer: host:port
                host, port = printer_uri.rsplit(":", 1)
                printer = NetworkPrinter(host=host, port=int(port))

            printer.image(label_img)
            printer.cut()
            return True

        except Exception:
            return False

    # -- PDF label export ----------------------------------------------------

    def export_labels_pdf(
        self,
        items: list[dict[str, Any]],
        output_path: str,
        template_path: str | None = None,
    ) -> bool:
        """Batch-export label images to a PDF file.

        Uses a 2-up layout (2 labels per row) on A4 pages.
        """
        if not items:
            return False

        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import Image, SimpleDocTemplate, Spacer, Table

        from .barcode_utils import BarcodeGenerator

        generator = BarcodeGenerator(self._config)

        # Generate label images
        label_images: list[str] = []
        for item in items:
            try:
                img = generator.generate_label_preview(item, width=400, height=200)
                fd, tmp = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                img.save(tmp, "PNG")
                label_images.append(tmp)
            except Exception:
                continue

        if not label_images:
            return False

        try:
            doc = SimpleDocTemplate(
                output_path,
                pagesize=A4,
                topMargin=10 * mm,
                bottomMargin=10 * mm,
                leftMargin=10 * mm,
                rightMargin=10 * mm,
            )

            # Build table with 2 columns
            page_width = A4[0] - 20 * mm
            label_width = page_width / 2

            rows: list[list[Any]] = []
            current_row: list[Any] = []

            for img_path in label_images:
                img_element = Image(
                    img_path,
                    width=label_width - 2 * mm,
                    height=label_width * 0.5 - 2 * mm,
                )
                current_row.append(img_element)

                if len(current_row) == 2:
                    rows.append(current_row)
                    current_row = []

            # Flush remaining
            if current_row:
                while len(current_row) < 2:
                    current_row.append(Spacer(1, 1))
                rows.append(current_row)

            col_widths = [label_width, label_width]
            table = Table(rows, colWidths=col_widths)
            from reportlab.lib.styles import TableStyle
            from reportlab.lib import colors

            table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )

            doc.build([table])
            return True

        except Exception:
            return False
        finally:
            # Clean up temp images
            for img_path in label_images:
                try:
                    os.unlink(img_path)
                except OSError:
                    pass
