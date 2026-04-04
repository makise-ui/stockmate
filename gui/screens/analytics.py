"""Analytics and management screens for StockMate.

Provides DashboardScreen, AnalyticsScreen, ActivityLogScreen, and ConflictScreen.
All screens extend ``BaseScreen`` and receive the application context dict
containing references to core managers.
"""

from __future__ import annotations

import datetime
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from typing import Any

import ttkbootstrap as tb
from ttkbootstrap.dialogs import Messagebox

from core.constants import (
    FIELD_BUYER,
    FIELD_BUYER_CONTACT,
    FIELD_MODEL,
    FIELD_NOTES,
    FIELD_PRICE,
    FIELD_STATUS,
    FIELD_UNIQUE_ID,
    STATUS_IN,
    STATUS_OUT,
)
from gui.base import BaseScreen
from gui.widgets import CollapsibleFrame


# ---------------------------------------------------------------------------
# DashboardScreen
# ---------------------------------------------------------------------------


class DashboardScreen(BaseScreen):
    """KPI dashboard with alerts, demand insights, and recent activity.

    Displays four KPI cards, AI demand forecast, old/low stock alerts,
    top selling models, and the last 10 activity log entries.
    """

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)

        self._kpi_labels: dict[str, ttk.Label] = {}
        self._forecast_tree: ttk.Treeview | None = None
        self._old_stock_tree: ttk.Treeview | None = None
        self._low_stock_tree: ttk.Treeview | None = None
        self._top_models_tree: ttk.Treeview | None = None
        self._activity_tree: ttk.Treeview | None = None

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the full dashboard layout."""
        # Header
        header = self.add_header("Dashboard")
        self._refresh_btn = ttk.Button(
            header,
            text="↻ Refresh",
            bootstyle="info-outline",
            command=self._refresh_stats,
        )
        self._refresh_btn.pack(side=tk.RIGHT, padx=8)

        # KPI cards row
        self._build_kpi_cards()

        # AI Demand Insights
        self._build_demand_section()

        # Alerts section (two columns)
        self._build_alerts_section()

        # Top Selling Models
        self._build_top_models_section()

        # Recent Activity
        self._build_activity_section()

    def _build_kpi_cards(self) -> None:
        """Create four KPI cards in a grid."""
        card_frame = ttk.Frame(self)
        card_frame.pack(fill=tk.X, padx=12, pady=8)

        cards = [
            ("in_stock", "In Stock", "primary"),
            ("stock_value", "Stock Value", "success"),
            ("sold_month", "Sold This Month", "info"),
            ("aging", "Aging (>60d)", "warning"),
        ]

        for idx, (key, label, style) in enumerate(cards):
            card = ttk.Labelframe(card_frame, text=label, bootstyle=style, padding=12)
            card.grid(row=0, column=idx, padx=4, sticky="nsew")
            card_frame.grid_columnconfigure(idx, weight=1)

            value_lbl = ttk.Label(
                card,
                text="0",
                font=("Segoe UI", 20, "bold"),
                anchor=tk.CENTER,
            )
            value_lbl.pack(fill=tk.X)
            self._kpi_labels[key] = value_lbl

    def _build_demand_section(self) -> None:
        """Build the AI Demand Insights section."""
        demand_frame = ttk.Labelframe(self, text="AI Demand Insights", padding=8)
        demand_frame.pack(fill=tk.X, padx=12, pady=6)

        columns = (
            "model",
            "in_stock",
            "sold_per_week",
            "days_remaining",
            "status_flag",
        )
        self._forecast_tree = ttk.Treeview(
            demand_frame, columns=columns, show="headings", height=5
        )

        self._forecast_tree.heading("model", text="Model")
        self._forecast_tree.heading("in_stock", text="In Stock")
        self._forecast_tree.heading("sold_per_week", text="Sold / Week")
        self._forecast_tree.heading("days_remaining", text="Days Remaining")
        self._forecast_tree.heading("status_flag", text="Status")

        self._forecast_tree.column("model", width=200)
        self._forecast_tree.column("in_stock", width=70, anchor=tk.CENTER)
        self._forecast_tree.column("sold_per_week", width=90, anchor=tk.CENTER)
        self._forecast_tree.column("days_remaining", width=100, anchor=tk.CENTER)
        self._forecast_tree.column("status_flag", width=90, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(
            demand_frame, orient=tk.VERTICAL, command=self._forecast_tree.yview
        )
        self._forecast_tree.configure(yscrollcommand=scrollbar.set)

        self._forecast_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_alerts_section(self) -> None:
        """Build the two-column alerts section."""
        alerts_frame = ttk.Frame(self)
        alerts_frame.pack(fill=tk.X, padx=12, pady=6)

        # Old Stock
        old_frame = ttk.Labelframe(alerts_frame, text="Old Stock (>60 days)", padding=8)
        old_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        old_columns = ("id", "model", "days")
        self._old_stock_tree = ttk.Treeview(
            old_frame, columns=old_columns, show="headings", height=4
        )
        self._old_stock_tree.heading("id", text="ID")
        self._old_stock_tree.heading("model", text="Model")
        self._old_stock_tree.heading("days", text="Days")
        self._old_stock_tree.column("id", width=50, anchor=tk.CENTER)
        self._old_stock_tree.column("model", width=180)
        self._old_stock_tree.column("days", width=50, anchor=tk.CENTER)

        old_scroll = ttk.Scrollbar(
            old_frame, orient=tk.VERTICAL, command=self._old_stock_tree.yview
        )
        self._old_stock_tree.configure(yscrollcommand=old_scroll.set)
        self._old_stock_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        old_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Low Stock Models
        low_frame = ttk.Labelframe(
            alerts_frame, text="Low Stock Models (<5)", padding=8
        )
        low_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))

        low_columns = ("model", "count")
        self._low_stock_tree = ttk.Treeview(
            low_frame, columns=low_columns, show="headings", height=4
        )
        self._low_stock_tree.heading("model", text="Model")
        self._low_stock_tree.heading("count", text="Count")
        self._low_stock_tree.column("model", width=200)
        self._low_stock_tree.column("count", width=50, anchor=tk.CENTER)

        low_scroll = ttk.Scrollbar(
            low_frame, orient=tk.VERTICAL, command=self._low_stock_tree.yview
        )
        self._low_stock_tree.configure(yscrollcommand=low_scroll.set)
        self._low_stock_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        low_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_top_models_section(self) -> None:
        """Build the Top Selling Models section."""
        top_frame = ttk.Labelframe(
            self, text="Top Selling Models (Last 30 Days)", padding=8
        )
        top_frame.pack(fill=tk.X, padx=12, pady=6)

        top_columns = ("model", "sold")
        self._top_models_tree = ttk.Treeview(
            top_frame, columns=top_columns, show="headings", height=4
        )
        self._top_models_tree.heading("model", text="Model")
        self._top_models_tree.heading("sold", text="Units Sold")
        self._top_models_tree.column("model", width=300)
        self._top_models_tree.column("sold", width=80, anchor=tk.CENTER)

        self._top_models_tree.pack(fill=tk.X, expand=True)

    def _build_activity_section(self) -> None:
        """Build the Recent Activity section."""
        activity_frame = ttk.Labelframe(self, text="Recent Activity", padding=8)
        activity_frame.pack(fill=tk.X, padx=12, pady=6)

        activity_columns = ("timestamp", "action", "details")
        self._activity_tree = ttk.Treeview(
            activity_frame, columns=activity_columns, show="headings", height=5
        )
        self._activity_tree.heading("timestamp", text="Timestamp")
        self._activity_tree.heading("action", text="Action")
        self._activity_tree.heading("details", text="Details")
        self._activity_tree.column("timestamp", width=140)
        self._activity_tree.column("action", width=110)
        self._activity_tree.column("details", width=400)

        activity_scroll = ttk.Scrollbar(
            activity_frame, orient=tk.VERTICAL, command=self._activity_tree.yview
        )
        self._activity_tree.configure(yscrollcommand=activity_scroll.set)
        self._activity_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        activity_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # -- data loading --------------------------------------------------------

    def _refresh_stats(self) -> None:
        """Recalculate all KPIs and refresh every section."""
        self._load_kpi_cards()
        self._load_demand_forecast()
        self._load_alerts()
        self._load_top_models()
        self._load_recent_activity()

    def _load_kpi_cards(self) -> None:
        """Populate the four KPI card values."""
        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            for lbl in self._kpi_labels.values():
                lbl.configure(text="0")
            return

        in_stock = df[df[FIELD_STATUS] == STATUS_IN]
        out_stock = df[df[FIELD_STATUS] == STATUS_OUT]

        # In Stock count
        in_stock_count = len(in_stock)
        self._kpi_labels["in_stock"].configure(text=str(in_stock_count))

        # Stock Value
        if not in_stock.empty and FIELD_PRICE in in_stock.columns:
            stock_value = in_stock[FIELD_PRICE].sum()
            self._kpi_labels["stock_value"].configure(text=f"\u20b9{stock_value:,.0f}")
        else:
            self._kpi_labels["stock_value"].configure(text="\u20b90")

        # Sold This Month
        now = datetime.datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        sold_this_month = 0
        if not out_stock.empty:
            for _, row in out_stock.iterrows():
                sold_date = row.get("date_sold")
                if sold_date:
                    try:
                        if isinstance(sold_date, str):
                            sold_dt = datetime.datetime.fromisoformat(sold_date)
                        else:
                            sold_dt = sold_date
                        if sold_dt >= month_start:
                            sold_this_month += 1
                    except (ValueError, TypeError):
                        pass
        self._kpi_labels["sold_month"].configure(text=str(sold_this_month))

        # Aging (>60 days)
        aging_count = 0
        if not in_stock.empty:
            for _, row in in_stock.iterrows():
                date_added = row.get("date_added")
                if date_added:
                    try:
                        if isinstance(date_added, str):
                            added_dt = datetime.datetime.fromisoformat(date_added)
                        else:
                            added_dt = date_added
                        age_days = (now - added_dt).days
                        if age_days > 60:
                            aging_count += 1
                    except (ValueError, TypeError):
                        pass
        self._kpi_labels["aging"].configure(text=str(aging_count))

    def _load_demand_forecast(self) -> None:
        """Load and display the demand forecast from analytics."""
        if self._forecast_tree is None:
            return

        for iid in self._forecast_tree.get_children():
            self._forecast_tree.delete(iid)

        analytics = self.app.get("analytics")
        if analytics is None:
            return

        forecasts = analytics.get_demand_forecast()
        if not forecasts:
            return

        for fc in forecasts:
            days = fc.get("days_remaining", 0)
            days_str = "\u221e" if days == -1 else str(days)
            self._forecast_tree.insert(
                "",
                tk.END,
                values=(
                    fc.get("model", ""),
                    fc.get("in_stock", 0),
                    fc.get("sold_per_week", 0),
                    days_str,
                    fc.get("status_flag", ""),
                ),
            )

    def _load_alerts(self) -> None:
        """Load old stock and low stock alerts."""
        self._load_old_stock_alerts()
        self._load_low_stock_alerts()

    def _load_old_stock_alerts(self) -> None:
        """Populate the old stock tree with items older than 60 days."""
        if self._old_stock_tree is None:
            return

        for iid in self._old_stock_tree.get_children():
            self._old_stock_tree.delete(iid)

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            return

        in_stock = df[df[FIELD_STATUS] == STATUS_IN]
        if in_stock.empty:
            return

        now = datetime.datetime.now()
        for _, row in in_stock.iterrows():
            date_added = row.get("date_added")
            if not date_added:
                continue
            try:
                if isinstance(date_added, str):
                    added_dt = datetime.datetime.fromisoformat(date_added)
                else:
                    added_dt = date_added
                age_days = (now - added_dt).days
                if age_days > 60:
                    self._old_stock_tree.insert(
                        "",
                        tk.END,
                        values=(
                            int(row.get(FIELD_UNIQUE_ID, 0)),
                            row.get(FIELD_MODEL, ""),
                            age_days,
                        ),
                    )
            except (ValueError, TypeError):
                pass

    def _load_low_stock_alerts(self) -> None:
        """Populate the low stock tree with models having fewer than 5 items."""
        if self._low_stock_tree is None:
            return

        for iid in self._low_stock_tree.get_children():
            self._low_stock_tree.delete(iid)

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            return

        in_stock = df[df[FIELD_STATUS] == STATUS_IN]
        if in_stock.empty:
            return

        model_counts = in_stock[FIELD_MODEL].value_counts()
        for model, count in model_counts.items():
            if count < 5:
                self._low_stock_tree.insert("", tk.END, values=(model, int(count)))

    def _load_top_models(self) -> None:
        """Load top selling models from the last 30 days."""
        if self._top_models_tree is None:
            return

        for iid in self._top_models_tree.get_children():
            self._top_models_tree.delete(iid)

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            return

        out_stock = df[df[FIELD_STATUS] == STATUS_OUT]
        if out_stock.empty:
            return

        now = datetime.datetime.now()
        cutoff = now - datetime.timedelta(days=30)
        sold_counts: dict[str, int] = {}

        for _, row in out_stock.iterrows():
            sold_date = row.get("date_sold")
            if not sold_date:
                continue
            try:
                if isinstance(sold_date, str):
                    sold_dt = datetime.datetime.fromisoformat(sold_date)
                else:
                    sold_dt = sold_date
                if sold_dt >= cutoff:
                    model = row.get(FIELD_MODEL, "Unknown")
                    sold_counts[model] = sold_counts.get(model, 0) + 1
            except (ValueError, TypeError):
                pass

        sorted_models = sorted(sold_counts.items(), key=lambda x: x[1], reverse=True)
        for model, count in sorted_models[:10]:
            self._top_models_tree.insert("", tk.END, values=(model, count))

    def _load_recent_activity(self) -> None:
        """Load the last 10 activity log entries."""
        if self._activity_tree is None:
            return

        for iid in self._activity_tree.get_children():
            self._activity_tree.delete(iid)

        logger = self.app.get("activity_logger")
        if logger is None:
            return

        entries = logger.get_entries()
        recent = entries[-10:]

        for entry in recent:
            ts = entry.get("timestamp", "")
            # Truncate timestamp for display
            if len(ts) > 19:
                ts = ts[:19]
            self._activity_tree.insert(
                "",
                tk.END,
                values=(
                    ts,
                    entry.get("action", ""),
                    entry.get("details", ""),
                ),
            )

    # -- lifecycle -----------------------------------------------------------

    def on_show(self) -> None:
        """Refresh all dashboard data when the screen becomes visible."""
        self._refresh_stats()

    def focus_primary(self) -> None:
        """No primary input on dashboard."""


# ---------------------------------------------------------------------------
# AnalyticsScreen
# ---------------------------------------------------------------------------


class AnalyticsScreen(BaseScreen):
    """Business Intelligence view with brand distribution, buyer analysis, and export.

    Displays KPIs, brand breakdown via progress bars, top buyers with clickable
    history, model-wise stock analysis, and PDF export.
    """

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)

        self._kpi_labels: dict[str, ttk.Label] = {}
        self._brand_canvas: tk.Canvas | None = None
        self._buyers_tree: ttk.Treeview | None = None
        self._model_tree: ttk.Treeview | None = None

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the full analytics layout."""
        # Header
        header = self.add_header("Analytics")
        self._sim_btn = ttk.Button(
            header,
            text="Price Simulation",
            bootstyle="warning-outline",
            command=self._run_simulation,
        )
        self._sim_btn.pack(side=tk.RIGHT, padx=4)

        self._export_btn = ttk.Button(
            header,
            text="Export PDF",
            bootstyle="success-outline",
            command=self._export_pdf,
        )
        self._export_btn.pack(side=tk.RIGHT, padx=4)

        # KPI row
        self._build_kpi_row()

        # Brand distribution
        self._build_brand_section()

        # Top Buyers and Model Analysis (two columns)
        self._build_buyers_and_models()

    def _build_kpi_row(self) -> None:
        """Create KPI labels row."""
        kpi_frame = ttk.Frame(self)
        kpi_frame.pack(fill=tk.X, padx=12, pady=8)

        cards = [
            ("stock_value", "Stock Value", "primary"),
            ("items_sold", "Items Sold", "info"),
            ("revenue", "Revenue", "success"),
            ("profit", "Profit", "warning"),
        ]

        for idx, (key, label, style) in enumerate(cards):
            card = ttk.Labelframe(kpi_frame, text=label, bootstyle=style, padding=10)
            card.grid(row=0, column=idx, padx=4, sticky="nsew")
            kpi_frame.grid_columnconfigure(idx, weight=1)

            value_lbl = ttk.Label(
                card,
                text="0",
                font=("Segoe UI", 18, "bold"),
                anchor=tk.CENTER,
            )
            value_lbl.pack(fill=tk.X)
            self._kpi_labels[key] = value_lbl

    def _build_brand_section(self) -> None:
        """Build brand distribution with canvas bars."""
        brand_frame = ttk.Labelframe(self, text="Brand Distribution", padding=8)
        brand_frame.pack(fill=tk.X, padx=12, pady=6)

        self._brand_canvas = tk.Canvas(brand_frame, height=160, bg="#fafafa")
        self._brand_canvas.pack(fill=tk.X, expand=True)

    def _build_buyers_and_models(self) -> None:
        """Build top buyers list and model analysis table."""
        split_frame = ttk.Frame(self)
        split_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

        # Top Buyers
        buyers_frame = ttk.Labelframe(split_frame, text="Top Buyers", padding=8)
        buyers_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        buyer_columns = ("buyer", "total_purchases", "total_spent")
        self._buyers_tree = ttk.Treeview(
            buyers_frame, columns=buyer_columns, show="headings", height=8
        )
        self._buyers_tree.heading("buyer", text="Buyer")
        self._buyers_tree.heading("total_purchases", text="Purchases")
        self._buyers_tree.heading("total_spent", text="Total Spent")
        self._buyers_tree.column("buyer", width=160)
        self._buyers_tree.column("total_purchases", width=80, anchor=tk.CENTER)
        self._buyers_tree.column("total_spent", width=90, anchor=tk.E)

        buyers_scroll = ttk.Scrollbar(
            buyers_frame, orient=tk.VERTICAL, command=self._buyers_tree.yview
        )
        self._buyers_tree.configure(yscrollcommand=buyers_scroll.set)
        self._buyers_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        buyers_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._buyers_tree.bind("<Double-1>", self._on_buyer_double_click)

        # Model Analysis
        model_frame = ttk.Labelframe(
            split_frame, text="Model Stock Analysis", padding=8
        )
        model_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))

        model_columns = ("model", "count", "avg_price", "total_value")
        self._model_tree = ttk.Treeview(
            model_frame, columns=model_columns, show="headings", height=8
        )
        self._model_tree.heading("model", text="Model")
        self._model_tree.heading("count", text="Count")
        self._model_tree.heading("avg_price", text="Avg Price")
        self._model_tree.heading("total_value", text="Total Value")
        self._model_tree.column("model", width=200)
        self._model_tree.column("count", width=60, anchor=tk.CENTER)
        self._model_tree.column("avg_price", width=80, anchor=tk.E)
        self._model_tree.column("total_value", width=90, anchor=tk.E)

        model_scroll = ttk.Scrollbar(
            model_frame, orient=tk.VERTICAL, command=self._model_tree.yview
        )
        self._model_tree.configure(yscrollcommand=model_scroll.set)
        self._model_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        model_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # -- data loading --------------------------------------------------------

    def _refresh_analytics(self) -> None:
        """Recalculate all analytics and refresh every section."""
        self._load_kpi_values()
        self._load_brand_distribution()
        self._load_top_buyers()
        self._load_model_analysis()

    def _load_kpi_values(self) -> None:
        """Populate KPI labels from analytics summary."""
        analytics = self.app.get("analytics")
        if analytics is None:
            return

        summary = analytics.get_summary()

        self._kpi_labels["stock_value"].configure(
            text=f"\u20b9{summary.get('total_value', 0):,.0f}"
        )
        self._kpi_labels["items_sold"].configure(
            text=str(summary.get("realized_sales", 0))
        )

        # Revenue = sum of sold item prices
        inventory = self.app.get("inventory")
        revenue = 0.0
        if inventory is not None:
            df = getattr(inventory, "inventory_df", None)
            if df is not None and not df.empty:
                out_stock = df[df[FIELD_STATUS] == STATUS_OUT]
                if not out_stock.empty and FIELD_PRICE in out_stock.columns:
                    revenue = out_stock[FIELD_PRICE].sum()

        self._kpi_labels["revenue"].configure(text=f"\u20b9{revenue:,.0f}")

        profit = summary.get("realized_profit", 0.0)
        self._kpi_labels["profit"].configure(text=f"\u20b9{profit:,.0f}")

    def _load_brand_distribution(self) -> None:
        """Draw brand distribution bars on the canvas."""
        if self._brand_canvas is None:
            return

        self._brand_canvas.delete("all")

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            self._brand_canvas.create_text(
                200, 80, text="No inventory data", fill="#999"
            )
            return

        in_stock = df[df[FIELD_STATUS] == STATUS_IN]
        if in_stock.empty:
            self._brand_canvas.create_text(
                200, 80, text="No in-stock items", fill="#999"
            )
            return

        brand_counts = in_stock["brand"].value_counts().head(10)
        max_count = brand_counts.max()
        if max_count == 0:
            return

        canvas_width = self._brand_canvas.winfo_width() or 600
        bar_height = 14
        gap = 4
        label_width = 80
        bar_area = canvas_width - label_width - 20

        colors_palette = [
            "#007acc",
            "#28a745",
            "#ffc107",
            "#dc3545",
            "#17a2b8",
            "#6f42c1",
            "#e83e8c",
            "#fd7e14",
            "#20c997",
            "#6610f2",
        ]

        for idx, (brand, count) in enumerate(brand_counts.items()):
            y = idx * (bar_height + gap) + 10
            bar_width = int((count / max_count) * bar_area) if max_count > 0 else 0

            # Label
            self._brand_canvas.create_text(
                label_width // 2,
                y + bar_height // 2,
                text=str(brand)[:10],
                font=("Segoe UI", 8),
                fill="#333",
            )

            # Bar
            if bar_width > 0:
                color = colors_palette[idx % len(colors_palette)]
                self._brand_canvas.create_rectangle(
                    label_width,
                    y,
                    label_width + bar_width,
                    y + bar_height,
                    fill=color,
                    outline=color,
                )

            # Count label
            self._brand_canvas.create_text(
                label_width + bar_width + 20,
                y + bar_height // 2,
                text=str(count),
                font=("Segoe UI", 8),
                fill="#555",
            )

    def _load_top_buyers(self) -> None:
        """Populate the top buyers tree."""
        if self._buyers_tree is None:
            return

        for iid in self._buyers_tree.get_children():
            self._buyers_tree.delete(iid)

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            return

        out_stock = df[df[FIELD_STATUS] == STATUS_OUT]
        if out_stock.empty:
            return

        buyer_data: dict[str, dict[str, Any]] = {}
        for _, row in out_stock.iterrows():
            buyer = str(row.get(FIELD_BUYER, "")).strip()
            if not buyer:
                continue
            if buyer not in buyer_data:
                buyer_data[buyer] = {"count": 0, "spent": 0.0}
            buyer_data[buyer]["count"] += 1
            price = row.get(FIELD_PRICE, 0)
            try:
                buyer_data[buyer]["spent"] += float(price)
            except (ValueError, TypeError):
                pass

        sorted_buyers = sorted(
            buyer_data.items(), key=lambda x: x[1]["count"], reverse=True
        )
        for buyer, data in sorted_buyers[:15]:
            self._buyers_tree.insert(
                "",
                tk.END,
                values=(
                    buyer,
                    data["count"],
                    f"\u20b9{data['spent']:,.0f}",
                ),
            )

    def _load_model_analysis(self) -> None:
        """Populate the model-wise stock analysis table."""
        if self._model_tree is None:
            return

        for iid in self._model_tree.get_children():
            self._model_tree.delete(iid)

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            return

        in_stock = df[df[FIELD_STATUS] == STATUS_IN]
        if in_stock.empty:
            return

        model_groups = in_stock.groupby(FIELD_MODEL)
        for model, group in model_groups:
            count = len(group)
            if FIELD_PRICE in group.columns:
                avg_price = group[FIELD_PRICE].mean()
                total_value = group[FIELD_PRICE].sum()
            else:
                avg_price = 0.0
                total_value = 0.0

            self._model_tree.insert(
                "",
                tk.END,
                values=(
                    model,
                    count,
                    f"\u20b9{avg_price:,.0f}",
                    f"\u20b9{total_value:,.0f}",
                ),
            )

    # -- interactions --------------------------------------------------------

    def _on_buyer_double_click(self, event: tk.Event) -> None:
        """Show buyer history dialog on double-click."""
        sel = self._buyers_tree.selection() if self._buyers_tree else ()
        if not sel:
            return

        item_values = self._buyers_tree.item(sel[0], "values")
        if not item_values:
            return

        buyer_name = item_values[0]
        self._show_buyer_history(buyer_name)

    def _show_buyer_history(self, buyer: str) -> None:
        """Open a dialog showing the buyer's purchase history."""
        if not buyer:
            return

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            messagebox.showinfo("Buyer History", f"No records found for {buyer}")
            return

        out_stock = df[df[FIELD_STATUS] == STATUS_OUT]
        buyer_items = out_stock[out_stock[FIELD_BUYER] == buyer]

        if buyer_items.empty:
            messagebox.showinfo("Buyer History", f"No records found for {buyer}")
            return

        # Build dialog
        dialog = tb.Toplevel(self)
        dialog.title(f"Purchase History — {buyer}")
        dialog.transient(self)
        dialog.geometry("650x400")

        columns = ("id", "model", "price", "date")
        tree = ttk.Treeview(dialog, columns=columns, show="headings")
        tree.heading("id", text="ID")
        tree.heading("model", text="Model")
        tree.heading("price", text="Price")
        tree.heading("date", text="Date")
        tree.column("id", width=50, anchor=tk.CENTER)
        tree.column("model", width=250)
        tree.column("price", width=80, anchor=tk.E)
        tree.column("date", width=120)

        for _, row in buyer_items.iterrows():
            sold_date = row.get("date_sold", "")
            if isinstance(sold_date, str) and len(sold_date) > 19:
                sold_date = sold_date[:19]
            tree.insert(
                "",
                tk.END,
                values=(
                    int(row.get(FIELD_UNIQUE_ID, 0)),
                    row.get(FIELD_MODEL, ""),
                    f"\u20b9{row.get(FIELD_PRICE, 0):,.0f}",
                    sold_date,
                ),
            )

        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        ttk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=8)

    def _run_simulation(self) -> None:
        """Open the Price Simulation dialog and apply results to analytics."""
        from gui.simulation import PriceSimulationDialog

        dialog = PriceSimulationDialog(self)
        self.wait_window(dialog)

        result = getattr(dialog, "result", None)
        if result is None:
            return

        analytics = self.app.get("analytics")
        if analytics is None:
            return

        summary = analytics.get_summary(sim_params=result)
        self._kpi_labels["stock_value"].configure(
            text=f"\u20b9{summary.get('total_value', 0):,.0f}"
        )
        self._kpi_labels["profit"].configure(
            text=f"\u20b9{summary.get('est_profit', 0):,.0f}"
        )

        self.app.get("app").show_toast(
            "Simulation Applied", "KPIs updated with simulation values.", "info"
        )

    def _export_pdf(self) -> None:
        """Export detailed analytics report as PDF."""
        reporting = self.app.get("reporting")
        if reporting is None:
            self.app.get("app").show_toast(
                "Export Failed", "Reporting module not available.", "danger"
            )
            return

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        df = getattr(inventory, "inventory_df", None)
        if df is None or df.empty:
            self.app.get("app").show_toast(
                "Export Failed", "No inventory data to export.", "warning"
            )
            return

        # Build summary DataFrame for export
        summary_data = []
        analytics = self.app.get("analytics")
        if analytics is not None:
            summary = analytics.get_summary()
            summary_data.append(
                {"Metric": "Total Items", "Value": summary["total_items"]}
            )
            summary_data.append(
                {"Metric": "Stock Value", "Value": summary["total_value"]}
            )
            summary_data.append(
                {"Metric": "Realized Sales", "Value": summary["realized_sales"]}
            )
            summary_data.append(
                {"Metric": "Realized Profit", "Value": summary["realized_profit"]}
            )

        summary_df = __import__("pandas").DataFrame(summary_data)

        filepath = __import__("tkinter.filedialog").asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf")],
            title="Export Analytics Report",
        )
        if not filepath:
            return

        success = reporting.export(summary_df, "pdf", filepath)
        if success:
            self.app.get("app").show_toast(
                "Export Complete", f"Report saved to {filepath}", "success"
            )
        else:
            self.app.get("app").show_toast(
                "Export Failed", "Could not generate PDF report.", "danger"
            )

    # -- lifecycle -----------------------------------------------------------

    def on_show(self) -> None:
        """Refresh all analytics data when the screen becomes visible."""
        self._refresh_analytics()

    def focus_primary(self) -> None:
        """No primary input on analytics screen."""


# ---------------------------------------------------------------------------
# ActivityLogScreen
# ---------------------------------------------------------------------------


class ActivityLogScreen(BaseScreen):
    """Activity log viewer with filtering and clear functionality.

    Displays timestamped log entries in a Treeview with a limit selector
    and a clear button with confirmation.
    """

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)

        self._log_tree: ttk.Treeview | None = None
        self._limit_var = tk.IntVar(value=100)

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the activity log layout."""
        # Header
        header = self.add_header("Activity Log")
        self._clear_btn = ttk.Button(
            header,
            text="Clear Logs",
            bootstyle="danger-outline",
            command=self._clear_logs,
        )
        self._clear_btn.pack(side=tk.RIGHT, padx=4)

        # Limit selector
        limit_frame = ttk.Frame(header)
        limit_frame.pack(side=tk.RIGHT, padx=8)
        ttk.Label(limit_frame, text="Show last:").pack(side=tk.LEFT, padx=4)
        limit_cb = ttk.Combobox(
            limit_frame,
            textvariable=self._limit_var,
            values=[50, 100, 500],
            state="readonly",
            width=6,
        )
        limit_cb.pack(side=tk.LEFT)
        limit_cb.bind("<<ComboboxSelected>>", lambda e: self._load_logs())

        # Log treeview
        log_columns = ("timestamp", "action", "details")
        self._log_tree = ttk.Treeview(
            self, columns=log_columns, show="headings", height=20
        )
        self._log_tree.heading("timestamp", text="Timestamp")
        self._log_tree.heading("action", text="Action")
        self._log_tree.heading("details", text="Details")
        self._log_tree.column("timestamp", width=160)
        self._log_tree.column("action", width=120)
        self._log_tree.column("details", width=500)

        log_scroll = ttk.Scrollbar(
            self, orient=tk.VERTICAL, command=self._log_tree.yview
        )
        self._log_tree.configure(yscrollcommand=log_scroll.set)
        self._log_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # -- data loading --------------------------------------------------------

    def _load_logs(self) -> None:
        """Load logs from the activity logger and populate the tree."""
        if self._log_tree is None:
            return

        for iid in self._log_tree.get_children():
            self._log_tree.delete(iid)

        logger = self.app.get("activity_logger")
        if logger is None:
            return

        entries = logger.get_entries()
        limit = self._limit_var.get()
        recent = entries[-limit:] if limit > 0 else entries

        for entry in recent:
            ts = entry.get("timestamp", "")
            if len(ts) > 19:
                ts = ts[:19]
            self._log_tree.insert(
                "",
                tk.END,
                values=(
                    ts,
                    entry.get("action", ""),
                    entry.get("details", ""),
                ),
            )

    def _clear_logs(self) -> None:
        """Clear all logs after user confirmation."""
        logger = self.app.get("activity_logger")
        if logger is None:
            return

        confirm = Messagebox.okcancel(
            title="Clear Logs",
            message="Are you sure you want to clear all activity logs? This cannot be undone.",
        )
        if confirm != "OK":
            return

        # ActivityLogger has no clear method; we reset its internal list
        logger._entries = []  # noqa: SLF001 — internal reset
        self._load_logs()
        self.app.get("app").show_toast(
            "Logs Cleared", "All activity logs have been cleared.", "success"
        )

    # -- lifecycle -----------------------------------------------------------

    def on_show(self) -> None:
        """Load logs when the screen becomes visible."""
        self._load_logs()

    def focus_primary(self) -> None:
        """No primary input on activity log screen."""


# ---------------------------------------------------------------------------
# ConflictScreen
# ---------------------------------------------------------------------------


class ConflictScreen(BaseScreen):
    """IMEI conflict list with resolution controls.

    Displays duplicate IMEI entries with their sources and provides
    a merge resolution action per conflict.
    """

    def __init__(self, parent: tk.Misc, app_context: dict[str, Any]) -> None:
        super().__init__(parent, app_context)

        self._conflict_tree: ttk.Treeview | None = None

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the conflict screen layout."""
        # Header
        header = self.add_header("IMEI Conflicts")
        self._refresh_btn = ttk.Button(
            header,
            text="↻ Refresh",
            bootstyle="info-outline",
            command=self._load_conflicts,
        )
        self._refresh_btn.pack(side=tk.RIGHT, padx=8)

        # Conflict treeview
        conflict_columns = ("imei", "model", "ids", "sources")
        self._conflict_tree = ttk.Treeview(
            self, columns=conflict_columns, show="headings", height=15
        )
        self._conflict_tree.heading("imei", text="IMEI")
        self._conflict_tree.heading("model", text="Model")
        self._conflict_tree.heading("ids", text="Item IDs")
        self._conflict_tree.heading("sources", text="Sources")
        self._conflict_tree.column("imei", width=150)
        self._conflict_tree.column("model", width=200)
        self._conflict_tree.column("ids", width=120)
        self._conflict_tree.column("sources", width=250)

        conflict_scroll = ttk.Scrollbar(
            self, orient=tk.VERTICAL, command=self._conflict_tree.yview
        )
        self._conflict_tree.configure(yscrollcommand=conflict_scroll.set)
        self._conflict_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        conflict_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Resolve button
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=8)

        self._resolve_btn = ttk.Button(
            btn_frame,
            text="Resolve Selected (Keep All / Merge)",
            bootstyle="warning",
            command=self._resolve_selected,
        )
        self._resolve_btn.pack(side=tk.RIGHT)

    # -- data loading --------------------------------------------------------

    def _load_conflicts(self) -> None:
        """Load conflicts from the inventory manager."""
        if self._conflict_tree is None:
            return

        for iid in self._conflict_tree.get_children():
            self._conflict_tree.delete(iid)

        inventory = self.app.get("inventory")
        if inventory is None:
            return

        conflicts = getattr(inventory, "conflicts", [])
        if not conflicts:
            return

        for conflict in conflicts:
            ids_str = ", ".join(str(uid) for uid in conflict.get("unique_ids", []))
            sources_str = ", ".join(str(s) for s in conflict.get("sources", []))
            self._conflict_tree.insert(
                "",
                tk.END,
                iid=str(conflict.get("imei", "")),
                values=(
                    conflict.get("imei", ""),
                    conflict.get("model", ""),
                    ids_str,
                    sources_str,
                ),
            )

    # -- interactions --------------------------------------------------------

    def _resolve_selected(self) -> None:
        """Resolve the selected conflict by merging duplicates."""
        if self._conflict_tree is None:
            return

        sel = self._conflict_tree.selection()
        if not sel:
            self.app.get("app").show_toast(
                "No Selection", "Select a conflict to resolve.", "warning"
            )
            return

        imei = sel[0]
        inventory = self.app.get("inventory")
        if inventory is None:
            return

        conflicts = getattr(inventory, "conflicts", [])
        target = None
        for conflict in conflicts:
            if str(conflict.get("imei", "")) == imei:
                target = conflict
                break

        if target is None:
            self.app.get("app").show_toast(
                "Not Found", "Conflict data not found.", "danger"
            )
            return

        rows = target.get("rows", [])
        if len(rows) < 2:
            self.app.get("app").show_toast(
                "No Conflict", "No duplicates to merge.", "info"
            )
            return

        confirm = Messagebox.okcancel(
            title="Merge Conflict",
            message=f"Merge {len(rows)} items with IMEI {imei}?\n"
            f"First item will be kept; others will be hidden.",
        )
        if confirm != "OK":
            return

        keep_id = rows[0].get(FIELD_UNIQUE_ID)
        hide_ids = [r.get(FIELD_UNIQUE_ID) for r in rows[1:]]

        if keep_id is None or not hide_ids:
            self.app.get("app").show_toast(
                "Merge Failed", "Invalid conflict data.", "danger"
            )
            return

        success = inventory.resolve_conflict(
            keep_id=int(keep_id),
            hide_ids=[int(h) for h in hide_ids],
            reason="User merged via conflict screen",
        )

        if success:
            self.app.get("app").show_toast(
                "Conflict Resolved", f"Merged {len(hide_ids)} duplicate(s).", "success"
            )
            self._load_conflicts()
        else:
            self.app.get("app").show_toast(
                "Merge Failed", "Could not resolve conflict.", "danger"
            )

    # -- lifecycle -----------------------------------------------------------

    def on_show(self) -> None:
        """Load conflicts when the screen becomes visible."""
        self._load_conflicts()

    def focus_primary(self) -> None:
        """No primary input on conflict screen."""
