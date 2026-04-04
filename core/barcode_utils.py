"""
Barcode generation and label preview utilities for StockMate.

Generates Code128 barcode images and full label previews
with store branding, item details, and pricing.
"""

import os
import platform
import re
from typing import Any

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Cross-platform font loading
# ---------------------------------------------------------------------------

_FONT_PATHS: dict[str, list[str]] = {
    "Windows": [
        "C:/Windows/Fonts/{name}.ttf",
    ],
    "Darwin": [
        "/System/Library/Fonts/{name}.ttf",
        "/Library/Fonts/{name}.ttf",
    ],
    "Linux": [
        "/usr/share/fonts/truetype/dejavu/{name}.ttf",
        "/usr/share/fonts/truetype/liberation/{name}.ttf",
        "/usr/share/fonts/TTF/{name}.ttf",
    ],
}


def load_font(
    font_name: str, size: int
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a TrueType font with cross-platform path resolution.

    Tries OS-specific font directories in order, falling back to
    ``ImageFont.load_default()`` when no match is found.
    """
    system = platform.system()
    candidates = _FONT_PATHS.get(system, _FONT_PATHS["Linux"])

    for pattern in candidates:
        path = pattern.format(name=font_name)
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue

    # Last resort: try font_name as a direct path
    if os.path.isfile(font_name):
        try:
            return ImageFont.truetype(font_name, size)
        except (OSError, IOError):
            pass

    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Data cleaning
# ---------------------------------------------------------------------------

_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")


def _clean_barcode_data(data: str) -> str:
    """Strip non-alphanumeric characters for Code128 compatibility."""
    return _ALNUM_RE.sub("", data).upper()


# ---------------------------------------------------------------------------
# BarcodeGenerator
# ---------------------------------------------------------------------------


class BarcodeGenerator:
    """Generate barcodes and label preview images.

    Takes a *config_manager* to read store branding details.
    """

    def __init__(self, config_manager: Any) -> None:
        self._config = config_manager

    # -- barcode image -------------------------------------------------------

    def generate_barcode_image(
        self,
        data: str,
        width: int = 300,
        height: int = 80,
    ) -> Image.Image:
        """Generate a Code128 barcode as a PIL ``Image``.

        Cleans *data* to alphanumeric-only before encoding.
        """
        if not data:
            raise ValueError("Barcode data cannot be empty")

        import barcode
        from barcode.writer import ImageWriter

        clean = _clean_barcode_data(data)
        if not clean:
            raise ValueError("Barcode data contains no alphanumeric characters")

        code128 = barcode.get("code128", clean, writer=ImageWriter())

        # Render to in-memory image
        from io import BytesIO

        buffer = BytesIO()
        code128.write(
            buffer,
            options={
                "write_text": False,
                "module_width": 0.4,
                "module_height": height / 100.0,
                "quiet_zone": 6.0,
                "font_size": 10,
                "text_distance": 5.0,
            },
        )
        buffer.seek(0)
        img = Image.open(buffer).convert("RGBA")
        img = img.resize((width, height), Image.LANCZOS)

        return img

    # -- label preview -------------------------------------------------------

    def generate_label_preview(
        self,
        item: dict[str, Any],
        width: int = 400,
        height: int = 200,
    ) -> Image.Image:
        """Build a full label preview image for *item*.

        Layout (top to bottom):
        - Store name header (bold, centered)
        - Model name + RAM/ROM
        - Code128 barcode
        - Unique ID text
        - Price (large, bold)
        """
        # Guard: item must have a price
        price = item.get("price", 0)
        if not isinstance(price, (int, float)) or price < 0:
            raise ValueError(f"Invalid price for label: {price}")

        # White background
        img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Fonts
        font_store = load_font("arialbd", 16)
        font_model = load_font("arial", 13)
        font_id = load_font("arial", 10)
        font_price = load_font("arialbd", 22)
        font_barcode_text = load_font("arial", 8)

        y_cursor = 4

        # Store name header
        store_name = self._config.get("store_name", "Mobile Shop")
        bbox = draw.textbbox((0, 0), store_name, font=font_store)
        text_w = bbox[2] - bbox[0]
        draw.text(
            ((width - text_w) / 2, y_cursor),
            store_name,
            fill="#1a1a2e",
            font=font_store,
        )
        y_cursor += bbox[3] - bbox[0] + 4

        # Horizontal rule
        draw.line([(10, y_cursor), (width - 10, y_cursor)], fill="#bdc3c7", width=1)
        y_cursor += 6

        # Model + RAM/ROM
        model = item.get("model", "Unknown Model")
        ram_rom = item.get("ram_rom", "")
        model_line = f"{model}"
        if ram_rom:
            model_line += f"  |  {ram_rom}"
        bbox = draw.textbbox((0, 0), model_line, font=font_model)
        text_w = bbox[2] - bbox[0]
        draw.text(
            ((width - text_w) / 2, y_cursor),
            model_line,
            fill="#2c3e50",
            font=font_model,
        )
        y_cursor += bbox[3] - bbox[0] + 6

        # Barcode image
        unique_id = str(item.get("unique_id", item.get("id", "0000")))
        try:
            barcode_img = self.generate_barcode_image(
                unique_id, width=width - 20, height=50
            )
            img.paste(barcode_img, (10, y_cursor), barcode_img)
            y_cursor += 54
        except Exception:
            # Fallback: draw placeholder text
            draw.text(
                (10, y_cursor),
                f"||| {unique_id} |||",
                fill="#7f8c8d",
                font=font_barcode_text,
            )
            y_cursor += 16

        # Unique ID text
        bbox = draw.textbbox((0, 0), f"ID: {unique_id}", font=font_id)
        text_w = bbox[2] - bbox[0]
        draw.text(
            ((width - text_w) / 2, y_cursor),
            f"ID: {unique_id}",
            fill="#7f8c8d",
            font=font_id,
        )
        y_cursor += bbox[3] - bbox[0] + 4

        # Price at bottom
        price_str = f"\u20b9{float(price):,.0f}"
        bbox = draw.textbbox((0, 0), price_str, font=font_price)
        text_w = bbox[2] - bbox[0]
        price_y = height - bbox[3] - 8
        draw.text(
            ((width - text_w) / 2, price_y), price_str, fill="#c0392b", font=font_price
        )

        return img.convert("RGB")
