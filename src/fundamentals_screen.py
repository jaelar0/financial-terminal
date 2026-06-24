# ---------------------------------------------------------------------------
# Fundamentals Screen — SEC EDGAR financial statements via edgartools.

# Commands

# ticker <T>          Load a new ticker  (e.g.  ticker MSFT)
# 10k <year>          Load annual 10-K   (e.g.  10k 2024)
# 10q <year> <q>      Load quarterly 10-Q (e.g. 10q 2024 1)
# income              Show income statement
# balance             Show balance sheet
# cashflow            Show cash flow statement
# back  |  ESC        Return to main dashboard

# Edgar Identity

# The SEC requires an identity string before making EDGAR requests.
# On first use you will be prompted for your name and e-mail.
# This is saved to ~/.finance_terminal_identity.json and never asked again.
# ---------------------------------------------------------------------------

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Input, Static
from textual import work

from fundamentals import (
    EdgarCompanyStatements,
    EdgarIdentityError,
    apply_saved_identity,
    render_statement,
    save_identity_to_file,
    validate_email,
    validate_name,
)


# ---------------
# Screen
# ---------------

class FundamentalsScreen(Screen):
    CSS = """
    FundamentalsScreen {
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
    #fn-header {
        height: 3;
        border: double #89CFF0;
        content-align: center middle;
        text-style: bold;
        text-align: center;
    }
    #fn-body {
        height: 1fr;
    }
    #fn-sidebar {
        width: 28;
        border: tall #89CFF0;
        padding: 1;
        overflow-y: auto;
        text-align: left;
    }
    #fn-results {
        border: tall #89CFF0;
        width: 1fr;
        overflow-y: auto;
    }
    #fn-results-inner {
        padding: 1;
        text-align: left;
    }
    #fn-status {
        height: 2;
        border-top: solid #1B3F5C;
        padding: 0 1;
        content-align: left middle;
        color: #5BAFD6;
        text-align: left;
    }
    #fn-cmd {
        height: 3;
        border-top: double #89CFF0;
        padding-left: 1;
    }
    """

    BINDINGS = [("escape", "go_back", "Back")]

    # ------------------------------------------------------------------
    # Setup stage: None → "name" → "email" → None (done)
    # ------------------------------------------------------------------

    def __init__(self, ticker: str = "AAPL") -> None:
        super().__init__()
        self._ticker          = ticker.upper().strip()
        self._filing_label    = ""        # e.g. "10-K 2024"
        self._active_stmt     = ""        # "income_statement" | "balance_sheet" | "cash_flow"
        self._statements: dict = {}       # keyed by the three statement names
        self._identity_ready  = False

        # Identity setup state machine
        self._setup_stage  = None         # None | "name" | "email"
        self._pending_name = ""

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(
            "◈ FUNDAMENTALS  │  ticker <T>  10k <year>  10q <year> <q>"
            "  income  balance  cashflow  back",
            id="fn-header",
        )
        with Horizontal(id="fn-body"):
            yield Static(self._render_sidebar(), id="fn-sidebar")
            with ScrollableContainer(id="fn-results"):
                yield Static(self._render_intro(), id="fn-results-inner")
        yield Static("Initialising…", id="fn-status")
        yield Input(placeholder="Enter command…", id="fn-cmd")

    def on_mount(self) -> None:
        self.query_one("#fn-cmd", Input).focus()
        self._boot()

    # ------------------------------------------------------------------
    # Boot: check identity, then auto-load ticker
    # ------------------------------------------------------------------

    def _boot(self) -> None:
        if apply_saved_identity():
            self._identity_ready = True
            self._set_status(
                f"Identity loaded  │  Loading {self._ticker}…"
            )
            self._load_ticker(self._ticker)
        else:
            self._enter_setup()

    # ------------------------------------------------------------------
    # Identity setup flow
    # ------------------------------------------------------------------

    def _enter_setup(self) -> None:
        self._setup_stage = "name"
        self._set_results(
            "\n".join([
                " [bold]SEC EDGAR IDENTITY SETUP[/bold]",
                " " + "─" * 60,
                "",
                " The SEC requires a name and e-mail before fetching filings.",
                " This is stored in [bold]~/.finance_terminal_identity.json[/bold]",
                " and will not be asked again.",
                "",
                " [bold]Step 1 of 2[/bold] — Type your [bold]full name[/bold] in the",
                " command bar below and press Enter.",
            ])
        )
        self._set_status("Identity required  │  Enter your full name and press Enter")
        cmd = self.query_one("#fn-cmd", Input)
        cmd.placeholder = "Your full name…"

    def _handle_setup_input(self, raw: str) -> None:
        if self._setup_stage == "name":
            try:
                self._pending_name = validate_name(raw)
            except EdgarIdentityError as exc:
                self._set_status(f"Error: {exc}  │  Try again")
                return
            self._setup_stage = "email"
            self._set_results(
                "\n".join([
                    " [bold]SEC EDGAR IDENTITY SETUP[/bold]",
                    " " + "─" * 60,
                    "",
                    f" Name recorded: [bold]{escape(self._pending_name)}[/bold]",
                    "",
                    " [bold]Step 2 of 2[/bold] — Type your [bold]e-mail address[/bold]",
                    " in the command bar below and press Enter.",
                ])
            )
            self._set_status("Enter your e-mail address and press Enter")
            self.query_one("#fn-cmd", Input).placeholder = "your@email.com…"

        elif self._setup_stage == "email":
            try:
                email = validate_email(raw)
            except EdgarIdentityError as exc:
                self._set_status(f"Error: {exc}  │  Try again")
                return

            try:
                from edgar import set_identity as _set_id
                _set_id(f"{self._pending_name} {email}")
                save_identity_to_file(self._pending_name, email)
            except Exception as exc:
                self._set_status(f"Failed to set identity: {escape(str(exc)[:80])}")
                return

            self._setup_stage    = None
            self._identity_ready = True
            self.query_one("#fn-cmd", Input).placeholder = "Enter command…"
            self._set_status(
                f"Identity saved  │  Loading {self._ticker}…"
            )
            self._load_ticker(self._ticker)

    # ---------------
    # Sidebar
    # ---------------

    def _render_sidebar(self) -> str:
        stmts = [
            ("income_statement", "income"),
            ("balance_sheet",    "balance"),
            ("cash_flow",        "cashflow"),
        ]
        lines = [
            " [bold]TICKER[/bold]",
            f"  [green]{escape(self._ticker)}[/green]",
            "",
            " [bold]FILING[/bold]",
            f"  {escape(self._filing_label) if self._filing_label else '[dim]none loaded[/dim]'}",
            "",
            " [bold]STATEMENTS[/bold]",
            " " + "─" * 22,
        ]
        for key, cmd in stmts:
            loaded = key in self._statements and self._statements[key] is not None
            active = key == self._active_stmt
            bullet = "►" if active else " "
            if active:
                lines.append(f" [bold green]{bullet} {cmd}[/bold green]")
            elif loaded:
                lines.append(f" [white]{bullet} {cmd}[/white]")
            else:
                lines.append(f" [dim]{bullet} {cmd}[/dim]")
        lines += [
            "",
            " [bold]COMMANDS[/bold]",
            " " + "─" * 22,
            "  ticker <T>",
            "  10k <year>",
            "  10q <year> <q>",
            "  income / balance",
            "  cashflow",
            "  back",
        ]
        return "\n".join(lines)

    def _render_intro(self) -> str:
        return "\n".join([
            " [bold]FUNDAMENTALS[/bold]",
            " " + "─" * 60,
            "",
            "  [dim]ticker <T>[/dim]       Load a company      e.g.  ticker MSFT",
            "  [dim]10k <year>[/dim]       Annual report       e.g.  10k 2024",
            "  [dim]10q <year> <q>[/dim]   Quarterly report    e.g.  10q 2024 1",
            "",
            "  Once a filing is loaded:",
            "  [dim]income[/dim]           Show income statement",
            "  [dim]balance[/dim]          Show balance sheet",
            "  [dim]cashflow[/dim]         Show cash flow statement",
            "",
            "  [dim]back[/dim]             Return to main dashboard",
            "",
            f"  Current ticker: [bold green]{escape(self._ticker)}[/bold green]",
        ])

    # ------------------------------------
    # Update helpers (safely)
    # ------------------------------------

    def _set_results(self, content: str, focus_scroll: bool = False) -> None:
        self.query_one("#fn-results-inner", Static).update(content)
        container = self.query_one("#fn-results", ScrollableContainer)
        container.scroll_home(animate=False)
        if focus_scroll:
            container.focus()

    def _set_status(self, msg: str) -> None:
        hint = "ticker <T>  10k <year>  10q <year> <q>  income  balance  cashflow  back"
        self.query_one("#fn-status", Static).update(f"{escape(msg)}  │  {hint}")

    def _refresh_sidebar(self) -> None:
        self.query_one("#fn-sidebar", Static).update(self._render_sidebar())

    # ---------------------
    # Command dispatch
    # ---------------------

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.app.pop_screen()
            return
        # If the scroll container has focus, redirect printable keys to cmd bar
        focused = self.focused
        if focused is not None and focused.id == "fn-results":
            if event.character and event.character.isprintable():
                cmd_input = self.query_one("#fn-cmd", Input)
                cmd_input.focus()
                cmd_input.value += event.character
                event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "fn-cmd":
            return
        raw = event.value.strip()
        event.input.value = ""

        if self._setup_stage is not None:
            self._handle_setup_input(raw)
            return

        self._dispatch(raw)

    def _dispatch(self, raw: str) -> None:
        if not raw:
            return
        parts = raw.split()
        cmd   = parts[0].lower()

        if cmd in ("back", "quit", "exit"):
            self.app.pop_screen()

        elif cmd == "ticker" and len(parts) > 1:
            sym = parts[1].upper()
            self._ticker     = sym
            self._filing_label = ""
            self._statements  = {}
            self._active_stmt = ""
            self._refresh_sidebar()
            self._set_results(self._render_intro())
            self._set_status(f"Loading {sym}…")
            self._load_ticker(sym)

        elif cmd == "10k" and len(parts) > 1:
            try:
                year = int(parts[1])
            except ValueError:
                self._set_status("Usage: 10k <year>  e.g.  10k 2024")
                return
            self._set_status(f"Loading 10-K {year} for {self._ticker}…")
            self._load_filing("10K", year)

        elif cmd == "10q" and len(parts) > 2:
            try:
                year    = int(parts[1])
                quarter = int(parts[2])
            except ValueError:
                self._set_status("Usage: 10q <year> <quarter>  e.g.  10q 2024 1")
                return
            if quarter not in (1, 2, 3):
                self._set_status("Quarter must be 1, 2, or 3")
                return
            self._set_status(f"Loading 10-Q {year} Q{quarter} for {self._ticker}…")
            self._load_filing("10Q", year, quarter)

        elif cmd == "income":
            self._show_statement("income_statement", "Income Statement")

        elif cmd == "balance":
            self._show_statement("balance_sheet", "Balance Sheet")

        elif cmd == "cashflow":
            self._show_statement("cash_flow", "Cash Flow Statement")

        else:
            self._set_status(
                f"Unknown command: '{raw}'  │  try: ticker <T>  10k <year>  income  balance  cashflow  back"
            )

    # --------------------
    # Statement display
    # --------------------

    def _show_statement(self, key: str, title: str) -> None:
        if not self._statements:
            self._set_status("No filing loaded — use 10k <year> or 10q <year> <q> first")
            return
        stmt = self._statements.get(key)
        if stmt is None:
            self._set_status(f"{title} not available in this filing")
            return
        self._active_stmt = key
        self._refresh_sidebar()
        self._set_status(f"Rendering {title}…")
        # Render in a thread (can be slow for large statements)
        self._render_in_thread(stmt, f"{title} — {self._ticker}  ({self._filing_label})")

    @work(thread=True)
    def _render_in_thread(self, stmt, title: str) -> None:
        content = render_statement(stmt, title)
        self.app.call_from_thread(lambda: self._set_results(content, focus_scroll=True))
        self.app.call_from_thread(
            lambda: self._set_status(
                f"{escape(title)} loaded  │  ↑↓ / Page Up/Down to scroll  │  type to refocus command bar"
            )
        )
        self.app.call_from_thread(self._refresh_sidebar)

    # --------------------------
    # Background data loading
    # --------------------------

    @work(thread=True)
    def _load_ticker(self, sym: str) -> None:
        """Load the most recent 10-K for a ticker on a background thread."""
        try:
            client = EdgarCompanyStatements(sym)
            filing = client.get_recent_10k()
            stmts  = client.get_all_statements(filing)

            # Determine filing year from income statement period columns
            label = _infer_filing_label(stmts, "10-K")

            self._ticker      = sym
            self._statements  = stmts
            self._filing_label = label
            self._active_stmt = "income_statement"

            content = render_statement(
                stmts["income_statement"],
                f"Income Statement — {sym}  ({label})",
            )
            self.app.call_from_thread(lambda: self._set_results(content, focus_scroll=True))
            self.app.call_from_thread(lambda: self._set_status(
                f"Loaded {sym} {label}  │  income  balance  cashflow to switch"
            ))
            self.app.call_from_thread(self._refresh_sidebar)

        except Exception as exc:
            self.app.call_from_thread(
                lambda: self._set_status(f"Error loading {sym}: {escape(str(exc)[:100])}")
            )

    @work(thread=True)
    def _load_filing(self, form_type: str, year: int, quarter: int | None = None) -> None:
        """Load a specific filing by year (and optionally quarter)."""
        try:
            client = EdgarCompanyStatements(self._ticker)
            filing = client.get_filing(form_type, year, quarter)
            stmts  = client.get_all_statements(filing)

            if form_type == "10Q":
                label = f"10-Q {year} Q{quarter}"
            else:
                label = f"10-K {year}"

            self._statements   = stmts
            self._filing_label = label
            self._active_stmt  = "income_statement"

            content = render_statement(
                stmts["income_statement"],
                f"Income Statement — {self._ticker}  ({label})",
            )
            self.app.call_from_thread(lambda: self._set_results(content, focus_scroll=True))
            self.app.call_from_thread(lambda: self._set_status(
                f"Loaded {self._ticker} {label}  │  income  balance  cashflow to switch"
            ))
            self.app.call_from_thread(self._refresh_sidebar)

        except Exception as exc:
            self.app.call_from_thread(
                lambda: self._set_status(f"Error: {escape(str(exc)[:100])}")
            )


# ---------------------------------------
# Helper - Guessing Statements from keyword
# ---------------------------------------

def _infer_filing_label(stmts: dict, form_type: str) -> str:
    """Guess a filing label like '10-K 2024' from the loaded statements."""
    import re as _re
    for key in ("income_statement", "cash_flow", "balance_sheet"):
        stmt = stmts.get(key)
        if stmt is None:
            continue
        try:
            df   = stmt.to_dataframe()
            cols = [c for c in df.columns if _re.match(r"\d{4}", str(c))]
            if cols:
                year = str(cols[0])[:4]
                return f"{form_type} {year}"
        except Exception:
            continue
    return form_type
