"""
Analytics module for StockMate.

Provides inventory summaries, profit calculations, and demand forecasting
based on the current state of the inventory DataFrame and item history.
"""

import datetime
from collections import Counter
from typing import Any

import pandas as pd

from .constants import (
    STATUS_IN,
    STATUS_OUT,
    FIELD_MODEL,
    FIELD_PRICE,
    FIELD_PRICE_ORIGINAL,
    FIELD_STATUS,
    FIELD_UNIQUE_ID,
)
from .inventory import InventoryManager


class AnalyticsManager:
    """Compute business analytics from the current inventory state."""

    def __init__(self, inventory_manager: InventoryManager) -> None:
        self._inventory = inventory_manager

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self, sim_params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a dict of aggregate inventory metrics.

        When *sim_params* is provided the summary is calculated against
        hypothetical cost/price adjustments instead of the real values.

        Parameters
        ----------
        sim_params:
            Keys: ``target`` ("cost" | "price"), ``base`` (float),
            ``modifier`` (float multiplier), ``flat_adjust`` (float additive).
        """
        df = self._inventory.get_inventory()

        if df.empty:
            return self._empty_summary()

        working = self._apply_simulation(df, sim_params)

        in_stock = working[working[FIELD_STATUS] == STATUS_IN]
        out_stock = working[working[FIELD_STATUS] == STATUS_OUT]

        total_value = float(in_stock[FIELD_PRICE].sum()) if not in_stock.empty else 0.0
        total_cost = (
            float(in_stock[FIELD_PRICE_ORIGINAL].sum()) if not in_stock.empty else 0.0
        )

        realized_profit = 0.0
        if not out_stock.empty:
            cost_col = FIELD_PRICE_ORIGINAL
            sold_col = FIELD_PRICE
            realized_profit = float((out_stock[sold_col] - out_stock[cost_col]).sum())

        status_counts = dict(working[FIELD_STATUS].value_counts())

        top_models = self._compute_top_models(in_stock)
        supplier_dist = self._compute_supplier_dist(in_stock)

        return {
            "total_items": len(in_stock),
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "est_profit": round(total_value - total_cost, 2),
            "realized_sales": len(out_stock),
            "realized_profit": round(realized_profit, 2),
            "status_counts": status_counts,
            "top_models": top_models,
            "supplier_dist": supplier_dist,
        }

    # ------------------------------------------------------------------
    # Demand forecast
    # ------------------------------------------------------------------

    def get_demand_forecast(self) -> list[dict[str, Any]]:
        """Estimate sales velocity and days-of-stock remaining per model.

        Uses history entries with action ``STATUS_CHANGE`` to ``OUT`` to
        derive a weekly sales rate for each model.
        """
        df = self._inventory.get_inventory()

        if df.empty:
            return []

        # Current stock per model
        in_stock = df[df[FIELD_STATUS] == STATUS_IN]
        stock_counts: Counter = Counter(in_stock[FIELD_MODEL].values)

        # Sales per model from history
        sales_per_model: Counter = Counter()
        all_items = self._inventory.db.get_all_items()

        for item in all_items:
            if item.get("status") != STATUS_OUT:
                continue
            history = self._inventory.db.get_metadata(item["id"])
            # We need to query history table directly for velocity calc
            model = item.get(FIELD_MODEL, "Unknown Model")
            sales_per_model[model] += 1

        # Calculate velocity from history timestamps
        velocity = self._calculate_velocity(all_items)

        now = datetime.datetime.now()
        forecasts: list[dict[str, Any]] = []

        all_models = set(stock_counts.keys()) | set(velocity.keys())

        for model in sorted(all_models):
            in_stock_count = stock_counts.get(model, 0)
            sold_per_week = velocity.get(model, 0.0)

            if sold_per_week > 0:
                days_remaining = (in_stock_count / sold_per_week) * 7.0
            else:
                days_remaining = float("inf") if in_stock_count > 0 else 0.0

            if in_stock_count == 0:
                status_flag = "OUT_OF_STOCK"
            elif in_stock_count < 5:
                status_flag = "LOW_STOCK"
            else:
                status_flag = "OK"

            forecasts.append(
                {
                    "model": model,
                    "in_stock": in_stock_count,
                    "sold_per_week": round(sold_per_week, 2),
                    "days_remaining": round(days_remaining, 1)
                    if days_remaining != float("inf")
                    else -1,
                    "status_flag": status_flag,
                }
            )

        return forecasts

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_summary() -> dict[str, Any]:
        """Return a zeroed summary when no inventory data exists."""
        return {
            "total_items": 0,
            "total_value": 0.0,
            "total_cost": 0.0,
            "est_profit": 0.0,
            "realized_sales": 0,
            "realized_profit": 0.0,
            "status_counts": {},
            "top_models": [],
            "supplier_dist": {},
        }

    @staticmethod
    def _apply_simulation(
        df: pd.DataFrame, sim_params: dict[str, Any] | None
    ) -> pd.DataFrame:
        """Return a copy of *df* with simulated price/cost adjustments applied."""
        if sim_params is None:
            return df

        target = sim_params.get("target", "price")
        base = float(sim_params.get("base", 0))
        modifier = float(sim_params.get("modifier", 1.0))
        flat_adjust = float(sim_params.get("flat_adjust", 0))

        working = df.copy()
        col = FIELD_PRICE if target == "price" else FIELD_PRICE_ORIGINAL

        if col not in working.columns:
            return working

        # Apply multiplier then flat adjustment relative to base
        mask = working[col] > 0
        working.loc[mask, col] = (
            working.loc[mask, col] * modifier
            + (working.loc[mask, col] - base) * flat_adjust
        )

        return working

    @staticmethod
    def _compute_top_models(in_stock: pd.DataFrame) -> list[tuple[str, int]]:
        """Return the top 10 models by count in stock."""
        if in_stock.empty:
            return []
        counts = in_stock[FIELD_MODEL].value_counts()
        return [(str(model), int(count)) for model, count in counts.head(10).items()]

    @staticmethod
    def _compute_supplier_dist(in_stock: pd.DataFrame) -> dict[str, int]:
        """Return a mapping of supplier → item count."""
        if in_stock.empty:
            return {}
        return dict(in_stock["supplier"].value_counts())

    @staticmethod
    def _calculate_velocity(
        all_items: list[dict[str, Any]],
    ) -> dict[str, float]:
        """Calculate weekly sales velocity per model from history data."""
        # Import here to avoid circular dependency at module level
        import sqlite3

        # We need to pull history from the DB to calculate time-based velocity
        # Get all items with their sold dates and compute time span
        sold_items = [
            item
            for item in all_items
            if item.get("status") == STATUS_OUT and item.get("sold_date")
        ]

        if not sold_items:
            # Fall back to simple count-based estimate
            model_counts: Counter = Counter()
            for item in all_items:
                if item.get("status") == STATUS_OUT:
                    model_counts[item.get(FIELD_MODEL, "Unknown Model")] += 1
            # Assume 4 weeks of data as default window
            return {model: count / 4.0 for model, count in model_counts.items()}

        # Parse dates and compute time window
        dates = []
        model_sold: dict[str, list[datetime.datetime]] = {}

        for item in sold_items:
            sold_date_str = item.get("sold_date", "")
            try:
                sold_date = datetime.datetime.fromisoformat(sold_date_str)
                dates.append(sold_date)
                model = item.get(FIELD_MODEL, "Unknown Model")
                model_sold.setdefault(model, []).append(sold_date)
            except (ValueError, TypeError):
                continue

        if not dates:
            return {}

        # Calculate time span in weeks
        earliest = min(dates)
        latest = max(dates)
        span_days = (latest - earliest).total_seconds() / 86400.0
        span_weeks = max(span_days / 7.0, 1.0)  # At least 1 week

        velocity: dict[str, float] = {}
        for model, sold_dates in model_sold.items():
            velocity[model] = len(sold_dates) / span_weeks

        return velocity
