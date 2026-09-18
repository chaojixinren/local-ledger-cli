"""SQLite storage; amounts are always integer cents."""

import calendar
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .validation import (
    DEFAULT_DATABASE,
    ValidationError,
    database_path,
    parse_amount,
    parse_category,
    parse_date,
    parse_month,
)


@dataclass(frozen=True)
class Entry:
    id: int
    entry_date: str
    kind: str
    category: str
    amount_cents: int
    note: str


@dataclass(frozen=True)
class Summary:
    income_cents: int
    expense_cents: int

    @property
    def net_cents(self) -> int:
        return self.income_cents - self.expense_cents


class Ledger:
    def __init__(self, path: str | Path = DEFAULT_DATABASE):
        self.path = database_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_date TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
                    category TEXT NOT NULL CHECK (length(trim(category)) > 0),
                    amount_cents INTEGER NOT NULL
                        CHECK (typeof(amount_cents) = 'integer' AND amount_cents > 0),
                    note TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS entries_by_date ON entries(entry_date, id)"
            )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def add(
        self,
        *,
        kind: str,
        amount: str,
        category: str,
        entry_date: str | None = None,
        note: str = "",
    ) -> int:
        if kind not in {"income", "expense"}:
            raise ValidationError("类型必须为 income（收入）或 expense（支出）。")
        amount_cents = parse_amount(amount)
        category = parse_category(category)
        entry_date = parse_date(entry_date if entry_date is not None else date.today().isoformat())
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO entries (entry_date, kind, category, amount_cents, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (entry_date, kind, category, amount_cents, note),
            )
            return cursor.lastrowid

    @staticmethod
    def _filters(
        *, month: str | None = None, kind: str | None = None, category: str | None = None
    ) -> tuple[str, list[str]]:
        clauses = []
        parameters = []
        if month is not None:
            month = parse_month(month)
            last_day = calendar.monthrange(int(month[:4]), int(month[5:]))[1]
            clauses.append("entry_date BETWEEN ? AND ?")
            parameters.extend((f"{month}-01", f"{month}-{last_day:02d}"))
        if kind is not None:
            if kind not in {"income", "expense"}:
                raise ValidationError("类型必须为 income（收入）或 expense（支出）。")
            clauses.append("kind = ?")
            parameters.append(kind)
        if category is not None:
            clauses.append("category = ?")
            parameters.append(parse_category(category))
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), parameters

    def list_entries(
        self, *, month: str | None = None, kind: str | None = None, category: str | None = None
    ) -> list[Entry]:
        clause, parameters = self._filters(month=month, kind=kind, category=category)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, entry_date, kind, category, amount_cents, note FROM entries"
                + clause + " ORDER BY entry_date ASC, id ASC",
                parameters,
            ).fetchall()
        return [Entry(**dict(row)) for row in rows]

    def summary(self, month: str, category: str | None = None) -> Summary:
        clause, parameters = self._filters(month=month, category=category)
        income = expense = 0
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT kind, amount_cents FROM entries" + clause, parameters
            )
            # Python integers also keep totals exact above SQLite's integer range.
            for row in rows:
                if row["kind"] == "income":
                    income += row["amount_cents"]
                else:
                    expense += row["amount_cents"]
        return Summary(income, expense)
