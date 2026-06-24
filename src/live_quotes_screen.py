"""
Live Quotes Screen — intraday price chart with periodic refresh.

Behaviour
---------
• Market OPEN  ("REGULAR") → loads today's full 5-min candles (09:30 → now ET)
  and auto-refreshes every 5 minutes via set_interval.
• Market CLOSED (any other state) → loads the previous trading-day's 1-h candles
  and shows a static chart (no auto-refresh).

Commands (inside the screen)
-----------------------------
add <TICKER>        Add another series to the chart
remove <TICKER>     Remove a series
back  |  ESC        Return to the main dashboard
"""
from __future__ import annotations

import math
import time
from collections import deque
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import plotext as plt
import yfinance as yf
from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Input, Static
from textual import work

from price import TickerHistoryFetcher

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN  = "09:30"   # zero-padded HH:MM for safe string compare
_MARKET_CLOSE = "16:30"

REFRESH_INTERVAL = 300     # seconds between auto-refreshes (5 min)
SERIES_COLORS    = ["green", "cyan", "yellow", "magenta", "red", "blue"]
MAX_TICKS        = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _market_state(symbol: str) -> str:
    try:
        return yf.Ticker(symbol).info.get("marketState", "CLOSED")
    except Exception:
        return "CLOSED"


def _to_et_naive(series: pd.Series) -> pd.Series:
    """
    Convert a datetime Series to naive ET wall-clock datetimes.

    pandas 2.x changed tz_localize(None) to return UTC-naive values instead of
    local-time-naive values, so we use a strftime roundtrip which is unambiguous
    across all pandas versions.
    """
    if series.dt.tz is not None:
        series = series.dt.tz_convert(_ET)
    # strftime drops tz info and keeps the wall-clock string, then re-parse as naive
    return pd.to_datetime(series.dt.strftime("%Y-%m-%d %H:%M:%S"), format="%Y-%m-%d %H:%M:%S")


def _fetch_history(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = TickerHistoryFetcher(symbol, period=period, interval=interval, repair=False).fetch()
    if df.empty or "datetime" not in df.columns:
        return df
    df["datetime"] = _to_et_naive(df["datetime"])
    return df


def _prev_trading_day_data(symbol: str) -> pd.DataFrame:
    """1-h candles for the most recent complete trading day."""
    df = _fetch_history(symbol, period="5d", interval="1h")
    if df.empty or "datetime" not in df.columns:
        return df
    last_date = df["datetime"].dt.date.max()
    return df[df["datetime"].dt.date == last_date].reset_index(drop=True)


def _fmt_price(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 10_000 else f"{v:,.1f}" if abs(v) >= 1_000 else f"{v:.2f}"


# ---------------------------------------------------------------------------
# Chart widget
# ---------------------------------------------------------------------------

class PlotextChart(Widget):
    """Multi-series intraday price chart. X-axis always spans ET trading hours."""

    DEFAULT_CSS = "PlotextChart { height: 1fr; }"

    def __init__(self, symbols: list[str]) -> None:
        super().__init__()
        self.symbols: list[str] = list(symbols)
        self._series: dict[str, deque] = {s: deque(maxlen=MAX_TICKS) for s in symbols}
        self._start_prices: dict[str, float] = {}
        self._mode: str = "INITIALIZING"
        self._last_refresh: float = 0.0

    def load_history(self, symbol: str, df: pd.DataFrame) -> None:
        if df.empty or "Close" not in df.columns:
            return
        series: deque = deque(maxlen=MAX_TICKS)
        for _, row in df.iterrows():
            ts = row.get("datetime")
            if ts is None or (isinstance(ts, float) and math.isnan(ts)):
                continue
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            try:
                price = float(row["Close"])
            except (ValueError, TypeError):
                continue
            series.append((ts, price))
        if not series:
            return
        self._series[symbol] = series
        self._start_prices[symbol] = series[0][1]
        self.refresh()

    def add_symbol(self, symbol: str) -> None:
        if symbol not in self.symbols:
            self.symbols.append(symbol)
            self._series[symbol] = deque(maxlen=MAX_TICKS)

    def remove_symbol(self, symbol: str) -> None:
        if symbol in self.symbols:
            self.symbols.remove(symbol)
            self._series.pop(symbol, None)
            self._start_prices.pop(symbol, None)
            self.refresh()

    def render(self) -> Text:
        w, h = self.size.width, self.size.height
        if w < 15 or h < 5:
            return Text("Loading chart…")
        active = {s: list(self._series[s]) for s in self.symbols if self._series.get(s)}
        if not active:
            return Text("Waiting for data…")
        return self._build_chart(active, w, h)

    def _build_chart(self, active: dict[str, list], w: int, h: int) -> Text:
        is_live = "LIVE" in self._mode

        title_parts = []
        for sym, data in active.items():
            if not data:
                continue
            cur   = data[-1][1]
            start = self._start_prices.get(sym, cur)
            chg   = (cur - start) / start * 100 if start else 0.0
            sign  = "+" if chg >= 0 else ""
            title_parts.append(f"{sym} ${_fmt_price(cur)} ({sign}{chg:.2f}%)")

        plt.clf()
        plt.theme("dark")
        plt.plotsize(w, h - 1)
        plt.title("   │   ".join(title_parts))
        plt.ylabel("Price ($)")
        plt.date_form("H:M")

        any_plotted = False
        for idx, (sym, data) in enumerate(active.items()):
            if not data:
                continue
            times:  list[str]   = []
            prices: list[float] = []
            for ts, price in data:
                times.append(ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(len(times)))
                prices.append(price)
            if not times:
                continue

            # Anchor x-axis to the full ET trading day window
            if times[0] > _MARKET_OPEN:
                times  = [_MARKET_OPEN] + times
                prices = [prices[0]]    + prices
            if not is_live and times[-1] < _MARKET_CLOSE:
                times  = times  + [_MARKET_CLOSE]
                prices = prices + [prices[-1]]

            plt.plot(times, prices, label=sym, color=SERIES_COLORS[idx % len(SERIES_COLORS)])
            any_plotted = True

        if not any_plotted:
            plt.text("Waiting for data…", x=1, y=1)

        chart_text = Text.from_ansi(plt.build())
        chart_text.append(f"\n[{self._mode}]", style="dim")
        return chart_text


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------

class LiveQuotesScreen(Screen):
    CSS = """
    LiveQuotesScreen {
        layout: vertical;
        background: ansi_default;
        color: #89CFF0;
    }
    Widget, Grid, Horizontal, Vertical, ScrollableContainer {
        background: ansi_default;
    }
    Static, Input {
        background: ansi_default;
    }
    #lq-header {
        height: 3;
        border: double #89CFF0;
        content-align: center middle;
        text-style: bold;
        text-align: center;
    }
    #lq-status {
        height: 2;
        border-top: solid #1B3F5C;
        padding: 0 1;
        content-align: left middle;
        color: #5BAFD6;
    }
    #lq-cmd {
        height: 3;
        border-top: double #89CFF0;
        padding-left: 1;
    }
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, symbols: list[str]) -> None:
        super().__init__()
        self.symbols: list[str] = [s.upper() for s in symbols if s.strip()] or ["AAPL"]
        self._chart: Optional[PlotextChart] = None
        self._market_open: bool = False
        self._alive: bool = True   # set False on unmount to stop in-flight thread workers

    # ------------------------------------------------------------------
    # Layout / lifecycle
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(self._header_str(), id="lq-header")
        self._chart = PlotextChart(self.symbols)
        yield self._chart
        yield Static("Initializing…", id="lq-status")
        yield Input(placeholder="add <TICKER>  remove <TICKER>  back", id="lq-cmd")

    def on_mount(self) -> None:
        self.query_one("#lq-cmd", Input).focus()
        self._initialize()

    def on_unmount(self) -> None:
        self._alive = False
        self.workers.cancel_all()

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _header_str(self) -> str:
        return (
            f"◈ LIVE QUOTES  │  {'  │  '.join(self.symbols)}"
            "  │  add <TICKER>  remove <TICKER>  back"
        )

    def _set_status(self, msg: str) -> None:
        if not self._alive:
            return
        try:
            self.query_one("#lq-status", Static).update(msg)
        except Exception:
            pass

    def _set_header(self) -> None:
        if not self._alive:
            return
        try:
            self.query_one("#lq-header", Static).update(self._header_str())
        except Exception:
            pass

    def _now_et(self) -> str:
        return datetime.now(_ET).strftime("%H:%M:%S")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    @work(thread=True)
    def _initialize(self) -> None:
        """Detect market state, load initial data, set up auto-refresh if open."""
        primary = self.symbols[0]
        state   = _market_state(primary)
        self._market_open = (state == "REGULAR")

        if self._market_open:
            mode = "LIVE  │  auto-refresh 5 min"
        else:
            mode = f"HISTORICAL [{state}]  │  previous trading day"

        if self._chart and self._alive:
            self.app.call_from_thread(lambda: setattr(self._chart, "_mode", mode))

        self._fetch_and_load_all()

        if self._alive:
            status = (
                f"[{state}]  │  Last update: {self._now_et()} ET"
                + ("  │  Next refresh in 5 min" if self._market_open else "")
            )
            self.app.call_from_thread(lambda: self._set_status(status))

        # Schedule periodic refresh on the main thread (only when market open)
        if self._market_open and self._alive:
            self.app.call_from_thread(
                lambda: self.set_interval(REFRESH_INTERVAL, self._auto_refresh)
            )

    def _fetch_and_load_all(self) -> None:
        """Fetch data for every symbol and push to the chart. Checks _alive per symbol."""
        for sym in list(self.symbols):
            if not self._alive:
                return
            df = (
                _fetch_history(sym, period="1d", interval="5m")
                if self._market_open
                else _prev_trading_day_data(sym)
            )
            if not df.empty and self._chart and self._alive:
                self.app.call_from_thread(
                    lambda s=sym, d=df: self._chart.load_history(s, d)
                )

    def _auto_refresh(self) -> None:
        """Called by set_interval every 5 minutes (main thread); kicks off thread worker."""
        if self._alive and self._market_open:
            self._refresh_data()

    @work(thread=True)
    def _refresh_data(self) -> None:
        """Pull fresh 5-min candles for all symbols and update the chart."""
        self._fetch_and_load_all()
        if self._alive:
            self.app.call_from_thread(
                lambda: self._set_status(
                    f"[LIVE]  │  Last update: {self._now_et()} ET"
                    "  │  Next refresh in 5 min"
                )
            )

    @work(thread=True)
    def _load_new_symbol(self, sym: str) -> None:
        if not self._alive:
            return
        df = (
            _fetch_history(sym, period="1d", interval="5m")
            if self._market_open
            else _prev_trading_day_data(sym)
        )
        if not df.empty and self._chart and self._alive:
            self.app.call_from_thread(lambda: self._chart.load_history(sym, df))
        if self._alive:
            self.app.call_from_thread(
                lambda: self._set_status(f"Loaded {sym}  │  Last update: {self._now_et()} ET")
            )

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "lq-cmd":
            raw = event.value.strip()
            event.input.value = ""
            self._dispatch(raw)

    def _dispatch(self, raw: str) -> None:
        if not raw:
            return
        parts = raw.split()
        cmd   = parts[0].lower()

        if cmd in ("back", "quit", "exit"):
            self.app.pop_screen()

        elif cmd == "add" and len(parts) > 1:
            sym = parts[1].upper()
            if sym in self.symbols:
                self._set_status(f"{sym} is already on the chart")
                return
            self.symbols.append(sym)
            if self._chart:
                self._chart.add_symbol(sym)
            self._set_header()
            self._set_status(f"Loading {sym}…")
            self._load_new_symbol(sym)

        elif cmd == "remove" and len(parts) > 1:
            sym = parts[1].upper()
            if sym not in self.symbols:
                self._set_status(f"{sym} is not on the chart")
                return
            self.symbols.remove(sym)
            if self._chart:
                self._chart.remove_symbol(sym)
            self._set_header()
            self._set_status(f"Removed {sym}")

        else:
            self._set_status(
                f"Unknown: '{raw}'  │  add <TICKER>  remove <TICKER>  back"
            )
