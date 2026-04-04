"""Local HTTP server serving the web-based ZPL label designer."""

import json
import logging
import os
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Any, Optional

logger = logging.getLogger(__name__)

PORT = 8910
HOST = "127.0.0.1"
CUSTOM_TEMPLATE_KEY = "custom_template.zpl"


class _ZPLHandler(SimpleHTTPRequestHandler):
    """Custom request handler for the ZPL designer endpoints."""

    # Overridden at runtime by start_server()
    _zpl_designer_dir: str = ""
    _config_manager: Any = None

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug(fmt, *args)

    # -- routing -------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/template":
            self._serve_template()
            return

        if self.path == "/" or self.path == "/index.html":
            self._serve_index()
            return

        # Serve static files from the designer directory
        self._serve_static()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/save":
            self._handle_save()
            return

        self.send_error(404, "Not Found")

    # -- endpoint handlers ---------------------------------------------------

    def _serve_index(self) -> None:
        index_path = os.path.join(self._zpl_designer_dir, "index.html")
        if not os.path.isfile(index_path):
            self.send_error(404, "index.html not found")
            return
        self._send_file(index_path, "text/html; charset=utf-8")

    def _serve_template(self) -> None:
        template_content = self._load_custom_template()
        store_name = self._get_store_name()
        payload = json.dumps(
            {
                "template": template_content,
                "store_name": store_name,
            }
        )
        self._send_json(200, payload)

    def _handle_save(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error(400, "Empty request body")
            return

        try:
            body = self.rfile.read(content_length)
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.send_error(400, f"Invalid JSON: {exc}")
            return

        template_text = data.get("template", "")
        if not isinstance(template_text, str):
            self.send_error(400, "'template' must be a string")
            return

        saved = self._save_custom_template(template_text)
        if saved:
            self._send_json(200, json.dumps({"status": "ok"}))
        else:
            self.send_error(500, "Failed to save template")

    def _serve_static(self) -> None:
        # Strip leading slash and serve relative to designer dir
        relative_path = self.path.lstrip("/")
        file_path = os.path.join(self._zpl_designer_dir, relative_path)

        if not os.path.isfile(file_path):
            self.send_error(404, f"File not found: {relative_path}")
            return

        mime = self._guess_mime(file_path)
        self._send_file(file_path, mime)

    # -- helpers -------------------------------------------------------------

    def _load_custom_template(self) -> str:
        """Load custom ZPL template from config, falling back to empty string."""
        if self._config_manager is None:
            return ""
        return self._config_manager.get(CUSTOM_TEMPLATE_KEY, "")

    def _save_custom_template(self, template: str) -> bool:
        """Persist custom ZPL template to config manager."""
        if self._config_manager is None:
            return False
        try:
            self._config_manager.set(CUSTOM_TEMPLATE_KEY, template)
            return True
        except Exception as exc:
            logger.error("Failed to save ZPL template: %s", exc)
            return False

    def _get_store_name(self) -> str:
        """Return the configured store name."""
        if self._config_manager is None:
            return ""
        return self._config_manager.get("store_name", "")

    def _send_file(self, file_path: str, content_type: str) -> None:
        """Read and send a file with the given content type."""
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except OSError as exc:
            logger.error("Error serving file %s: %s", file_path, exc)
            self.send_error(500, "Internal Server Error")

    def _send_json(self, status: int, body: str) -> None:
        """Send a JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    @staticmethod
    def _guess_mime(path: str) -> str:
        """Return a MIME type based on file extension."""
        ext = os.path.splitext(path)[1].lower()
        return {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
            ".woff": "font/woff",
            ".woff2": "font/woff2",
        }.get(ext, "application/octet-stream")


def start_server(zpl_designer_dir: str, config_manager: Any) -> threading.Thread:
    """Start the ZPL designer HTTP server in a background daemon thread.

    Returns the thread object.  Logs a warning and returns a stopped thread
    if the port is already in use.
    """
    _ZPLHandler._zpl_designer_dir = zpl_designer_dir
    _ZPLHandler._config_manager = config_manager

    def _run() -> None:
        try:
            server = HTTPServer((HOST, PORT), _ZPLHandler)
            logger.info("ZPL designer server running at http://%s:%d", HOST, PORT)
            server.serve_forever()
        except OSError as exc:
            if "address already in use" in str(exc).lower() or exc.errno == 98:
                logger.warning(
                    "Port %d is already in use — ZPL designer may already be running",
                    PORT,
                )
            else:
                logger.error("ZPL designer server failed to start: %s", exc)

    thread = threading.Thread(target=_run, name="ZPLDesignerServer", daemon=True)
    thread.start()
    return thread


def open_designer() -> None:
    """Open the ZPL designer in the default web browser."""
    url = f"http://{HOST}:{PORT}"
    webbrowser.open(url)
