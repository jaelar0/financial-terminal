"""
Finance Terminal — Bloomberg-style TUI dashboard.

Dashboard commands
------------------
chart <TICKER>          Load chart for that ticker  (e.g. chart AAPL)
news <TICKER>           Load news panel for that ticker
watch add <TICKER>      Add ticker to the watchlist
watch remove <TICKER>   Remove ticker from the watchlist
period <period>         Change chart period (1d 5d 1mo 3mo 6mo 1y 2y ytd max)
live <T1> [T2 …]        Open Live Quotes screen (stream or prev-day 1 h)
screener                Open the Industry Screener screen
refresh                 Force-refresh all panels
?  |  help              Show command reference
q  |  quit              Exit
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import yfinance as yf
from rich.markup import escape
from textual.app import App, ComposeResult
from textual.theme import Theme
from textual.widgets import Input, Static
from textual import work

from terminallayout import FinanceTerminal
from price import TickerHistoryFetcher
from datetime import date as date_type
from news import EconomicCalendarFetcher, TickerEarningsDatesFetcher, TickerNewsFetcher
from live_quotes_screen import LiveQuotesScreen
from screener_screen import ScreenerScreen
from fundamentals_screen import FundamentalsScreen


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WATCHLIST = ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN", "META", "TSLA"]
INDICES = ["SPY", "QQQ", "DIA", "IWM"]

VALID_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "ytd", "max"}


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------

@dataclass
class AppState:
    current_symbol: str = "AAPL"
    chart_period: str = "3mo"
    chart_interval: str = "1d"


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _fetch_quick_price(symbol: str) -> dict:
    """Fetch last price and daily % change for one symbol (blocking)."""
    try:
        fi = yf.Ticker(symbol).fast_info
        price = float(fi.last_price or 0)
        prev = float(fi.previous_close or price)
        chg = (price - prev) / prev * 100 if prev else 0.0
        return {"price": price, "change_pct": chg}
    except Exception:
        return {"price": 0.0, "change_pct": 0.0}


# ---------------------------------------------------------------------------
# Render functions
# ---------------------------------------------------------------------------

def render_price_chart(
    df, ticker: str, earnings_str: str = "", width: int = 52, height: int = 12
) -> str:
    """Render a filled-area ASCII chart from a price DataFrame."""
    if df.empty:
        return f"[dim]No price data for {escape(ticker)}[/dim]"

    closes = df["Close"].dropna().tolist()
    if len(closes) < 2:
        return "[dim]Insufficient data[/dim]"

    closes = closes[-width:]
    n = len(closes)
    min_p, max_p = min(closes), max(closes)
    rng = (max_p - min_p) or 1.0

    is_up = closes[-1] >= closes[0]
    color = "green" if is_up else "red"
    arrow = "▲" if is_up else "▼"
    pct = (closes[-1] - closes[0]) / closes[0] * 100
    period = df["period"].iloc[0] if "period" in df.columns else ""

    chart_lines: list[str] = []
    for r in range(height):
        val = min_p + rng * (height - 1 - r) / (height - 1)
        if r == 0:
            lbl = f"{max_p:>8.2f} ┤"
        elif r == height - 1:
            lbl = f"{min_p:>8.2f} ┤"
        elif r == height // 2:
            lbl = f"{val:>8.2f} ┤"
        else:
            lbl = f"         │"

        bar = "".join(
            "█" if r >= (height - 1 - round((p - min_p) / rng * (height - 1))) else " "
            for p in closes
        )
        chart_lines.append(f"{lbl}[{color}]{bar}[/{color}]")

    x_axis = "         └" + "─" * n

    date_row = ""
    if "datetime" in df.columns:
        dates = df["datetime"].dropna().dt.strftime("%m/%d").tolist()[-n:]
        if len(dates) >= 2:
            date_row = f"          {dates[0]:<{n // 2}}{dates[-1]:>{n - n // 2}}"

    header = (
        f" [{color}]{escape(ticker)}  ${closes[-1]:.2f}  "
        f"{arrow} {pct:+.2f}%[/{color}]  [dim]{escape(period)}[/dim]"
    )
    earnings_line = (
        f" [dim]Next Earnings: {escape(earnings_str)}[/dim]" if earnings_str else ""
    )
    lines = [header]
    if earnings_line:
        lines.append(earnings_line)
    lines.extend([*chart_lines, x_axis, date_row])
    return "\n".join(lines)


def render_watchlist(prices: dict[str, dict]) -> str:
    """Render the watchlist panel from the shared prices dict."""
    lines = [" [bold]WATCHLIST[/bold]", " " + "─" * 32]
    for sym in WATCHLIST:
        data = prices.get(sym, {})
        price = data.get("price", 0.0)
        chg = data.get("change_pct", 0.0)
        color = "green" if chg >= 0 else "red"
        arrow = "▲" if chg >= 0 else "▼"
        lines.append(
            f" [{color}]{escape(sym):<6} ${price:>8.2f}  {arrow} {chg:+.2f}%[/{color}]"
        )
    return "\n".join(lines)


def render_market_overview(prices: dict[str, dict], econ_df) -> str:
    """Render market overview (indices + economic calendar)."""
    lines = [" [bold]INDICES[/bold]", " " + "─" * 32]
    for sym in INDICES:
        data = prices.get(sym, {})
        price = data.get("price", 0.0)
        chg = data.get("change_pct", 0.0)
        color = "green" if chg >= 0 else "red"
        arrow = "▲" if chg >= 0 else "▼"
        display = sym.lstrip("^")
        lines.append(
            f" [{color}]{escape(display):<6} ${price:>8.2f}  {arrow} {chg:+.2f}%[/{color}]"
        )

    lines += ["", " [bold]ECONOMIC EVENTS (TODAY)[/bold]", " " + "─" * 32]
    if econ_df is not None and not econ_df.empty:
        for _, row in econ_df.head(7).iterrows():
            name = escape(str(row.get("event_name", ""))[:26])
            t = escape(str(row.get("event_time_ampm", "")))
            lines.append(f" {t:<11} {name}")
    else:
        lines.append(" [dim]No events today[/dim]")

    return "\n".join(lines)


def render_news(news_df, symbol: str) -> str:
    """Render the news panel for a given symbol."""
    lines = [f" [bold]NEWS: {escape(symbol)}[/bold]", " " + "─" * 44]

    if news_df is None or news_df.empty:
        lines.append(" [dim]No news found[/dim]")
        return "\n".join(lines)

    for _, row in news_df.head(9).iterrows():
        title = escape(str(row.get("title", ""))[:54])
        provider = escape(str(row.get("provider_name", "") or ""))
        pub = escape(str(row.get("published_date", "") or ""))
        lines.append(f" [bold]{title}[/bold]")
        lines.append(f"   [dim]{provider}  {pub}[/dim]")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

_TRANSPARENT_THEME = Theme(
    name="finance-transparent",
    primary="#89CFF0",
    secondary="#5BAFD6",
    background="ansi_default",
    surface="ansi_default",
    panel="ansi_default",
    boost="ansi_default",
    foreground="#89CFF0",
    dark=True,
)


class Terminal(App):
    CSS_PATH = "styles.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.state = AppState()
        self._prices: dict[str, dict] = {}
        self._econ_df = None
        # Cached price DataFrames keyed by symbol (for earnings re-render)
        self._last_df: dict[str, object] = {}
        # Next earnings date string keyed by symbol
        self._earnings: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def _header_text(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d  %H:%M")
        return f"◈ FINANCE TERMINAL  │  {self.state.current_symbol}  │  {now}"

    def compose(self) -> ComposeResult:
        yield FinanceTerminal(
            Static(self._header_text(), id="header-bar"),
            Static("[dim]Loading…[/dim]", id="watchlist"),
            Static("[dim]Loading…[/dim]", id="price-chart"),
            Static("[dim]Loading…[/dim]", id="market-overview"),
            Static("[dim]Loading…[/dim]", id="news-feed"),
            Static(
                "Ready  │  chart <T>  news <T>  watch add/remove <T>  period <p>  live <T>  screener  fundamentals <T>  refresh  quit",
                id="status-bar",
            ),
            Input(placeholder="Enter command or ticker…", id="command-bar"),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self.register_theme(_TRANSPARENT_THEME)
        self.theme = "finance-transparent"
        self.query_one("#command-bar", Input).focus()
        self._load_all()
        self.set_interval(300, self._periodic_refresh)  # full refresh every 5 min

    def _periodic_refresh(self) -> None:
        self._load_watchlist()
        self._load_market()
        self._update_header()

    # ------------------------------------------------------------------
    # Panel helpers (always called on main/async thread — no call_from_thread)
    # ------------------------------------------------------------------

    def _update_header(self) -> None:
        self.query_one("#header-bar", Static).update(self._header_text())

    def _update_status(self, msg: str) -> None:
        hint = "chart <T>  news <T>  watch add/remove <T>  period <p>  live <T>  screener  fundamentals <T>  refresh  quit"
        self.query_one("#status-bar", Static).update(f"{escape(msg)}  │  {hint}")

    def _repaint_watchlist(self) -> None:
        self.query_one("#watchlist", Static).update(render_watchlist(self._prices))

    def _repaint_market(self) -> None:
        self.query_one("#market-overview", Static).update(
            render_market_overview(self._prices, self._econ_df)
        )

    # ------------------------------------------------------------------
    # Thread workers — initial / periodic data loads
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        sym = self.state.current_symbol
        self._load_chart(sym, self.state.chart_period, self.state.chart_interval)
        self._load_watchlist()
        self._load_market()
        self._load_news(sym)
        self._load_earnings(sym)

    # ------------------------------------------------------------------
    # Panel update helpers called on the main thread via call_from_thread
    # ------------------------------------------------------------------

    def _update_panel(self, panel_id: str, content: str) -> None:
        self.query_one(panel_id, Static).update(content)

    # ------------------------------------------------------------------
    # Thread workers
    # ------------------------------------------------------------------

    @work(thread=True)
    def _load_chart(self, symbol: str, period: str, interval: str) -> None:
        import pandas as pd
        df = TickerHistoryFetcher(symbol, period=period, interval=interval, repair=False).fetch()
        self._last_df[symbol] = df  # cache for earnings re-render
        chart = render_price_chart(df, symbol, self._earnings.get(symbol, ""))
        self.call_from_thread(lambda: self._update_panel("#price-chart", chart))

    @work(thread=True)
    def _load_earnings(self, symbol: str) -> None:
        """Fetch next/most-recent earnings date and refresh the chart header."""
        try:
            df = TickerEarningsDatesFetcher(symbol, limit=10).fetch()
            if df.empty or "earnings_date" not in df.columns:
                return
            today = date_type.today()
            # Prefer the next upcoming date; fall back to the most recent past date
            upcoming = df[
                df["earnings_date"].apply(
                    lambda d: hasattr(d, "year") and d >= today
                )
            ]
            if not upcoming.empty:
                row = upcoming.iloc[-1]  # earliest future date (df sorted desc)
                self._earnings[symbol] = str(row["earnings_date"])
            else:
                self._earnings[symbol] = str(df.iloc[0]["earnings_date"]) + " (last)"
        except Exception:
            return
        # Re-render chart if we have cached price data for this symbol
        cached_df = self._last_df.get(symbol)
        if cached_df is not None and symbol == self.state.current_symbol:
            chart = render_price_chart(cached_df, symbol, self._earnings.get(symbol, ""))
            self.call_from_thread(lambda: self._update_panel("#price-chart", chart))

    @work(thread=True)
    def _load_watchlist(self) -> None:
        for sym in WATCHLIST:
            data = _fetch_quick_price(sym)
            # Only overwrite if no live price present (don't downgrade live → polled)
            if not self._prices.get(sym, {}).get("live"):
                self._prices[sym] = data
        self.call_from_thread(self._repaint_watchlist)

    @work(thread=True)
    def _load_market(self) -> None:
        for sym in INDICES:
            data = _fetch_quick_price(sym)
            if not self._prices.get(sym, {}).get("live"):
                self._prices[sym] = data
        try:
            self._econ_df = EconomicCalendarFetcher().fetch()
        except Exception:
            self._econ_df = None
        self.call_from_thread(self._repaint_market)

    @work(thread=True)
    def _load_news(self, symbol: str) -> None:
        df = TickerNewsFetcher(symbol, count=15).fetch()
        text = render_news(df, symbol)
        self.call_from_thread(lambda: self._update_panel("#news-feed", text))

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def on_key(self, event) -> None:
        if event.key == "q":
            self.exit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "command-bar":
            raw = event.value.strip()
            event.input.value = ""
            self._run_command(raw)

    def _run_command(self, raw: str) -> None:
        if not raw:
            return

        parts = raw.split()
        cmd = parts[0].lower()

        if cmd in ("quit", "exit"):
            self.exit()

        elif cmd in ("help", "?"):
            self._update_status(
                "Commands: chart <T>  news <T>  watch add/remove <T>  period <1d…>  live <T>  screener  fundamentals <T>  refresh  quit"
            )

        elif cmd == "chart" and len(parts) > 1:
            symbol = parts[1].upper()
            self.state.current_symbol = symbol
            self._update_header()
            self._update_status(f"Loading chart for {symbol}…")
            self._load_chart(symbol, self.state.chart_period, self.state.chart_interval)
            self._load_earnings(symbol)

        elif cmd == "watch" and len(parts) > 2:
            action = parts[1].lower()
            symbol = parts[2].upper()
            if action == "add":
                if symbol in WATCHLIST:
                    self._update_status(f"{symbol} is already on the watchlist")
                else:
                    WATCHLIST.append(symbol)
                    self._update_status(f"Added {symbol} to watchlist")
                    self._load_watchlist()
            elif action == "remove":
                if symbol not in WATCHLIST:
                    self._update_status(f"{symbol} is not on the watchlist")
                else:
                    WATCHLIST.remove(symbol)
                    self._repaint_watchlist()
                    self._update_status(f"Removed {symbol} from watchlist")
            else:
                self._update_status("Usage: watch add <TICKER>  |  watch remove <TICKER>")

        elif cmd == "live" and len(parts) > 1:
            # Support: live AAPL   or   live quotes AAPL MSFT
            tickers = [
                p.upper() for p in parts[1:]
                if p.lower() != "quotes"   # allow optional "quotes" keyword
            ]
            if tickers:
                self.push_screen(LiveQuotesScreen(tickers))
            else:
                self._update_status("Usage: live <TICKER> [TICKER2 …]")

        elif cmd == "screener":
            self.push_screen(ScreenerScreen())

        elif cmd == "fundamentals" and len(parts) > 1:
            symbol = parts[1].upper()
            self.push_screen(FundamentalsScreen(ticker=symbol))

        elif cmd == "fundamentals":
            # No ticker given — open with current symbol
            self.push_screen(FundamentalsScreen(ticker=self.state.current_symbol))

        elif cmd == "refresh":
            self._update_status("Refreshing all data…")
            self._update_header()
            self._load_all()

        elif cmd == "period" and len(parts) > 1:
            p = parts[1].lower()
            if p in VALID_PERIODS:
                self.state.chart_period = p
                self._update_status(f"Chart period → {p}")
                sym = self.state.current_symbol
                self._load_chart(sym, p, self.state.chart_interval)
                if sym not in self._earnings:
                    self._load_earnings(sym)
            else:
                self._update_status(
                    f"Invalid period '{p}'. Valid: {', '.join(sorted(VALID_PERIODS))}"
                )

        elif cmd == "news" and len(parts) > 1:
            symbol = parts[1].upper()
            self._update_status(f"Loading news for {symbol}…")
            self._load_news(symbol)

        else:
            self._update_status(
                f"Unknown command '{raw}'  │  try: chart <T>  news <T>  watch add/remove <T>  period <p>  live <T>  screener  fundamentals <T>  help"
            )


if __name__ == "__main__":
    Terminal().run()
