"""A sheet column's kind — what its values are, checked at import and on every typed edit (Arc SH, SH-1).

**A kind is taken only when every value reads back as it was written** (the lossless rule): a zip code written
``01037`` is not a Number, because ``1037`` is not what was written; a review score ``4`` is. A value that does not fit
a kind leaves the column Text, and the import says how many did not fit — a value is never dropped to make a kind fit.

**Date and Date & time are kept apart.** Comparing a delivery's *time* with an estimated *date* held at midnight counted
1,292 Olist orders delivered on their estimated day as late (the arc doc §1); by calendar day 6,535 were late, not
7,827. A column whose every value is midnight is offered as a Date, and compared by day.

Kinds: Text, Number, Money (in the dataset's currency), Date, Date & time, Choice (few values, each a chip), Yes/No,
Email, and Link (a key into another sheet — SH-7).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

TEXT = "text"
NUMBER = "number"
MONEY = "money"
DATE = "date"
DATETIME = "datetime"
CHOICE = "choice"
YESNO = "yesno"
EMAIL = "email"
LINK = "link"

KINDS = (TEXT, NUMBER, MONEY, DATE, DATETIME, CHOICE, YESNO, EMAIL, LINK)

LABELS = {TEXT: "Text", NUMBER: "Number", MONEY: "Money", DATE: "Date", DATETIME: "Date & time",
          CHOICE: "Choice", YESNO: "Yes/No", EMAIL: "Email", LINK: "Link"}

#: A Choice holds at most this many values; more and it is Text.
MAX_CHOICES = 12

#: Column names that suggest an amount of money, when every value is one (at most two decimals).
_MONEY_WORDS = re.compile(r"(?i)(price|value|amount|revenue|cost|paid|payment|total|freight|fee|sales|spend|refund)")

# What each kind accepts, as written. Anchored, so a value fits only whole.
_INT = r"-?(0|[1-9][0-9]*)"
_NUM = r"-?(0|[1-9][0-9]*)(\.[0-9]+)?"
_MONEY = r"-?(0|[1-9][0-9]*)(\.[0-9]{1,2})?"
_DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
_MIDNIGHT = r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T]00:00(:00(\.0+)?)?"
_DATETIME = r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]+)?)?"
_EMAIL = r"[^@\s]+@[^@\s]+\.[^@\s]+"


def duck_type(kind: str, *, integer: bool = False) -> str:
    """The DuckDB type a column of this kind is held in."""
    return {NUMBER: "BIGINT" if integer else "DOUBLE", MONEY: "DECIMAL(18,2)", DATE: "DATE", DATETIME: "TIMESTAMP",
            YESNO: "BOOLEAN"}.get(kind, "VARCHAR")


@dataclass
class Fit:
    """How a column's values fit each kind: of ``filled`` values, how many did not read back as each kind."""
    filled: int = 0
    empty: int = 0
    misfits: dict[str, int] = field(default_factory=dict)
    integer: bool = False
    midnight: bool = False
    distinct: int = 0
    values: list[tuple[str, int]] = field(default_factory=list)    # the most common, with counts
    first: Optional[str] = None

    def fits(self, kind: str) -> bool:
        return kind == TEXT or self.misfits.get(kind, 1) == 0

    def offered(self) -> list[str]:
        """The kinds a person may choose for this column: those every value fits, Text always."""
        return [k for k in (TEXT, NUMBER, MONEY, DATE, DATETIME, CHOICE, YESNO, EMAIL) if self.fits(k)]


def fit_sql(column_sql: str) -> str:
    """One aggregate over a column of raw text that counts, for each kind, the filled values that do NOT fit it."""
    v = f"NULLIF(TRIM({column_sql}), '')"
    def miss(pattern: str, extra: str = "") -> str:
        cond = f"regexp_full_match({v}, '{pattern}')" + (f" AND {extra}" if extra else "")
        return f"COUNT({v}) FILTER (WHERE NOT ({cond}))"
    return ", ".join([
        f"COUNT({v}) AS filled",
        f"COUNT(*) - COUNT({v}) AS empty",
        f"{miss(_INT)} AS int_miss",
        f"{miss(_NUM)} AS num_miss",
        f"{miss(_MONEY)} AS money_miss",
        f"{miss(_DATE, f'TRY_CAST({v} AS DATE) IS NOT NULL')} AS date_miss",
        f"{miss(_MIDNIGHT, f'TRY_CAST({v} AS TIMESTAMP) IS NOT NULL')} AS midnight_miss",
        f"{miss(_DATETIME, f'TRY_CAST({v} AS TIMESTAMP) IS NOT NULL')} AS datetime_miss",
        f"COUNT({v}) FILTER (WHERE lower({v}) NOT IN ('true', 'false', 'yes', 'no')) AS yesno_miss",
        f"{miss(_EMAIL)} AS email_miss",
        f"COUNT(DISTINCT {v}) AS distinct_n",
    ])


def fit_from_row(row: dict, values: list[tuple[str, int]], first: Optional[str]) -> Fit:
    """A `Fit` from one row of `fit_sql`'s aggregate and the column's most common values."""
    filled = int(row["filled"] or 0)
    distinct = int(row["distinct_n"] or 0)
    misfits = {
        NUMBER: int(row["num_miss"] or 0),
        MONEY: int(row["money_miss"] or 0),
        DATE: min(int(row["date_miss"] or 0), int(row["midnight_miss"] or 0)),
        DATETIME: int(row["datetime_miss"] or 0),
        YESNO: int(row["yesno_miss"] or 0),
        EMAIL: int(row["email_miss"] or 0),
        # A Choice is few values among many rows: a column of distinct ids is not one, however few rows it has.
        CHOICE: 0 if (filled >= 2 and 0 < distinct <= MAX_CHOICES and distinct * 2 <= filled) else max(1, filled),
    }
    if filled == 0:
        # An empty column fits every kind; it is offered as Text, the kind that claims nothing.
        misfits = {k: 0 for k in misfits}
    return Fit(filled=filled, empty=int(row["empty"] or 0), misfits=misfits,
               integer=int(row["int_miss"] or 0) == 0 and filled > 0,
               midnight=int(row["midnight_miss"] or 0) == 0 and int(row["date_miss"] or 0) > 0 and filled > 0,
               distinct=distinct, values=values, first=first)


def suggest(name: str, fit: Fit) -> str:
    """The kind an import offers first. Only a kind every value fits is ever suggested."""
    if fit.filled == 0:
        return TEXT
    if fit.fits(NUMBER):
        return MONEY if fit.fits(MONEY) and not fit.integer and _MONEY_WORDS.search(name or "") else NUMBER
    if fit.fits(DATE):
        return DATE
    if fit.fits(DATETIME):
        return DATETIME
    if fit.fits(YESNO):
        return YESNO
    if fit.fits(EMAIL):
        return EMAIL
    if fit.fits(CHOICE):
        return CHOICE
    return TEXT


def cast_sql(kind: str, raw_sql: str, *, integer: bool = False) -> str:
    """The SQL that turns a column of raw text into its kind's type. Only used on a column every value fits."""
    v = f"NULLIF(TRIM({raw_sql}), '')"
    if kind == NUMBER:
        return f"CAST({v} AS {'BIGINT' if integer else 'DOUBLE'})"
    if kind == MONEY:
        return f"CAST({v} AS DECIMAL(18,2))"
    if kind == DATE:
        return f"CAST(CAST({v} AS TIMESTAMP) AS DATE)"
    if kind == DATETIME:
        return f"CAST({v} AS TIMESTAMP)"
    if kind == YESNO:
        return f"(lower({v}) IN ('true', 'yes'))::BOOLEAN"
    return v


class ValueRefused(ValueError):
    """A typed value that does not read as its column's kind — said in a sentence a person can act on."""


def parse(kind: str, raw: Any, *, integer: bool = False, column: str = "this column") -> Any:
    """A value a person typed, as its column's kind holds it — JSON-safe, so it is kept in the edit layer as written.
    Empty clears the cell (None). Raises `ValueRefused` with a sentence when it does not read as the kind."""
    if raw is None:
        return None
    if isinstance(raw, bool) and kind == YESNO:
        return raw
    text = str(raw).strip()
    if text == "":
        return None
    if kind == NUMBER:
        cleaned = text.replace(",", "")
        if not re.fullmatch(_NUM, cleaned) and not re.fullmatch(r"-?[0-9]*\.[0-9]+", cleaned):
            raise ValueRefused(f"{column} holds numbers, and {text!r} does not read as one")
        if integer:
            if not re.fullmatch(_INT, cleaned):
                raise ValueRefused(f"{column} holds whole numbers, and {text!r} is not one")
            return int(cleaned)
        number = float(cleaned)
        return int(number) if number.is_integer() and "." not in cleaned else number
    if kind == MONEY:
        cleaned = re.sub(r"^[^\d\-.]+", "", text).replace(",", "").strip()
        try:
            amount = Decimal(cleaned)
        except InvalidOperation:
            raise ValueRefused(f"{column} holds amounts of money, and {text!r} does not read as one") from None
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueRefused(f"{column} holds amounts to the cent, and {text!r} has more decimals than that")
        return f"{amount.quantize(Decimal('0.01'))}"
    if kind == DATE:
        # a date written with a midnight time is the date (a file's dates often are: the arc doc §1)
        if not (re.fullmatch(_DATE, text) or re.fullmatch(_MIDNIGHT, text)):
            _not_date(text, column)
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            raise ValueRefused(f"{column} holds dates, and {text!r} is not a date that exists") from None
    if kind == DATETIME:
        if not re.fullmatch(_DATETIME, text) and not re.fullmatch(_DATE, text):
            raise ValueRefused(f"{column} holds a date and a time, written 2018-10-17 14:30, and {text!r} is not")
        try:
            when = datetime.fromisoformat(text.replace("T", " "))
        except ValueError:
            raise ValueRefused(f"{column} holds a date and a time, and {text!r} is not one that exists") from None
        return when.isoformat(sep=" ", timespec="seconds")
    if kind == YESNO:
        word = text.lower()
        if word in ("true", "yes", "y", "1"):
            return True
        if word in ("false", "no", "n", "0"):
            return False
        raise ValueRefused(f"{column} is Yes/No, and {text!r} is neither")
    if kind == EMAIL:
        if not re.fullmatch(_EMAIL, text):
            raise ValueRefused(f"{column} holds email addresses, and {text!r} is not one")
        return text
    return text


def _not_date(text: str, column: str):
    raise ValueRefused(f"{column} holds dates, written 2018-10-17, and {text!r} is not written that way")
