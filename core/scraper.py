"""Phone details scraper — fetch model info from IMEI via external APIs."""

import logging
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    from Cryptodome.Cipher import AES
except ImportError:
    from Crypto.Cipher import AES  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

_IMEI_PATTERN = re.compile(r"^\d{14,16}$")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 10
_REQUEST_DELAY = 0.5

_GSMARENA_SEARCH_URL = "https://www.gsmarena.com/results.php3"


class PhoneScraper:
    """Fetch phone brand, model, and full name from an IMEI number."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})
        self._session.timeout = _REQUEST_TIMEOUT

    # -- public API ----------------------------------------------------------

    def fetch_details(self, imei: str) -> Optional[dict[str, str]]:
        """Return phone details dict or None on any failure.

        Pipeline: validate IMEI → resolve model code → search GSMArena →
        extract phone name → return {brand, model, full_name}.
        """
        model_code = self._resolve_model_code(imei)
        if model_code is None:
            return None

        time.sleep(_REQUEST_DELAY)

        full_name = self._search_gsmarena(model_code)
        if full_name is None:
            return None

        brand, model = self._split_brand_model(full_name)
        return {"brand": brand, "model": model, "full_name": full_name}

    # -- internal helpers ----------------------------------------------------

    def _decrypt_aes(self, encrypted_data: bytes, key: bytes, iv: bytes) -> str:
        """Decrypt AES-CBC ciphertext and return UTF-8 plaintext."""
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded = cipher.decrypt(encrypted_data)
        return self._unpad(padded).decode("utf-8")

    @staticmethod
    def _unpad(data: bytes) -> bytes:
        """Remove PKCS7 padding."""
        pad_len = data[-1]
        if pad_len < 1 or pad_len > 16:
            raise ValueError(f"Invalid PKCS7 padding byte: {pad_len}")
        if data[-pad_len:] != bytes([pad_len]) * pad_len:
            raise ValueError("PKCS7 padding mismatch")
        return data[:-pad_len]

    def _resolve_model_code(self, imei: str) -> Optional[str]:
        """Look up the model / product code for a given IMEI."""
        if not self._is_valid_imei(imei):
            return None

        try:
            resp = self._session.get(
                f"https://api.imeicheck.com/imei/{imei}",
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("model_code") or data.get("product_code")
        except Exception as exc:
            logger.debug("IMEI lookup failed for %s: %s", imei, exc)
            return None

    def _search_gsmarena(self, model_code: str) -> Optional[str]:
        """Search GSMArena and return the best-match phone full name."""
        try:
            resp = self._session.get(
                _GSMARENA_SEARCH_URL,
                params={"sQuickSearch": "yes", "sName": model_code},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()

            # Attempt to detect encrypted payload in response
            phone_name = self._try_decrypt_response(resp.content)
            if phone_name is not None:
                return phone_name

            # Fall back to HTML parsing
            return self._parse_search_html(resp.text)
        except Exception as exc:
            logger.debug("GSMArena search failed for '%s': %s", model_code, exc)
            return None

    def _try_decrypt_response(self, raw: bytes) -> Optional[str]:
        """If the response body looks like an encrypted blob, decrypt it.

        Returns the decrypted string or None.
        """
        # Heuristic: if the body is short and contains no HTML tags, it may
        # be a raw encrypted payload.  In practice the caller must supply
        # the correct key/iv — here we return None and let HTML parsing
        # handle the normal case.  Override this method in a subclass if
        # you have a known key/iv pair.
        return None

    def _parse_search_html(self, html: str) -> Optional[str]:
        """Extract the first phone name from GSMArena search results HTML."""
        soup = BeautifulSoup(html, "html.parser")

        # GSMArena lists results in <div class="makers"> → <ul> → <li> → <a>
        makers = soup.find("div", class_="makers")
        if makers is None:
            # Try alternative selector used on newer layouts
            makers = soup.find("ul", class_="makers")

        if makers is None:
            return None

        first_link = makers.find("a")
        if first_link is None:
            return None

        # The link text typically looks like "Samsung Galaxy S24 Ultra"
        name = first_link.get_text(strip=True)
        # Strip any trailing "°C" or extra whitespace artifacts
        name = re.sub(r"\s+", " ", name).strip()
        return name if name else None

    @staticmethod
    def _split_brand_model(full_name: str) -> tuple[str, str]:
        """Split a full phone name into brand and model parts."""
        parts = full_name.split(None, 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return full_name, full_name

    @staticmethod
    def _is_valid_imei(imei: str) -> bool:
        """Return True when *imei* contains 14–16 digits only."""
        return bool(_IMEI_PATTERN.match(imei))
