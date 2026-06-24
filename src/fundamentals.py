from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from edgar import get_filings, set_identity, Company
from rich.markup import escape

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Identity persistence
# ---------------------------------------------------------------------------

IDENTITY_FILE = Path.home() / ".finance_terminal_identity.json"


def load_saved_identity() -> dict | None:
    # Return saved identity dict {name, email} or None if not set
    try:
        if IDENTITY_FILE.exists():
            data = json.loads(IDENTITY_FILE.read_text())
            if data.get("name") and data.get("email"):
                return data
    except Exception:
        pass
    return None


def save_identity_to_file(name: str, email: str) -> None:
    # Persist identity to disk so we only ask once.
    IDENTITY_FILE.write_text(json.dumps({"name": name, "email": email}))


def apply_saved_identity() -> bool:
    # Load identity from disk and call edgar.set_identity().
    # Returns True on success, False if no saved identity.

    data = load_saved_identity()
    if data:
        set_identity(f"{data['name']} {data['email']}")
        return True
    return False


# ---------------------------------------------------------------------------
# Identity validation (shared with EdgarClient)
# ---------------------------------------------------------------------------

class EdgarIdentityError(ValueError):
    """Raised when the SEC EDGAR identity is invalid."""


def validate_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) < 2:
        raise EdgarIdentityError("Name must be at least 2 characters.")
    return " ".join(name.split())


def validate_email(email: str) -> str:
    email = email.strip().lower()
    if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", email):
        raise EdgarIdentityError(f"Invalid email address: {email!r}")
    return email


# ---------------------------------------------------------------------------
# EdgarClient
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class EdgarClient:

    # Wrapper builds and sets a SEC-compliant identity string.

    name: str
    email: str
    organization: Optional[str] = None
    auto_set_identity: bool = True
    _identity_is_set: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.name = validate_name(self.name)
        self.email = validate_email(self.email)
        if self.organization:
            self.organization = " ".join(self.organization.strip().split()) or None
        if self.auto_set_identity:
            self.set_identity()

    @property
    def identity(self) -> str:
        parts = [self.name]
        if self.organization:
            parts.append(self.organization)
        parts.append(self.email)
        return " ".join(parts)

    def set_identity(self) -> None:
        try:
            set_identity(self.identity)
            self._identity_is_set = True
        except Exception as exc:
            raise EdgarIdentityError("Unable to set SEC EDGAR identity.") from exc

    def ensure_identity(self) -> None:
        if not self._identity_is_set:
            self.set_identity()

    def get_filings(self, *args: Any, **kwargs: Any) -> Any:
        self.ensure_identity()
        return get_filings(*args, **kwargs)

    def to_dict(self) -> dict[str, Optional[str]]:
        return {"name": self.name, "organization": self.organization, "email": self.email}


# ---------------------------------------------------------------------------
# Statement rendering helpers
# ---------------------------------------------------------------------------

def _period_label(col: str) -> str:
    """Convert a period column name to a short 2-line display label."""
    # "2024-09-28 (FY)"  →  "FY 2024"
    m = re.match(r"(\d{4})-\d{2}-\d{2} \((\w+)\)", str(col))
    if m:
        return f"{m.group(2)} {m.group(1)}"
    # "2024-09-28"  →  "2024"
    m2 = re.match(r"(\d{4})-(\d{2})-\d{2}$", str(col))
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}"
    return str(col)[:10]


def _find_period_cols(df: pd.DataFrame) -> list[str]:
    """Return all period (date) columns from a statement DataFrame."""
    result = []
    for col in df.columns:
        s = str(col)
        if re.match(r"\d{4}-\d{2}-\d{2}", s):
            result.append(col)
    return result


def _fmt_val(val) -> str:
    """
    Format a single numeric value with automatic per-value scaling.
    Large numbers get a B/M/K suffix; small numbers (e.g. EPS) stay as-is.
    """
    if pd.isna(val):
        return "—".rjust(12)
    try:
        v = float(val)
    except (TypeError, ValueError):
        return str(val)[:12].rjust(12)

    neg = v < 0
    av = abs(v)

    if av == 0:
        return "0".rjust(12)
    elif av >= 1e12:
        s = f"{v/1e12:.2f}T"
    elif av >= 1e9:
        s = f"{v/1e9:.2f}B"
    elif av >= 1e6:
        s = f"{v/1e6:.2f}M"
    elif av >= 1e3:
        s = f"{v/1e3:.2f}K"
    elif av >= 1:
        s = f"{v:,.2f}"
    else:
        # Small decimals (EPS fractions, ratios, etc.)
        s = f"{v:.4f}"

    return s.rjust(12)


def render_statement(stmt, title: str) -> str:
    """
    Render an edgartools Statement object as Rich-markup formatted text.
    Returns a multiline string ready for a Textual Static widget.
    """
    try:
        df = stmt.to_dataframe()
    except Exception as exc:
        return f" [bold]{escape(title)}[/bold]\n\n [red]Error: {escape(str(exc))}[/red]"

    if df is None or df.empty:
        return f" [bold]{escape(title)}[/bold]\n\n [dim]No data available.[/dim]"

    period_cols = _find_period_cols(df)
    if not period_cols:
        return f" [bold]{escape(title)}[/bold]\n\n [dim]No period data found.[/dim]"

    # Main line items only (no dimension breakdowns)
    if "dimension" in df.columns:
        main = df[df["dimension"] == False].copy()
    else:
        main = df.copy()

    if main.empty:
        return f" [bold]{escape(title)}[/bold]\n\n [dim]No line items found.[/dim]"

    # Header
    LABEL_W = 44
    COL_W   = 14
    sep = " " + "─" * (LABEL_W + COL_W * len(period_cols) + 2)

    lines: list[str] = [
        f" [bold]{escape(title)}[/bold]",
        sep,
    ]

    # Period header row
    hdr = " " + " " * LABEL_W
    for col in period_cols:
        hdr += _period_label(col).rjust(COL_W)
    lines.append(f" [bold]{escape(hdr)}[/bold]")
    lines.append(sep)

    # Rows of data
    for _, row in main.iterrows():
        label     = str(row.get("label", ""))
        level     = int(row.get("level", 4)) if pd.notna(row.get("level")) else 4
        is_abstr  = bool(row.get("abstract", False))

        indent = "  " * max(0, level - 3)
        full_label = (indent + label)

        if is_abstr:
            lines.append(f"\n [dim]{escape(full_label)}[/dim]")
            continue

        val_str = "".join(_fmt_val(row.get(col)) for col in period_cols)
        label_display = escape(full_label[:LABEL_W].ljust(LABEL_W))
        lines.append(f"  {label_display}{val_str}")

    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# EdgarCompanyStatements
# ---------------------------------------------------------------------------

class EdgarCompanyStatements:
    VALID_FORMS      = {"10K", "10Q"}
    VALID_STATEMENTS = {"income_statement", "balance_sheet", "cash_flow"}

    def __init__(self, ticker: str) -> None:
        self.ticker  = ticker.upper().strip()
        self.company = Company(self.ticker)

    # Fetching companiy info

    def get_filing(self, form_type: str, year: int, quarter: int | None = None):
        form_type = form_type.upper()
        if form_type not in self.VALID_FORMS:
            raise ValueError(f"form_type must be one of {self.VALID_FORMS}")

        if form_type == "10Q":
            if quarter not in {1, 2, 3}:
                raise ValueError("10Q requires quarter to be 1, 2, or 3")
            filings = self.company.get_filings(year=year, quarter=quarter)
            filings = filings.filter(form="10-Q", amendments=True)
        else:
            if quarter is not None:
                raise ValueError("10K does not use quarter")
            filings = self.company.get_filings(year=year)
            filings = filings.filter(form="10-K", amendments=True)

        if len(filings) == 0:
            raise ValueError(f"No {form_type} filings found for {self.ticker} {year}")
        return filings[0].obj()

    def get_statement(
        self,
        form_type: str,
        year: int,
        statement: str,
        quarter: int | None = None,
    ):
        statement = statement.lower()
        if statement not in self.VALID_STATEMENTS:
            raise ValueError(f"statement must be one of {self.VALID_STATEMENTS}")
        filing_obj = self.get_filing(form_type, year, quarter)
        return self._extract_statement(filing_obj, statement)

    # REturning recent 10k as default

    def get_recent_10k(self):
        """Return the most recent 10-K filing object (no year required)."""
        filings = self.company.get_filings(form="10-K")
        if len(filings) == 0:
            raise ValueError(f"No 10-K filings found for {self.ticker}")
        return filings[0].obj()

    def get_recent_10q(self):
        """Return the most recent 10-Q filing object (no year required)."""
        filings = self.company.get_filings(form="10-Q")
        if len(filings) == 0:
            raise ValueError(f"No 10-Q filings found for {self.ticker}")
        return filings[0].obj()

    def get_all_statements(self, filing_obj) -> dict:
        """
        Return a dict with all three statements from an already-fetched filing.
        Keys: 'income_statement', 'balance_sheet', 'cash_flow'
        Values: the raw edgartools statement objects (or None on error).
        """
        stmts: dict = {}
        for key, attr in [
            ("income_statement", "income_statement"),
            ("balance_sheet",    "balance_sheet"),
            ("cash_flow",        "cash_flow_statement"),
        ]:
            try:
                stmts[key] = getattr(filing_obj, attr)
            except Exception:
                stmts[key] = None
        return stmts

    # extracting

    @staticmethod
    def _extract_statement(filing_obj, statement: str):
        if statement == "income_statement":
            return filing_obj.income_statement
        if statement == "balance_sheet":
            return filing_obj.balance_sheet
        return filing_obj.cash_flow_statement
