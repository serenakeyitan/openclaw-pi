"""Dip Buyer strategy — long-only, buys on dips below rolling average."""

import sys
from pathlib import Path
from datetime import datetime, timezone

VENV_SITE = Path(__file__).resolve().parent.parent / ".venv/lib"
for p in sorted(VENV_SITE.glob("python*/site-packages")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from strategies.base import Strategy


class DipBuyerStrategy(Strategy):
    """Long-only dip buyer: watches price, buys when it dips below a
    short-term rolling average. Never sells — hold until manually closed
    or strategy is stopped.

    Designed for crypto (BTCUSD, ETHUSD) but works on any symbol.

    Config keys
    -----------
    symbol : str              — ticker (e.g. "BTC/USD" for crypto, "AAPL" for stock)
    window : int              — rolling average window in samples (default 20)
    dip_pct : float           — buy when price is this % below avg (default 1.0)
    buy_amount : float        — notional $ per dip buy (default 100)
    max_buys : int            — max dip buys before stopping (default 10)
    cooldown_seconds : int    — min seconds between buys (default 60)
    duration_minutes : int    — auto-pause after N minutes (0 = no limit)
    """

    def __init__(self, name: str, config: dict, capital_allocated: float = 0.0):
        super().__init__(name, "dip_buyer", config, capital_allocated)
        self.config.setdefault("symbol", "BTC/USD")
        self.config.setdefault("window", 20)
        self.config.setdefault("dip_pct", 1.0)
        self.config.setdefault("buy_amount", 100)
        self.config.setdefault("max_buys", 10)
        self.config.setdefault("cooldown_seconds", 60)
        # Runtime state
        self.config.setdefault("price_samples", [])
        self.config.setdefault("buy_count", 0)
        self.config.setdefault("last_buy_time", None)
        self.config.setdefault("buys", [])  # list of {time, price, amount}

    def initialize(self, api):
        self.status = "initializing"
        symbol = self.config["symbol"]

        price = self._get_latest_price(api, symbol)
        if price is None:
            self.status = "error"
            self.error_msg = f"Cannot get price for {symbol}"
            return

        self.config["price_samples"] = [price]
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.status = "active"

    def tick(self, api):
        if self.status != "active":
            return

        self.last_tick = datetime.now(timezone.utc).isoformat()
        symbol = self.config["symbol"]
        window = self.config["window"]
        dip_pct = self.config["dip_pct"]
        buy_amount = self.config["buy_amount"]
        max_buys = self.config["max_buys"]
        cooldown = self.config["cooldown_seconds"]

        current_price = self._get_latest_price(api, symbol)
        if current_price is None:
            return

        # Record price
        samples = self.config["price_samples"]
        samples.append(current_price)
        if len(samples) > window * 3:
            samples = samples[-(window * 3):]
        self.config["price_samples"] = samples

        # Need enough samples
        if len(samples) < window:
            return

        # Rolling average
        recent = samples[-window:]
        avg = sum(recent) / len(recent)
        buy_threshold = avg * (1 - dip_pct / 100)

        # Check if we should buy
        buy_count = self.config.get("buy_count", 0)
        if buy_count >= max_buys:
            return

        # Cooldown check
        last_buy = self.config.get("last_buy_time")
        if last_buy:
            try:
                last_dt = datetime.fromisoformat(last_buy)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if elapsed < cooldown:
                    return
            except (ValueError, TypeError):
                pass

        # DIP signal: price below threshold
        if current_price <= buy_threshold:
            # Use gtc for crypto, day for stocks
            tif = "gtc" if "/" in symbol else "day"
            cid = self.tag_order_id(f"dip{buy_count}")
            order = self._submit_order(
                api,
                symbol=symbol,
                notional=buy_amount,
                side="buy",
                type="market",
                time_in_force=tif,
                client_order_id=cid,
            )
            if order:
                self.total_fills += 1
                now = datetime.now(timezone.utc).isoformat()
                self.config["buy_count"] = buy_count + 1
                self.config["last_buy_time"] = now
                self.config["buys"].append({
                    "time": now,
                    "price": current_price,
                    "amount": buy_amount,
                })

        # Update unrealized PnL
        # Alpaca uses the symbol without "/" for positions
        pos_symbol = symbol.replace("/", "")
        try:
            pos = api.get_position(pos_symbol)
            self.unrealized_pnl = float(pos.unrealized_pl)
            self.capital_used = abs(float(pos.cost_basis))
        except Exception:
            pass

    def stop(self, api):
        """Sell position and stop."""
        symbol = self.config["symbol"]
        pos_symbol = symbol.replace("/", "")
        pos_qty = self._get_position_qty(api, pos_symbol)
        if pos_qty > 0:
            tif = "gtc" if "/" in symbol else "day"
            try:
                api.submit_order(
                    symbol=symbol,
                    qty=pos_qty,
                    side="sell",
                    type="market",
                    time_in_force=tif,
                )
            except Exception:
                pass
        super().stop(api)

    def get_positions(self) -> dict:
        samples = self.config.get("price_samples", [])
        window = self.config["window"]
        avg = None
        if len(samples) >= window:
            recent = samples[-window:]
            avg = round(sum(recent) / len(recent), 2)

        return {
            "symbol": self.config["symbol"],
            "buy_count": self.config.get("buy_count", 0),
            "max_buys": self.config["max_buys"],
            "rolling_avg": avg,
            "samples": len(samples),
            "dip_pct": self.config["dip_pct"],
            "last_buy_time": self.config.get("last_buy_time"),
            "buys": self.config.get("buys", [])[-5:],  # last 5
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DipBuyerStrategy":
        obj = cls(
            name=data["name"],
            config=data.get("config", {}),
            capital_allocated=data.get("capital_allocated", 0.0),
        )
        obj.status = data.get("status", "pending")
        obj.realized_pnl = data.get("realized_pnl", 0.0)
        obj.unrealized_pnl = data.get("unrealized_pnl", 0.0)
        obj.total_fills = data.get("total_fills", 0)
        obj.orders = list(data.get("orders", []))
        obj.created_at = data.get("created_at", "")
        obj.started_at = data.get("started_at", "")
        obj.duration_minutes = data.get("duration_minutes", 0)
        obj.last_tick = data.get("last_tick", "")
        obj.error_msg = data.get("error_msg", "")
        obj.capital_used = data.get("capital_used", 0.0)
        return obj
