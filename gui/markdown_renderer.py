"""Markdown rendering widget for StockMate help screens."""

from __future__ import annotations

import re
import tkinter as tk
import webbrowser
from typing import Callable


class MarkdownText(tk.Text):
    """A ``tk.Text`` widget that renders a subset of Markdown.

    Supported syntax:
    - Headings (``#``, ``##``, ``###``)
    - **Bold** (``**text**`` or ``__text__``)
    - *Italic* (``*text*`` or ``_text_``)
    - ``Inline code`` (backticks)
    - Code blocks (triple backticks)
    - Links (``[text](url)`` — clickable, opens in browser)
    - Bullet lists (``- item`` / ``* item``)
    - Numbered lists (``1. item``)
    - Blockquotes (``> text``)
    - Strikethrough (``~~text~~``)
    - Horizontal rules (``---``)
    - Admonitions: ``> [!example]``, ``> [!note]``, ``> [!warning]``

    Parameters
    ----------
    master:
        Parent widget.
    **kwargs:
        Forwarded to ``tk.Text``.
    """

    _ADMONITION_COLORS: dict[str, dict[str, str]] = {
        "example": {"bg": "#e3f2fd", "fg": "#1565c0", "border": "#1565c0"},
        "note": {"bg": "#fff9c4", "fg": "#f57f17", "border": "#f57f17"},
        "warning": {"bg": "#ffebee", "fg": "#c62828", "border": "#c62828"},
    }

    def __init__(self, master: tk.Misc, **kwargs) -> None:
        defaults: dict[str, object] = {
            "wrap": tk.WORD,
            "state": tk.NORMAL,
            "borderwidth": 0,
            "highlightthickness": 0,
            "padx": 8,
            "pady": 8,
        }
        defaults.update(kwargs)
        super().__init__(master, **defaults)
        self._setup_styles()
        self.configure(state=tk.DISABLED)

    # -- public API ----------------------------------------------------------

    def insert_markdown(self, index: str, markdown_text: str) -> None:
        """Parse and insert *markdown_text* at *index*.

        Args:
            index: Tkinter text index (e.g. ``"1.0"``).
            markdown_text: Markdown source string.
        """
        self.configure(state=tk.NORMAL)
        self._parse_and_insert(markdown_text)
        self.configure(state=tk.DISABLED)

    # -- style setup ---------------------------------------------------------

    def _setup_styles(self) -> None:
        """Configure text tags for all markdown elements."""
        self.tag_configure("h1", font=("Segoe UI", 20, "bold"), spacing1=12, spacing3=6)
        self.tag_configure("h2", font=("Segoe UI", 16, "bold"), spacing1=10, spacing3=4)
        self.tag_configure("h3", font=("Segoe UI", 13, "bold"), spacing1=8, spacing3=3)
        self.tag_configure("bold", font=("Segoe UI", 10, "bold"))
        self.tag_configure("italic", font=("Segoe UI", 10, "italic"))
        self.tag_configure("code", font=("Consolas", 10), background="#f0f0f0")
        self.tag_configure(
            "codeblock",
            font=("Consolas", 10),
            background="#2b2b2b",
            foreground="#d4d4d4",
            lmargin1=8,
            lmargin2=8,
        )
        self.tag_configure("link", foreground="#0066cc", underline=True)
        self.tag_configure("bullet", lmargin1=24, lmargin2=36)
        self.tag_configure("numbered", lmargin1=24, lmargin2=36)
        self.tag_configure("blockquote", lmargin1=16, lmargin2=24, foreground="#555555")
        self.tag_configure("strikethrough", font=("Segoe UI", 10, "overstrike"))
        self.tag_configure("hr", font=("Segoe UI", 8), foreground="#cccccc")

        # Admonition styles
        for name, colors in self._ADMONITION_COLORS.items():
            tag_name = f"admonition_{name}"
            self.tag_configure(
                tag_name,
                background=colors["bg"],
                foreground=colors["fg"],
                lmargin1=8,
                lmargin2=8,
                borderwidth=2,
            )

        # Link interaction
        self.tag_bind("link", "<Button-1>", self._on_link_click)
        self.tag_bind("link", "<Enter>", lambda e: self.config(cursor="hand2"))
        self.tag_bind("link", "<Leave>", lambda e: self.config(cursor=""))

    # -- parsing -------------------------------------------------------------

    def _parse_and_insert(self, text: str) -> None:
        """Parse *text* line-by-line and insert formatted content."""
        lines = text.split("\n")
        i = 0
        in_codeblock = False
        codeblock_lines: list[str] = []

        while i < len(lines):
            line = lines[i]

            # Code block toggle
            if line.strip().startswith("```"):
                if in_codeblock:
                    self.insert(tk.END, "\n".join(codeblock_lines) + "\n", "codeblock")
                    self.insert(tk.END, "\n")
                    codeblock_lines = []
                    in_codeblock = False
                else:
                    in_codeblock = True
                i += 1
                continue

            if in_codeblock:
                codeblock_lines.append(line)
                i += 1
                continue

            # Horizontal rule
            if re.match(r"^\s*[-*_]{3,}\s*$", line):
                self.insert(tk.END, "\n" + "\u2500" * 60 + "\n", "hr")
                i += 1
                continue

            # Headings
            heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
            if heading_match:
                level = len(heading_match.group(1))
                content = heading_match.group(2).strip()
                tag = f"h{level}"
                self.insert(tk.END, content + "\n", tag)
                i += 1
                continue

            # Blockquote / admonition
            if line.startswith(">"):
                i = self._insert_blockquote(lines, i)
                continue

            # Bullet list
            if re.match(r"^\s*[-*]\s+", line):
                i = self._insert_list(lines, i, "bullet")
                continue

            # Numbered list
            if re.match(r"^\s*\d+\.\s+", line):
                i = self._insert_list(lines, i, "numbered")
                continue

            # Regular paragraph
            self._insert_inline_formatted(line + "\n", [])
            i += 1

    def _insert_blockquote(self, lines: list[str], start: int) -> int:
        """Insert a blockquote, detecting admonitions.

        Returns the next line index to process.
        """
        i = start
        quote_lines: list[str] = []

        while i < len(lines) and lines[i].startswith(">"):
            quote_lines.append(lines[i][1:].strip())
            i += 1

        if not quote_lines:
            return i

        # Check for admonition
        first = quote_lines[0]
        admonition_match = re.match(r"\[!(\w+)\]\s*(.*)", first)
        if admonition_match:
            kind = admonition_match.group(1).lower()
            remainder = admonition_match.group(2)
            quote_lines[0] = remainder
            if kind in self._ADMONITION_COLORS:
                tag = f"admonition_{kind}"
                content = "\n".join(quote_lines).strip()
                self.insert(tk.END, f" {content}\n", tag)
                self.insert(tk.END, "\n")
                return i

        # Regular blockquote
        content = "\n".join(quote_lines)
        self._insert_inline_formatted(content + "\n", ["blockquote"])
        return i

    def _insert_list(
        self,
        lines: list[str],
        start: int,
        tag: str,
    ) -> int:
        """Insert a list (bullet or numbered).

        Returns the next line index to process.
        """
        i = start
        counter = 0

        while i < len(lines):
            line = lines[i]

            if tag == "bullet":
                match = re.match(r"^\s*[-*]\s+(.*)$", line)
            else:
                match = re.match(r"^\s*\d+\.\s+(.*)$", line)

            if not match:
                break

            counter += 1
            content = match.group(1)

            if tag == "numbered":
                prefix = f"{counter}. "
            else:
                prefix = "\u2022 "

            self.insert(tk.END, prefix, tag)
            self._insert_inline_formatted(content + "\n", [tag])
            i += 1

        self.insert(tk.END, "\n")
        return i

    def _insert_inline_formatted(self, text: str, base_tags: list[str]) -> None:
        """Insert *text* with inline formatting (bold, italic, code, links, strike).

        Args:
            text: Text that may contain inline markdown.
            base_tags: Tags to apply to the entire span.
        """
        # Tokenize: code spans first (to avoid processing their contents)
        tokens = self._tokenize_inline(text)

        for token_text, is_code in tokens:
            if is_code:
                self.insert(tk.END, token_text, ["code"] + base_tags)
                continue

            # Process bold, italic, strikethrough, links
            tags = list(base_tags)
            processed = self._apply_inline_styles(token_text, tags)

    def _tokenize_inline(self, text: str) -> list[tuple[str, bool]]:
        """Split text into code and non-code segments.

        Returns list of (text, is_code) tuples.
        """
        tokens: list[tuple[str, bool]] = []
        pattern = r"`([^`]+)`"
        last_end = 0

        for match in re.finditer(pattern, text):
            if match.start() > last_end:
                tokens.append((text[last_end : match.start()], False))
            tokens.append((match.group(1), True))
            last_end = match.end()

        if last_end < len(text):
            tokens.append((text[last_end:], False))

        return tokens

    def _apply_inline_styles(self, text: str, base_tags: list[str]) -> None:
        """Apply bold, italic, strikethrough, and link styles to *text*."""
        # Links: [text](url)
        link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"
        # Bold: **text** or __text__
        bold_pattern = r"\*\*(.+?)\*\*|__(.+?)__"
        # Italic: *text* or _text_
        italic_pattern = r"\*(.+?)\*|_(.+?)_"
        # Strikethrough: ~~text~~
        strike_pattern = r"~~(.+?)~~"

        # Process links first
        segments = self._split_by_pattern(text, link_pattern)
        for seg_text, is_link, url in segments:
            if is_link:
                self._insert_link(seg_text, url, base_tags)
                continue

            # Process bold within non-link segments
            sub_segments = self._split_by_pattern(seg_text, bold_pattern)
            for sub_text, is_bold, _ in sub_segments:
                if is_bold:
                    self.insert(tk.END, sub_text, ["bold"] + base_tags)
                    continue

                # Process italic
                italic_segments = self._split_by_pattern(sub_text, italic_pattern)
                for it_text, is_italic, _ in italic_segments:
                    if is_italic:
                        self.insert(tk.END, it_text, ["italic"] + base_tags)
                        continue

                    # Process strikethrough
                    strike_segments = self._split_by_pattern(it_text, strike_pattern)
                    for st_text, is_strike, _ in strike_segments:
                        if is_strike:
                            self.insert(tk.END, st_text, ["strikethrough"] + base_tags)
                            continue
                        # Plain text
                        if st_text:
                            self.insert(tk.END, st_text, base_tags)

    def _split_by_pattern(self, text: str, pattern: str) -> list[tuple[str, bool, str]]:
        """Split *text* by *pattern*, returning (text, is_match, group1) tuples."""
        results: list[tuple[str, bool, str]] = []
        last_end = 0

        for match in re.finditer(pattern, text):
            if match.start() > last_end:
                results.append((text[last_end : match.start()], False, ""))
            # group(1) for links, group(1) or group(2) for bold/italic
            captured = match.group(1) or match.group(2) or ""
            results.append(
                (captured, True, match.group(2) if len(match.groups()) > 1 else "")
            )
            last_end = match.end()

        if last_end < len(text):
            results.append((text[last_end:], False, ""))

        return results

    def _insert_link(self, text: str, url: str, base_tags: list[str]) -> None:
        """Insert a clickable link."""
        self.insert(tk.END, text, ["link"] + base_tags)
        self.tag_bind(
            f"link_{id(text)}",
            "<Button-1>",
            lambda e: self._open_url(url),
        )
        # Store URL on the link tag
        self.tag_configure("link")  # ensure tag exists

    def _on_link_click(self, event: tk.Event) -> None:
        """Handle link click — open URL in browser."""
        try:
            idx = self.index(f"@{event.x},{event.y}")
            tags = self.tag_names(idx)
            if "link" in tags:
                # Get the text at this position as the URL
                sel_start = self.tag_ranges("link")
                if sel_start:
                    url_text = self.get(sel_start[0], sel_start[1])
                    self._open_url(url_text)
        except Exception:
            pass

    @staticmethod
    def _open_url(url: str) -> None:
        """Open *url* in the default web browser."""
        if url:
            webbrowser.open(url)
