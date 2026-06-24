"""
Industry Stock Screener — a dedicated Textual Screen.

Commands
--------
list                    List all available sectors
sector <key>            Show industries in a sector  (e.g. sector technology)
screen <industry>       Screen top stocks by volume  (e.g. screen semiconductors)
top <industry>          Analyst picks / growth / top performers
info <TICKER>           Company summary + officers
back  |  ESC            Return to main dashboard
"""
from __future__ import annotations

import pandas as pd
from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Input, Static
from textual import work

from equity import (
    IndustryPerformanceFetcher,
    IndustryScreener,
    SectorIndustryLookup,
    TickerInfoFetcher,
    TickerOfficersFetcher,
)
from data_configs import SECTOR_INDUSTRY_MAP, SECTOR_KEYS_MAP


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _fmt_vol(v) -> str:
    try:
        v = int(v or 0)
    except (ValueError, TypeError):
        return "-"
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v/1_000:.0f}K"
    return str(v)


def _fmt_cap(v) -> str:
    try:
        v = float(v or 0)
    except (ValueError, TypeError):
        return "-"
    if v >= 1e12:
        return f"{v/1e12:.2f}T"
    if v >= 1e9:
        return f"{v/1e9:.1f}B"
    if v >= 1e6:
        return f"{v/1e6:.0f}M"
    return "-"


def render_screener_table(df: pd.DataFrame, title: str) -> str:
    """Render an IndustryScreener result DataFrame as formatted text."""
    HDR = f" [bold]{escape(title)}[/bold]"
    SEP = " " + "─" * 72
    COL = (
        f" {'SYM':<7} {'NAME':<26} {'PRICE':>8} {'CHG%':>7}"
        f" {'VOLUME':>10} {'MCAP':>10} {'P/E':>6}"
    )
    lines = [HDR, SEP, COL, SEP]

    price_col = next((c for c in ["regularMarketPrice", "price"] if c in df.columns), None)
    chg_col = next(
        (c for c in ["regularMarketChangePercent", "changePercent"] if c in df.columns), None
    )
    vol_col = next(
        (c for c in ["regularMarketVolume", "eodvolume", "volume"] if c in df.columns), None
    )
    cap_col = next((c for c in ["marketCap", "regularMarketCap"] if c in df.columns), None)
    pe_col = next((c for c in ["trailingPE", "forwardPE"] if c in df.columns), None)
    name_col = next((c for c in ["shortName", "longName"] if c in df.columns), None)
    sym_col = "symbol" if "symbol" in df.columns else df.columns[0]

    for _, row in df.head(25).iterrows():
        sym = escape(str(row.get(sym_col, ""))[:7])
        name = escape(str(row.get(name_col, ""))[:25]) if name_col else ""
        try:
            price = float(row.get(price_col, 0) or 0) if price_col else 0.0
            chg = float(row.get(chg_col, 0) or 0) if chg_col else 0.0
            pe_raw = row.get(pe_col) if pe_col else None
            pe = f"{float(pe_raw):.1f}" if pe_raw and float(pe_raw) > 0 else "-"
        except (ValueError, TypeError):
            price, chg, pe = 0.0, 0.0, "-"

        color = "green" if chg >= 0 else "red"
        arrow = "▲" if chg >= 0 else "▼"
        vol_str = _fmt_vol(row.get(vol_col) if vol_col else None)
        cap_str = _fmt_cap(row.get(cap_col) if cap_col else None)

        lines.append(
            f" [{color}]{sym:<7} {name:<26} ${price:>7.2f}"
            f" {arrow}{abs(chg):>5.2f}%"
            f" {vol_str:>10} {cap_str:>10} {pe:>6}[/{color}]"
        )

    return "\n".join(lines)


def render_top_companies(df: pd.DataFrame, industry_name: str) -> str:
    """Render IndustryPerformanceFetcher results grouped by dataset_type."""
    lines = [
        f" [bold]TOP COMPANIES — {escape(industry_name)}[/bold]",
        " " + "─" * 60,
    ]
    labels = {
        "top_companies": "ANALYST PICKS",
        "top_growth": "GROWTH LEADERS",
        "top_performing": "TOP PERFORMERS",
    }
    for dtype, label in labels.items():
        subset = df[df["dataset_type"] == dtype] if "dataset_type" in df.columns else pd.DataFrame()
        if subset.empty:
            continue
        lines += ["", f" [bold]{label}[/bold]", " " + "─" * 40]
        name_col = next((c for c in ["name", "symbol"] if c in subset.columns), None)
        for _, row in subset.head(8).iterrows():
            name = escape(str(row.get(name_col, ""))[:50]) if name_col else ""
            lines.append(f"   {name}")
    return "\n".join(lines)


def render_ticker_info(info_df: pd.DataFrame, officers_df: pd.DataFrame, ticker: str) -> str:
    """Render company info + officers for a ticker."""
    lines = [f" [bold]COMPANY INFO — {escape(ticker)}[/bold]", " " + "─" * 60]

    if not info_df.empty:
        row = info_df.iloc[0]
        lines += [
            f" [dim]Name:[/dim]       {escape(str(row.get('longName', '-')))}",
            f" [dim]Industry:[/dim]   {escape(str(row.get('industry', '-')))}",
            f" [dim]Sector:[/dim]     {escape(str(row.get('sector', '-')))}",
            f" [dim]Website:[/dim]    {escape(str(row.get('website', '-')))}",
            f" [dim]Employees:[/dim]  {row.get('fullTimeEmployees', '-'):,}" if row.get('fullTimeEmployees') else " [dim]Employees:[/dim]  -",
            "",
            " [dim]Business Summary:[/dim]",
        ]
        summary = str(row.get("longBusinessSummary", ""))
        # Wrap summary at ~68 chars
        words, line_buf = summary.split(), []
        for w in words:
            line_buf.append(w)
            if len(" ".join(line_buf)) > 68:
                lines.append(f"   {escape(' '.join(line_buf[:-1]))}")
                line_buf = [w]
        if line_buf:
            lines.append(f"   {escape(' '.join(line_buf))}")

    if not officers_df.empty:
        lines += ["", " [bold]OFFICERS[/bold]", " " + "─" * 60]
        lines.append(f" {'NAME':<30} {'TITLE':<35} {'PAY':>10}")
        lines.append(" " + "─" * 60)
        for _, row in officers_df.head(8).iterrows():
            name = escape(str(row.get("name", ""))[:29])
            title = escape(str(row.get("title", ""))[:34])
            pay = str(row.get("totalPay", "-"))
            try:
                pay_int = int(pay.replace(",", ""))
                pay = f"${pay_int:,}"
            except (ValueError, TypeError):
                pass
            lines.append(f" {name:<30} {title:<35} {pay:>10}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------

class ScreenerScreen(Screen):
    CSS = """
    ScreenerScreen {
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
    #sc-header {
        height: 3;
        border: double #89CFF0;
        content-align: center middle;
        text-style: bold;
        text-align: center;
    }
    #sc-body {
        height: 1fr;
    }
    #sc-sidebar {
        width: 26;
        border: tall #89CFF0;
        padding: 1;
        overflow-y: auto;
        text-align: left;
    }
    #sc-results {
        border: tall #89CFF0;
        width: 1fr;
        overflow-y: auto;
    }
    #sc-results-inner {
        padding: 1;
        text-align: left;
    }
    #sc-status {
        height: 2;
        border-top: solid #1B3F5C;
        padding: 0 1;
        content-align: left middle;
        color: #5BAFD6;
        text-align: left;
    }
    #sc-cmd {
        height: 3;
        border-top: double #89CFF0;
        padding-left: 1;
    }
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self) -> None:
        super().__init__()
        self._active_sector: str = ""
        self._base_lookup_df: pd.DataFrame = pd.DataFrame()
        self._full_lookup_df: pd.DataFrame | None = None
        self._lookup_obj: SectorIndustryLookup | None = None

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(
            "◈ INDUSTRY SCREENER  │  list  sector <key>  screen <industry>"
            "  top <industry>  info <TICKER>  back",
            id="sc-header",
        )
        with Horizontal(id="sc-body"):
            yield Static(self._render_sidebar(), id="sc-sidebar")
            with ScrollableContainer(id="sc-results"):
                yield Static(self._render_intro(), id="sc-results-inner")
        yield Static(
            "Building lookup…  │  list  sector <key>  screen <industry>"
            "  top <industry>  info <TICKER>  back",
            id="sc-status",
        )
        yield Input(placeholder="Enter screener command...", id="sc-cmd")

    def on_mount(self) -> None:
        self.query_one("#sc-cmd", Input).focus()
        # Build base lookup synchronously (pure dict ops — instant)
        self._lookup_obj = SectorIndustryLookup(SECTOR_INDUSTRY_MAP, SECTOR_KEYS_MAP)
        self._base_lookup_df = self._lookup_obj._build_base_lookup()
        # Fetch full lookup (yfinance industry keys) in background
        self._fetch_full_lookup()

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    def _render_sidebar(self) -> str:
        lines = [" [bold]SECTORS[/bold]", " " + "─" * 20]
        for key, name in SECTOR_KEYS_MAP.items():
            if key == self._active_sector:
                lines.append(f" [reverse green] {name} [/reverse green]")
            else:
                lines.append(f"  {name}")
        return "\n".join(lines)

    def _render_intro(self) -> str:
        return "\n".join([
            " [bold]INDUSTRY SCREENER[/bold]",
            " " + "─" * 60,
            "",
            "  [dim]list[/dim]               List all sectors",
            "  [dim]sector <key>[/dim]       Show industries in a sector",
            "                          e.g.  sector technology",
            "  [dim]screen <industry>[/dim]  Screen top stocks by volume",
            "                          e.g.  screen semiconductors",
            "  [dim]top <industry>[/dim]     Analyst picks + growth leaders",
            "                          e.g.  top semiconductors",
            "  [dim]info <TICKER>[/dim]      Company profile + officers",
            "                          e.g.  info NVDA",
            "  [dim]back[/dim]               Return to main dashboard",
        ])

    # ------------------------------------------------------------------
    # Update helpers (always on main thread or async worker)
    # ------------------------------------------------------------------

    def _set_results(self, content: str, focus_scroll: bool = False) -> None:
        self.query_one("#sc-results-inner", Static).update(content)
        container = self.query_one("#sc-results", ScrollableContainer)
        container.scroll_home(animate=False)
        if focus_scroll:
            container.focus()

    def _set_status(self, msg: str) -> None:
        hint = "list  sector <key>  screen <industry>  top <industry>  info <TICKER>  back"
        self.query_one("#sc-status", Static).update(f"{escape(msg)}  │  {hint}")

    def _set_sidebar(self) -> None:
        self.query_one("#sc-sidebar", Static).update(self._render_sidebar())

    # ------------------------------------------------------------------
    # Background: build full lookup with yfinance industry keys
    # ------------------------------------------------------------------

    @work(thread=True)
    def _fetch_full_lookup(self) -> None:
        try:
            df = self._lookup_obj.fetch()  # type: ignore[union-attr]
            self._full_lookup_df = df
            self.app.call_from_thread(
                lambda: self._set_status("Ready  │  list  sector <key>  screen <industry>  top <industry>  info <TICKER>  back")
            )
        except Exception as exc:
            self.app.call_from_thread(
                lambda: self._set_status(f"Partial lookup (top unavailable): {exc}")
            )

    # ------------------------------------------------------------------
    # Industry name resolution
    # ------------------------------------------------------------------

    def _resolve_industry(self, query: str) -> str | None:
        """Return the canonical industry name matching *query* (fuzzy)."""
        q = query.lower().strip()
        all_industries = [
            ind for inds in SECTOR_INDUSTRY_MAP.values() for ind in inds
        ]
        for ind in all_industries:
            if ind.lower() == q:
                return ind
        for ind in all_industries:
            if q in ind.lower():
                return ind
        return None

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.app.pop_screen()
            return
        # When the results scroll container has focus (after an `info` load),
        # redirect any printable character back to the command input so the
        # user can type the next command without manually clicking/tabbing.
        focused = self.focused
        if focused is not None and focused.id == "sc-results":
            if event.character and event.character.isprintable():
                cmd_input = self.query_one("#sc-cmd", Input)
                cmd_input.focus()
                cmd_input.value += event.character
                event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "sc-cmd":
            raw = event.value.strip()
            event.input.value = ""
            self._dispatch(raw)

    def _dispatch(self, raw: str) -> None:
        if not raw:
            return
        parts = raw.split()
        cmd = parts[0].lower()

        if cmd in ("back", "quit", "exit"):
            self.app.pop_screen()

        elif cmd == "list":
            self._cmd_list()

        elif cmd == "sector":
            key = parts[1].lower() if len(parts) > 1 else ""
            self._cmd_sector(key)

        elif cmd == "screen" and len(parts) > 1:
            industry_input = " ".join(parts[1:])
            self._set_status(f"Screening '{industry_input}'…")
            self._cmd_screen(industry_input)

        elif cmd == "top" and len(parts) > 1:
            industry_input = " ".join(parts[1:])
            self._set_status(f"Fetching top companies for '{industry_input}'…")
            self._cmd_top(industry_input)

        elif cmd == "info" and len(parts) > 1:
            ticker = parts[1].upper()
            self._set_status(f"Loading info for {ticker}…")
            self._cmd_info(ticker)

        else:
            self._set_status(f"Unknown command: '{raw}'")

    # ------------------------------------------------------------------
    # Sync commands (instant, no I/O)
    # ------------------------------------------------------------------

    def _cmd_list(self) -> None:
        lines = [" [bold]AVAILABLE SECTORS[/bold]", " " + "─" * 52]
        for key, name in SECTOR_KEYS_MAP.items():
            count = len(SECTOR_INDUSTRY_MAP.get(name, []))
            lines.append(
                f"   [green]{key:<26}[/green]  {escape(name)} ({count} industries)"
            )
        self._set_results("\n".join(lines))
        self._set_status("Type  sector <key>  to see industries")

    def _cmd_sector(self, key: str) -> None:
        # Fuzzy match the sector key
        matched_key = key if key in SECTOR_KEYS_MAP else next(
            (k for k in SECTOR_KEYS_MAP if key in k), None
        )
        if not matched_key:
            self._set_status(f"Sector '{key}' not found — type 'list' to see all")
            return

        self._active_sector = matched_key
        self._set_sidebar()

        sector_name = SECTOR_KEYS_MAP[matched_key]
        industries = SECTOR_INDUSTRY_MAP.get(sector_name, [])
        lines = [
            f" [bold]SECTOR: {escape(sector_name)}[/bold]",
            " " + "─" * 52,
        ]
        for i, ind in enumerate(industries, 1):
            lines.append(f"   {i:>2}.  {escape(ind)}")
        lines += ["", " [dim]screen <industry> to screen stocks[/dim]"]
        self._set_results("\n".join(lines))
        self._set_status(f"Sector: {sector_name} — {len(industries)} industries")

    # ------------------------------------------------------------------
    # Async-threaded commands (network I/O)
    # ------------------------------------------------------------------

    @work(thread=True)
    def _cmd_screen(self, industry_input: str) -> None:
        industry_name = self._resolve_industry(industry_input)
        if not industry_name:
            self.app.call_from_thread(
                lambda: self._set_status(f"'{industry_input}' not found — try sector <key> to browse")
            )
            return

        # Prefer the full lookup (has real yfinance industry_key) when ready;
        # fall back to the base lookup (key derived from display name).
        lookup_df = (
            self._full_lookup_df
            if self._full_lookup_df is not None
            else self._base_lookup_df
        )

        try:
            screener = IndustryScreener(lookup_df, count=25, size=25)
            df = screener.fetch_industry(industry_name)
            if df.empty:
                content = f"[dim]No results for {escape(industry_name)}[/dim]"
            else:
                content = render_screener_table(df, f"SCREENER: {industry_name}")
            self.app.call_from_thread(lambda: self._set_results(content))
            self.app.call_from_thread(
                lambda: self._set_status(f"Screened: {industry_name} ({len(df)} stocks)")
            )
        except Exception as exc:
            self.app.call_from_thread(lambda: self._set_status(f"Error: {escape(str(exc)[:80])}"))

    @work(thread=True)
    def _cmd_top(self, industry_input: str) -> None:
        if self._full_lookup_df is None:
            self.app.call_from_thread(
                lambda: self._set_status("Full lookup still building — please wait and retry")
            )
            return

        industry_name = self._resolve_industry(industry_input)
        if not industry_name:
            self.app.call_from_thread(
                lambda: self._set_status(f"'{industry_input}' not found")
            )
            return

        # Find the industry_key for the resolved name
        mask = self._full_lookup_df["industry_name"].str.lower() == industry_name.lower()
        rows = self._full_lookup_df[mask].dropna(subset=["industry_key"])
        if rows.empty:
            self.app.call_from_thread(
                lambda: self._set_status(f"No industry key for '{industry_name}' — yfinance lookup may be incomplete")
            )
            return

        industry_key = rows.iloc[0]["industry_key"]
        try:
            perf = IndustryPerformanceFetcher(
                self._full_lookup_df, industry_keys=[industry_key]
            )
            df = perf.fetch()
            if df.empty:
                content = f"[dim]No top company data for {escape(industry_name)}[/dim]"
            else:
                content = render_top_companies(df, industry_name)
            self.app.call_from_thread(lambda: self._set_results(content))
            self.app.call_from_thread(lambda: self._set_status(f"Top companies: {industry_name}"))
        except Exception as exc:
            self.app.call_from_thread(lambda: self._set_status(f"Error: {escape(str(exc)[:80])}"))

    @work(thread=True)
    def _cmd_info(self, ticker: str) -> None:
        try:
            info_df = TickerInfoFetcher(ticker).fetch()
            officers_df = TickerOfficersFetcher(ticker).fetch()
            content = render_ticker_info(info_df, officers_df, ticker)
            self.app.call_from_thread(lambda: self._set_results(content, focus_scroll=True))
            self.app.call_from_thread(lambda: self._set_status(f"Info: {ticker}  │  ↑↓ or j/k to scroll  │  type a command to refocus"))
        except Exception as exc:
            self.app.call_from_thread(lambda: self._set_status(f"Error: {escape(str(exc)[:80])}"))
