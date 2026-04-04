"""Visual ZPL Designer for StockMate.

Provides a drag-and-drop canvas for building ZPL label templates,
a properties panel for fine-tuning element attributes, live Labelary
preview rendering, and template save/load functionality. Supports
2-up (side-by-side) layout for dual-label printing.
"""

from __future__ import annotations

import io
import os
import re
import threading
from typing import Any

import requests
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

from gui.base import BaseScreen


class ZPLDesignerScreen(BaseScreen):
    """Visual WYSIWYG editor for ZPL label templates."""

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)
        self.config = app_context["config"]

        # Ensure templates dir exists
        self.templates_dir = self.config.get_config_dir() / "templates"
        if not os.path.exists(self.templates_dir):
            os.makedirs(self.templates_dir)

        # State
        self.elements: list[dict[str, Any]] = []
        self.selected_index: int | None = None
        self.drag_data: dict[str, Any] = {"x": 0, "y": 0, "item": None}
        self.canvas_scale: float = 1.0

        # Preview State
        self.debounce_timer: threading.Timer | None = None
        self.last_zpl_sent: str = ""

        # Load Configured Dimensions
        self.label_w_mm: int = self.config.get("label_width_mm", 104)
        self.label_h_mm: int = self.config.get("label_height_mm", 22)
        # 203 DPI = ~8 dots per mm
        self.dots_w: int = int(self.label_w_mm * 8)
        self.dots_h: int = int(self.label_h_mm * 8)

        self._init_ui()
        self._load_initial_template()

    # -- lifecycle -----------------------------------------------------------

    def on_show(self) -> None:
        """Called when screen is displayed."""

    # -- UI ------------------------------------------------------------------

    def _init_ui(self) -> None:
        # 1. Toolbar / Header
        toolbar = self.add_header("Visual ZPL Designer", help_section="Label Printing")

        ttk.Button(
            toolbar,
            text="Test Print",
            command=self._test_print,
            bootstyle="secondary",
        ).pack(side=tk.RIGHT, padx=5)
        ttk.Button(
            toolbar,
            text="Set as Active",
            command=self._set_active_template,
            bootstyle="warning",
        ).pack(side=tk.RIGHT, padx=5)
        ttk.Button(
            toolbar,
            text="Save Template",
            command=self._save_template,
            bootstyle="success",
        ).pack(side=tk.RIGHT, padx=5)
        ttk.Button(
            toolbar,
            text="Load Template",
            command=self._load_template_dialog,
            bootstyle="info-outline",
        ).pack(side=tk.RIGHT, padx=5)

        # Canvas Settings
        f_size = ttk.Frame(toolbar)
        f_size.pack(side=tk.RIGHT, padx=20)
        ttk.Label(f_size, text="W:").pack(side=tk.LEFT)
        self.ent_w = ttk.Entry(f_size, width=5)
        self.ent_w.insert(0, str(self.dots_w))
        self.ent_w.pack(side=tk.LEFT)

        ttk.Label(f_size, text="H:").pack(side=tk.LEFT, padx=(5, 0))
        self.ent_h = ttk.Entry(f_size, width=5)
        self.ent_h.insert(0, str(self.dots_h))
        self.ent_h.pack(side=tk.LEFT)

        ttk.Button(
            f_size,
            text="Set",
            command=self._update_canvas_size,
            style="link",
        ).pack(side=tk.LEFT)

        # Main Container
        main_pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        main_pane.pack(fill=tk.BOTH, expand=True)

        # 2. Toolbox (Left)
        toolbox_frame = ttk.LabelFrame(main_pane, text="Tools", padding=10, width=150)
        main_pane.add(toolbox_frame, width=150)

        ttk.Button(
            toolbox_frame,
            text="T  Text",
            command=lambda: self.add_element("text"),
            bootstyle="light",
        ).pack(fill=tk.X, pady=5)
        ttk.Button(
            toolbox_frame,
            text="|||  Barcode",
            command=lambda: self.add_element("barcode"),
            bootstyle="light",
        ).pack(fill=tk.X, pady=5)
        ttk.Button(
            toolbox_frame,
            text="Box / Line",
            command=lambda: self.add_element("box"),
            bootstyle="light",
        ).pack(fill=tk.X, pady=5)

        ttk.Separator(toolbox_frame, orient="horizontal").pack(fill=tk.X, pady=15)

        ttk.Label(toolbox_frame, text="Variables:", font=("bold",)).pack(anchor=tk.W)
        vars_list = [
            "${model}",
            "${price}",
            "${id}",
            "${imei}",
            "${ram_rom}",
            "${grade}",
            "${store_name}",
        ]
        for v in vars_list:
            lbl = ttk.Label(toolbox_frame, text=v, foreground="blue", cursor="hand2")
            lbl.pack(anchor=tk.W, pady=2)
            lbl.bind("<Button-1>", lambda e, val=v: self._insert_variable(val))

        lbl_bc = ttk.Label(
            toolbox_frame,
            text="Barcode ${id}",
            foreground="purple",
            cursor="hand2",
        )
        lbl_bc.pack(anchor=tk.W, pady=5)
        lbl_bc.bind("<Button-1>", lambda e: self.add_element("barcode", data="${id}"))

        # 3. Center Area (Vertical Split: Canvas Top, Preview Bottom)
        center_split = tk.PanedWindow(
            main_pane, orient=tk.VERTICAL, sashrelief=tk.RAISED
        )
        main_pane.add(center_split, stretch="always")

        self.canvas_frame = ttk.Frame(center_split)
        center_split.add(self.canvas_frame, stretch="always", height=400)

        # Scrollbars for Canvas
        h_scroll = ttk.Scrollbar(self.canvas_frame, orient=tk.HORIZONTAL)
        v_scroll = ttk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL)

        self.canvas = tk.Canvas(
            self.canvas_frame,
            bg="white",
            scrollregion=(0, 0, self.dots_w + 100, self.dots_h + 100),
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set,
        )

        h_scroll.config(command=self.canvas.xview)
        v_scroll.config(command=self.canvas.yview)

        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Draw Border for Label Area
        self.canvas.create_rectangle(
            0,
            0,
            self.dots_w,
            self.dots_h,
            outline="#ccc",
            dash=(4, 4),
            tags="border",
        )

        # Events
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

        # --- Preview Pane (Bottom Center - Full Width) ---
        self.preview_pane = ttk.LabelFrame(
            center_split, text="Live Preview", padding=10
        )
        center_split.add(self.preview_pane, stretch="never", height=250)

        # Preview Header (Loading + Toggle)
        f_prev_head = ttk.Frame(self.preview_pane)
        f_prev_head.pack(fill=tk.X, pady=(0, 5))

        self.lbl_preview_loading = ttk.Label(
            f_prev_head,
            text="Waiting...",
            foreground="gray",
            anchor="w",
        )
        self.lbl_preview_loading.pack(side=tk.LEFT)

        self.var_2up = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f_prev_head,
            text="Show 2-Up (Side-by-Side)",
            variable=self.var_2up,
            command=self._on_2up_toggle,
        ).pack(side=tk.RIGHT)

        # Scrollable Canvas for Preview
        f_prev_scroll = ttk.Frame(self.preview_pane)
        f_prev_scroll.pack(fill=tk.BOTH, expand=True)

        self.prev_h_scroll = ttk.Scrollbar(f_prev_scroll, orient=tk.HORIZONTAL)
        self.cv_preview = tk.Canvas(
            f_prev_scroll,
            bg="#ddd",
            height=200,
            xscrollcommand=self.prev_h_scroll.set,
        )
        self.prev_h_scroll.config(command=self.cv_preview.xview)

        self.prev_h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.cv_preview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 4. Right Panel (Split: Properties Top, Code Bottom)
        right_split = tk.PanedWindow(main_pane, orient=tk.VERTICAL)
        main_pane.add(right_split, width=300)

        # Properties (Top Right)
        self.prop_frame = ttk.LabelFrame(right_split, text="Properties", padding=10)
        right_split.add(self.prop_frame, stretch="never")

        # --- Prop UI Fields ---
        self.props: dict[str, tk.StringVar] = {}

        def add_prop(label: str, key: str, row: int) -> int:
            ttk.Label(self.prop_frame, text=label).grid(
                row=row,
                column=0,
                sticky=tk.W,
                pady=2,
            )
            var = tk.StringVar()
            var.trace("w", lambda *a: self._on_prop_change(key))
            ent = ttk.Entry(self.prop_frame, textvariable=var, width=15)
            ent.grid(row=row, column=1, sticky=tk.W, padx=5, pady=2)
            self.props[key] = var
            return row + 1

        r = 0
        ttk.Label(self.prop_frame, text="Type:").grid(row=r, column=0)
        self.lbl_type = ttk.Label(self.prop_frame, text="-", font=("bold",))
        self.lbl_type.grid(row=r, column=1, sticky=tk.W)
        r += 1

        r = add_prop("X (dots):", "x", r)
        r = add_prop("Y (dots):", "y", r)
        r = add_prop("Data/Text:", "data", r)

        # Font Props
        self.frame_font = ttk.LabelFrame(self.prop_frame, text="Font / Size")
        self.frame_font.grid(row=r, column=0, columnspan=2, sticky="ew", pady=10)

        def add_slider_row(
            parent: tk.Widget,
            label: str,
            var_name: str,
            min_val: float,
            max_val: float,
            row: int,
        ) -> int:
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W)

            self.props[var_name] = tk.StringVar()
            self.props[var_name].trace("w", lambda *a: self._on_prop_change(var_name))
            ent = ttk.Entry(parent, textvariable=self.props[var_name], width=5)
            ent.grid(row=row, column=1, sticky=tk.W)

            scale = ttk.Scale(
                parent,
                from_=min_val,
                to=max_val,
                command=lambda v, name=var_name: self.props[name].set(int(float(v))),
            )
            scale.grid(row=row + 1, column=0, columnspan=2, sticky="ew", padx=5)

            def update_scale(*a: Any) -> None:
                try:
                    scale.set(float(self.props[var_name].get()))
                except (ValueError, TypeError):
                    pass

            self.props[var_name].trace("w", update_scale)

            return row + 2

        # Font Height/Width
        r_f = 0
        r_f = add_slider_row(self.frame_font, "Height:", "h", 10, 200, r_f)
        r_f = add_slider_row(self.frame_font, "Width:", "w", 10, 200, r_f)

        # Text Block / Align
        ttk.Label(self.frame_font, text="Block Width:").grid(
            row=r_f,
            column=0,
            sticky=tk.W,
        )
        self.props["block_w"] = tk.StringVar(value="0")
        self.props["block_w"].trace("w", lambda *a: self._on_prop_change("block_w"))
        ttk.Entry(self.frame_font, textvariable=self.props["block_w"], width=5).grid(
            row=r_f,
            column=1,
        )
        r_f += 1

        ttk.Label(self.frame_font, text="Align (L/C/R):").grid(
            row=r_f,
            column=0,
            sticky=tk.W,
        )
        self.props["align"] = tk.StringVar(value="L")
        self.props["align"].trace("w", lambda *a: self._on_prop_change("align"))
        ttk.Entry(self.frame_font, textvariable=self.props["align"], width=5).grid(
            row=r_f,
            column=1,
        )
        r_f += 1

        self.var_bold = tk.BooleanVar()
        self.chk_bold = ttk.Checkbutton(
            self.frame_font,
            text="Bold",
            variable=self.var_bold,
            command=lambda: self._on_prop_change("bold"),
        )
        self.chk_bold.grid(row=r_f, column=0, columnspan=2, sticky=tk.W)

        self.var_invert = tk.BooleanVar()
        self.chk_invert = ttk.Checkbutton(
            self.frame_font,
            text="Invert (^FR)",
            variable=self.var_invert,
            command=lambda: self._on_prop_change("invert"),
        )
        self.chk_invert.grid(row=r_f + 1, column=0, columnspan=2, sticky=tk.W)

        # Box Specifics
        self.frame_box = ttk.LabelFrame(self.prop_frame, text="Box Dims")
        self.frame_box.grid(row=r + 1, column=0, columnspan=2, sticky="ew", pady=10)

        r_b = 0
        r_b = add_slider_row(self.frame_box, "Width:", "bw", 10, 800, r_b)
        r_b = add_slider_row(self.frame_box, "Height:", "bh", 10, 600, r_b)

        ttk.Label(self.frame_box, text="Thick:").grid(row=r_b, column=0)
        self.props["bt"] = tk.StringVar()
        self.props["bt"].trace("w", lambda *a: self._on_prop_change("bt"))
        ttk.Entry(self.frame_box, textvariable=self.props["bt"], width=5).grid(
            row=r_b,
            column=1,
        )

        r += 5
        ttk.Button(
            self.prop_frame,
            text="Delete Element",
            command=self._delete_selected,
            bootstyle="danger",
        ).grid(row=r, column=0, columnspan=2, pady=10, sticky="ew")

        # ZPL Code (Bottom Right)
        f_code = ttk.LabelFrame(right_split, text="ZPL Output")
        right_split.add(f_code, stretch="always")

        self.txt_zpl = tk.Text(f_code, width=30, height=10, font=("Consolas", 8))
        self.txt_zpl.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # -- actions -------------------------------------------------------------

    def _test_print(self) -> None:
        """Send current ZPL to the printer with test data substituted."""
        zpl = self.txt_zpl.get("1.0", tk.END)
        replacements = {
            "${model}": "TEST MODEL A",
            "${price}": "Rs. 99,999",
            "${id}": "TEST01",
            "${imei}": "123456789012345",
            "${ram_rom}": "8/128 GB",
            "${grade}": "A",
            "${store_name}": self.config.get("store_name", "Test Store"),
            "${model_2}": "TEST MODEL B",
            "${price_2}": "Rs. 88,888",
            "${id_2}": "TEST02",
            "${imei_2}": "098765432109876",
            "${ram_rom_2}": "12/256 GB",
            "${grade_2}": "B",
            "${store_name_2}": self.config.get("store_name", "Test Store"),
        }
        for k, v in replacements.items():
            zpl = zpl.replace(k, v)

        success = self.app["printer"].send_raw_zpl(zpl)
        if success:
            messagebox.showinfo("Printed", "Test print sent to default printer.")
        else:
            messagebox.showerror(
                "Error",
                "Failed to print. Check connection or default printer.",
            )

    def _save_template(self) -> None:
        """Save current ZPL to a .zpl file."""
        zpl = self._generate_zpl()
        path = filedialog.asksaveasfilename(
            initialdir=self.templates_dir,
            defaultextension=".zpl",
            filetypes=[("ZPL", "*.zpl")],
        )
        if not path:
            return

        with open(path, "w") as f:
            f.write(zpl)
        messagebox.showinfo("Saved", "Template saved successfully.")

    def _load_template_dialog(self) -> None:
        """Open a .zpl file and parse it into canvas elements."""
        path = filedialog.askopenfilename(
            initialdir=self.templates_dir,
            filetypes=[("ZPL", "*.zpl")],
        )
        if path:
            self._try_parse_zpl(path)

    def _update_canvas_size(self) -> None:
        """Apply the W/H entry values to the canvas dimensions."""
        try:
            w = int(self.ent_w.get())
            h = int(self.ent_h.get())
            self.dots_w = w
            self.dots_h = h
            self.canvas.config(scrollregion=(0, 0, w + 100, h + 100))
            self._render_canvas()
        except (ValueError, TypeError):
            pass

    def _on_2up_toggle(self) -> None:
        """Toggle between 2-up (830 dots) and single-label (415 dots) width."""
        if self.var_2up.get():
            self.ent_w.delete(0, tk.END)
            self.ent_w.insert(0, "830")
        else:
            self.ent_w.delete(0, tk.END)
            self.ent_w.insert(0, "415")
        self._update_canvas_size()

    # -- preview -------------------------------------------------------------

    def _trigger_preview_update(self, zpl_code: str) -> None:
        if self.debounce_timer is not None:
            self.debounce_timer.cancel()
        self.debounce_timer = threading.Timer(
            1.5,
            lambda: self._fetch_labelary_preview(zpl_code),
        )
        self.debounce_timer.start()
        self.lbl_preview_loading.config(text="Update pending...")

    def _fetch_labelary_preview(self, zpl: str) -> None:
        final_zpl = zpl

        replacements = {
            "${model}": "Samsung Galaxy S24 Ultra",
            "${price}": "Rs. 1,24,000",
            "${id}": "9901",
            "${imei}": "358912057894561",
            "${ram_rom}": "12/512 GB",
            "${grade}": "A+",
            "${store_name}": self.config.get("store_name", "My Mobile Shop"),
            "${model_2}": "Apple iPhone 15 Pro",
            "${price_2}": "Rs. 1,34,900",
            "${id_2}": "9902",
            "${imei_2}": "990000112233445",
            "${ram_rom_2}": "256 GB",
            "${grade_2}": "New",
            "${store_name_2}": self.config.get("store_name", "My Mobile Shop"),
        }
        for k, v in replacements.items():
            final_zpl = final_zpl.replace(k, v)

        if final_zpl == self.last_zpl_sent and not self.var_2up.get():
            return

        self.last_zpl_sent = final_zpl

        try:
            w_inch = self.dots_w / 203.0
            h_inch = self.dots_h / 203.0

            url = (
                f"https://api.labelary.com/v1/printers/8dpmm/"
                f"labels/{w_inch:.1f}x{h_inch:.1f}/0/"
            )
            response = requests.post(
                url,
                data=final_zpl,
                headers={"Accept": "image/png"},
            )

            if response.status_code == 200:
                try:
                    self.after(
                        0,
                        lambda: self._update_preview_image(response.content),
                    )
                except RuntimeError:
                    pass  # Main loop may have exited
            else:
                try:
                    self.after(0, lambda: self._update_loading_text("Preview Error"))
                except RuntimeError:
                    pass

        except Exception:
            try:
                self.after(0, lambda: self._update_loading_text("Offline"))
            except RuntimeError:
                pass

    def _update_loading_text(self, text: str) -> None:
        if self.winfo_exists():
            self.lbl_preview_loading.config(text=text)

    def _update_preview_image(self, image_data: bytes) -> None:
        if not self.winfo_exists():
            return
        try:
            pil_img = Image.open(io.BytesIO(image_data))
            self.tk_preview = ImageTk.PhotoImage(pil_img)

            self.cv_preview.delete("all")
            self.cv_preview.create_image(0, 0, image=self.tk_preview, anchor="nw")
            self.cv_preview.config(scrollregion=self.cv_preview.bbox("all"))

            self.lbl_preview_loading.config(text="Live Preview (Active)")
        except Exception:
            pass

    # -- canvas logic --------------------------------------------------------

    def add_element(self, etype: str, data: str | None = None) -> None:
        default_data = (
            "Text" if etype == "text" else ("123456" if etype == "barcode" else "")
        )
        if data is not None:
            default_data = data
        el: dict[str, Any] = {
            "type": etype,
            "x": 10,
            "y": 10,
            "data": default_data,
            "h": 30,
            "w": 30,
            "bw": 100,
            "bh": 50,
            "bt": 2,
            "bold": False,
            "invert": False,
            "block_w": 0,
            "align": "L",
        }
        self.elements.append(el)
        self.selected_index = len(self.elements) - 1
        self._render_canvas()
        self._load_props_to_ui()

    def _render_canvas(self) -> None:
        self.canvas.delete("all")
        self.canvas.create_rectangle(
            0,
            0,
            self.dots_w,
            self.dots_h,
            outline="#999",
            dash=(4, 4),
            tags="border",
        )
        self.canvas.create_text(
            self.dots_w / 2,
            -10,
            text=f"{self.dots_w}x{self.dots_h}",
            fill="#999",
        )

        for idx, el in enumerate(self.elements):
            tag = f"el_{idx}"
            color = "black" if not el.get("invert") else "white"
            bg = "black" if el.get("invert") else ""

            if el["type"] == "text":
                f_size = max(8, int(el["h"] * 0.8))
                font_spec: tuple[str, int, str] = (
                    "Arial",
                    f_size,
                    "bold" if el.get("bold") else "normal",
                )

                text_len_est = len(el["data"]) * f_size * 0.6
                box_w = el.get("block_w", 0)
                if box_w == 0:
                    box_w = text_len_est

                if bg:
                    self.canvas.create_rectangle(
                        el["x"],
                        el["y"],
                        el["x"] + box_w,
                        el["y"] + el["h"],
                        fill=bg,
                        tags=tag,
                    )

                anchor_map = {"C": "center", "R": "e", "L": "w", "J": "w"}
                anchor = anchor_map.get(el.get("align", "L"), "w")

                txt_x = el["x"]
                if el.get("align") == "C" and el.get("block_w", 0) > 0:
                    txt_x = el["x"] + (el["block_w"] / 2)
                    anchor = "center"
                elif el.get("align") == "R" and el.get("block_w", 0) > 0:
                    txt_x = el["x"] + el["block_w"]
                    anchor = "e"

                self.canvas.create_text(
                    txt_x,
                    el["y"],
                    text=el["data"],
                    anchor=anchor,
                    font=font_spec,
                    fill=color,
                    tags=tag,
                )

                if idx == self.selected_index and el.get("block_w", 0) > 0:
                    self.canvas.create_rectangle(
                        el["x"],
                        el["y"],
                        el["x"] + el["block_w"],
                        el["y"] + el["h"],
                        outline="lightblue",
                        dash=(2, 2),
                        tags=tag,
                    )

            elif el["type"] == "barcode":
                h = int(el.get("h", 40))
                self.canvas.create_rectangle(
                    el["x"],
                    el["y"],
                    el["x"] + 200,
                    el["y"] + h,
                    fill="#eee",
                    outline="black",
                    tags=tag,
                )
                self.canvas.create_text(
                    el["x"] + 10,
                    el["y"] + h / 2,
                    text=f"||| {el['data']} |||",
                    anchor="w",
                    tags=tag,
                )
            elif el["type"] == "box":
                self.canvas.create_rectangle(
                    el["x"],
                    el["y"],
                    el["x"] + el["bw"],
                    el["y"] + el["bh"],
                    width=el["bt"],
                    outline="black",
                    tags=tag,
                )

            if idx == self.selected_index:
                bbox = self.canvas.bbox(tag)
                if bbox:
                    self.canvas.create_rectangle(
                        bbox[0] - 2,
                        bbox[1] - 2,
                        bbox[2] + 2,
                        bbox[3] + 2,
                        outline="blue",
                        tags=tag,
                    )

        self._generate_zpl()

    def _on_canvas_click(self, event: tk.Event) -> None:
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        items = self.canvas.find_closest(x, y, halo=5)
        if items:
            tags = self.canvas.gettags(items[0])
            for t in tags:
                if t.startswith("el_"):
                    self.selected_index = int(t.split("_")[1])
                    self.drag_data = {"x": x, "y": y, "item": self.selected_index}
                    self._render_canvas()
                    self._load_props_to_ui()
                    return
        self.selected_index = None
        self._render_canvas()

    def _on_canvas_drag(self, event: tk.Event) -> None:
        if self.selected_index is None:
            return
        el = self.elements[self.selected_index]
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        el["x"] = int(el["x"] + (cx - self.drag_data["x"]))
        el["y"] = int(el["y"] + (cy - self.drag_data["y"]))
        self.drag_data["x"] = cx
        self.drag_data["y"] = cy
        self.props["x"].set(str(el["x"]))
        self.props["y"].set(str(el["y"]))
        self._render_canvas()

    def _on_canvas_release(self, event: tk.Event) -> None:
        self.drag_data["item"] = None

    def _load_props_to_ui(self) -> None:
        if self.selected_index is None:
            return
        el = self.elements[self.selected_index]
        self.lbl_type.config(text=el["type"].upper())
        self.props["x"].set(str(el["x"]))
        self.props["y"].set(str(el["y"]))
        self.props["data"].set(el["data"])
        self.props["h"].set(str(el.get("h", 30)))
        self.props["w"].set(str(el.get("w", 30)))
        self.props["bw"].set(str(el.get("bw", 50)))
        self.props["bh"].set(str(el.get("bh", 50)))
        self.props["bt"].set(str(el.get("bt", 1)))
        self.props["block_w"].set(str(el.get("block_w", 0)))
        self.props["align"].set(el.get("align", "L"))
        self.var_bold.set(el.get("bold", False))
        self.var_invert.set(el.get("invert", False))

        if el["type"] == "box":
            self.frame_font.grid_remove()
            self.frame_box.grid()
        elif el["type"] == "barcode":
            self.frame_font.grid()
            self.frame_box.grid_remove()
        else:
            self.frame_font.grid()
            self.frame_box.grid_remove()

    def _on_prop_change(self, key: str) -> None:
        if self.selected_index is None:
            return
        el = self.elements[self.selected_index]
        try:
            val = self.props[key].get()
            if key in ("x", "y", "h", "w", "bw", "bh", "bt", "block_w"):
                el[key] = int(val)
            elif key == "data":
                el[key] = val
            elif key == "align":
                el[key] = val
            elif key == "bold":
                el["bold"] = self.var_bold.get()
            elif key == "invert":
                el["invert"] = self.var_invert.get()
            self._render_canvas()
        except (ValueError, TypeError):
            pass

    def _insert_variable(self, var_text: str) -> None:
        self.add_element("text", data=var_text)

    def _delete_selected(self) -> None:
        if self.selected_index is not None:
            self.elements.pop(self.selected_index)
            self.selected_index = None
            self._render_canvas()

    # -- ZPL generation ------------------------------------------------------

    def _generate_element_zpl(
        self, el: dict[str, Any], off_x: int = 0, off_y: int = 0
    ) -> str:
        x = el["x"] + off_x
        y = el["y"] + off_y
        cmd = f"^FO{x},{y}"
        if el["type"] == "text":
            cmd += f"^A0N,{el['h']},{el['w']}"
            if el.get("invert"):
                cmd += "^FR"
            bw = el.get("block_w", 0)
            align = el.get("align", "L")
            if bw > 0:
                cmd += f"^FB{bw},1,0,{align},0"
            cmd += f"^FD{el['data']}^FS"
        elif el["type"] == "barcode":
            cmd += f"^BY2,2,{el['h']}^BCN,{el['h']},N,N,N^FD{el['data']}^FS"
        elif el["type"] == "box":
            cmd += f"^GB{el['bw']},{el['bh']},{el['bt']},B,0^FS"
        return cmd

    def _generate_zpl(self) -> str:
        zpl = [f"^XA^PW{self.dots_w}^LL{self.dots_h}"]
        for el in self.elements:
            zpl.append(self._generate_element_zpl(el))
        zpl.append("^XZ")
        full_zpl = "\n".join(zpl)
        self.txt_zpl.delete("1.0", tk.END)
        self.txt_zpl.insert("1.0", full_zpl)
        self._trigger_preview_update(full_zpl)
        return full_zpl

    # -- template parsing ----------------------------------------------------

    def _try_parse_zpl(self, path: str) -> None:
        try:
            with open(path, "r") as f:
                raw = f.read()
            self.elements = []

            # Detect dimensions
            pw = re.search(r"^PW(\d+)", raw, re.MULTILINE)
            ll = re.search(r"^LL(\d+)", raw, re.MULTILINE)
            if pw:
                self.dots_w = int(pw.group(1))
                self.ent_w.delete(0, tk.END)
                self.ent_w.insert(0, str(self.dots_w))
            if ll:
                self.dots_h = int(ll.group(1))
                self.ent_h.delete(0, tk.END)
                self.ent_h.insert(0, str(self.dots_h))
            self._update_canvas_size()

            # Tokenize by ^FO
            clean_raw = raw.replace("\n", " ").replace("\r", "")
            fo_pattern = re.compile(r"\^FO(\d+),(\d+)(.*?)\^FS")
            matches = fo_pattern.findall(clean_raw)

            for m in matches:
                x, y, content = int(m[0]), int(m[1]), m[2]
                el: dict[str, Any] = {
                    "x": x,
                    "y": y,
                    "bold": False,
                    "invert": False,
                    "block_w": 0,
                    "align": "L",
                }

                font_match = re.search(r"\^A0N,(\d+),(\d+)", content)
                if font_match:
                    el["type"] = "text"
                    el["h"] = int(font_match.group(1))
                    el["w"] = int(font_match.group(2))
                    if "^FR" in content:
                        el["invert"] = True

                    fb_match = re.search(
                        r"\^FB(\d+),(\d+),(\d+),([A-Z]),(\d+)",
                        content,
                    )
                    if fb_match:
                        el["block_w"] = int(fb_match.group(1))
                        el["align"] = fb_match.group(4)

                    fd_match = re.search(r"\^FD(.*?)$", content)
                    if fd_match:
                        el["data"] = fd_match.group(1)
                    else:
                        el["data"] = "Text"

                elif "^BC" in content:
                    el["type"] = "barcode"
                    bc_match = re.search(r"\^BCN,(\d+)", content)
                    el["h"] = int(bc_match.group(1)) if bc_match else 50
                    el["w"] = 30
                    fd_match = re.search(r"\^FD(.*?)$", content)
                    el["data"] = fd_match.group(1) if fd_match else "123"

                elif "^GB" in content:
                    el["type"] = "box"
                    gb_match = re.search(r"\^GB(\d+),(\d+),(\d+)", content)
                    if gb_match:
                        el["bw"] = int(gb_match.group(1))
                        el["bh"] = int(gb_match.group(2))
                        el["bt"] = int(gb_match.group(3))
                    else:
                        el["bw"], el["bh"], el["bt"] = 50, 50, 1
                    el["data"] = ""
                else:
                    continue

                self.elements.append(el)

            self._render_canvas()
            messagebox.showinfo("Loaded", f"Parsed {len(self.elements)} elements.")

        except Exception as exc:
            messagebox.showerror("Error", f"Failed to parse ZPL: {exc}")

    # -- active template -----------------------------------------------------

    def _set_active_template(self) -> None:
        if not messagebox.askyesno(
            "Confirm",
            "This will overwrite the current Active Template used for printing.\n\n"
            "Are you sure?",
        ):
            return

        zpl = self._generate_zpl()
        path = self.config.get_config_dir() / "custom_template.zpl"
        try:
            with open(path, "w") as f:
                f.write(zpl)
            messagebox.showinfo(
                "Success",
                "Template Set as Active!\nInventory printing will now use this layout.",
            )
        except Exception as exc:
            messagebox.showerror("Error", f"Could not save template: {exc}")

    # -- default layout ------------------------------------------------------

    def _load_initial_template(self) -> None:
        """Create the default 2-up layout matching core/printer.py conventions."""
        # 1. Left Label
        self.elements.append(
            {
                "type": "text",
                "x": 0,
                "y": 10,
                "h": 30,
                "w": 30,
                "data": "${store_name}",
                "block_w": 400,
                "align": "C",
                "bold": False,
                "invert": False,
            }
        )
        self.elements.append(
            {
                "type": "barcode",
                "x": 95,
                "y": 42,
                "h": 40,
                "w": 30,
                "data": "${id}",
                "block_w": 0,
                "align": "L",
                "bold": False,
                "invert": False,
            }
        )
        self.elements.append(
            {
                "type": "text",
                "x": 330,
                "y": 49,
                "h": 24,
                "w": 24,
                "data": "${grade}",
                "block_w": 50,
                "align": "C",
                "bold": False,
                "invert": True,
            }
        )
        self.elements.append(
            {
                "type": "text",
                "x": 0,
                "y": 85,
                "h": 25,
                "w": 25,
                "data": "${id}",
                "block_w": 400,
                "align": "C",
                "bold": False,
                "invert": False,
            }
        )
        self.elements.append(
            {
                "type": "text",
                "x": 25,
                "y": 112,
                "h": 29,
                "w": 29,
                "data": "${model}",
                "block_w": 350,
                "align": "L",
                "bold": False,
                "invert": False,
            }
        )
        self.elements.append(
            {
                "type": "text",
                "x": 25,
                "y": 145,
                "h": 26,
                "w": 26,
                "data": "${ram_rom}",
                "block_w": 200,
                "align": "L",
                "bold": False,
                "invert": False,
            }
        )
        self.elements.append(
            {
                "type": "text",
                "x": 150,
                "y": 142,
                "h": 32,
                "w": 32,
                "data": "${price}",
                "block_w": 240,
                "align": "R",
                "bold": False,
                "invert": False,
            }
        )

        # 2. Right Label (Offset +416)
        self.elements.append(
            {
                "type": "text",
                "x": 416,
                "y": 10,
                "h": 30,
                "w": 30,
                "data": "${store_name_2}",
                "block_w": 400,
                "align": "C",
                "bold": False,
                "invert": False,
            }
        )
        self.elements.append(
            {
                "type": "barcode",
                "x": 511,
                "y": 42,
                "h": 40,
                "w": 30,
                "data": "${id_2}",
                "block_w": 0,
                "align": "L",
                "bold": False,
                "invert": False,
            }
        )
        self.elements.append(
            {
                "type": "text",
                "x": 740,
                "y": 49,
                "h": 24,
                "w": 24,
                "data": "${grade_2}",
                "block_w": 50,
                "align": "C",
                "bold": False,
                "invert": True,
            }
        )
        self.elements.append(
            {
                "type": "text",
                "x": 416,
                "y": 85,
                "h": 25,
                "w": 25,
                "data": "${id_2}",
                "block_w": 400,
                "align": "C",
                "bold": False,
                "invert": False,
            }
        )
        self.elements.append(
            {
                "type": "text",
                "x": 441,
                "y": 112,
                "h": 29,
                "w": 29,
                "data": "${model_2}",
                "block_w": 350,
                "align": "L",
                "bold": False,
                "invert": False,
            }
        )
        self.elements.append(
            {
                "type": "text",
                "x": 441,
                "y": 145,
                "h": 26,
                "w": 26,
                "data": "${ram_rom_2}",
                "block_w": 200,
                "align": "L",
                "bold": False,
                "invert": False,
            }
        )
        self.elements.append(
            {
                "type": "text",
                "x": 566,
                "y": 142,
                "h": 32,
                "w": 32,
                "data": "${price_2}",
                "block_w": 240,
                "align": "R",
                "bold": False,
                "invert": False,
            }
        )

        self._render_canvas()
        self.selected_index = None
