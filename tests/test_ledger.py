import sqlite3
import unittest
from datetime import date

from ledger.storage import Ledger, Summary
from ledger.validation import (
    DEFAULT_DATABASE,
    MAX_AMOUNT_CENTS,
    PROJECT_ROOT,
    ValidationError,
    database_path,
    format_amount,
    parse_amount,
    parse_category,
    parse_date,
    parse_month,
)
from tests.support import DatabaseTestCase


class ValidationTests(unittest.TestCase):
    def test_valid_amounts_are_exact_integer_cents(self):
        values = {
            "1": 100, "0.01": 1, "0.10": 10, "12.3": 1230,
            "12.30": 1230, ".50": 50, "00012.30": 1230, " 12.30 ": 1230,
            "92233720368547758.07": MAX_AMOUNT_CENTS,
            "0" * 5000 + "1.00": 100,
        }
        for amount, expected in values.items():
            with self.subTest(amount=amount[:60]):
                actual = parse_amount(amount)
                self.assertIs(type(actual), int)
                self.assertEqual(actual, expected)

    def test_invalid_amounts(self):
        invalid = (
            "", " ", "abc", "NaN", "Infinity", "inf", "0", "0.00", "-1",
            "-0.01", "1.001", "1.230", "0.0001", "1e2", "1,000", "１２.３４",
            "1.2.3", "1 2", "92233720368547758.08", "9" * 5000,
        )
        for amount in invalid:
            with self.subTest(amount=amount[:60]):
                with self.assertRaises(ValidationError):
                    parse_amount(amount)

    def test_amount_display_handles_zero_negative_and_large_totals(self):
        for cents, expected in (
            (0, "0.00"), (1, "0.01"), (120, "1.20"), (-1, "-0.01"),
            (-12345, "-123.45"), (MAX_AMOUNT_CENTS * 2, "184467440737095516.14"),
        ):
            with self.subTest(cents=cents):
                self.assertEqual(format_amount(cents), expected)

    def test_valid_dates_and_leap_years(self):
        for value in ("0001-01-01", "2000-02-29", "2024-02-29", "9999-12-31"):
            with self.subTest(value=value):
                self.assertEqual(parse_date(value), value)

    def test_invalid_dates_and_formats(self):
        for value in (
            "", "2025-02-29", "1900-02-29", "2024-02-30", "2026-04-31",
            "2026-00-01", "2026-13-01", "2026-01-00", "0000-01-01",
            "2026-9-01", "2026-09-1", "20260901", "2026-W01-1",
            "2026-09-01T12:00:00", " 2026-09-01", "2026/09/01",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    parse_date(value)

    def test_month_validation_is_strict(self):
        for value in ("0001-01", "2024-02", "9999-12"):
            self.assertEqual(parse_month(value), value)
        for value in ("", "2026-00", "2026-13", "0000-01", "2026-9", "2026-09-01", "2026/09", "2026-09 "):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    parse_month(value)

    def test_category_is_trimmed_and_must_not_be_empty(self):
        self.assertEqual(parse_category("  餐饮  "), "餐饮")
        for value in ("", " ", "\t\n", "\u3000"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    parse_category(value)

    def test_default_database_is_inside_project(self):
        self.assertEqual(DEFAULT_DATABASE, PROJECT_ROOT / "ledger.db")
        self.assertEqual(database_path("ledger.db"), DEFAULT_DATABASE)

    def test_outside_database_paths_are_rejected(self):
        for value in ("../outside.sqlite3", PROJECT_ROOT, "."):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    database_path(value)


class StorageTests(DatabaseTestCase):
    def test_automatic_initialization_and_empty_database(self):
        ledger = Ledger(self.database)
        self.assertTrue(self.database.is_file())
        self.assertEqual(ledger.list_entries(), [])
        self.assertEqual(ledger.summary("2026-09"), Summary(0, 0))

    def test_missing_parent_directories_are_created(self):
        database = self.directory / "nested" / "personal.sqlite3"
        Ledger(database)
        self.assertTrue(database.is_file())

    def test_add_persist_reopen_and_storage_types(self):
        ledger = Ledger(self.database)
        first_id = ledger.add(kind="income", amount="10.10", category=" 工资 ", entry_date="2026-09-01", note="正常备注")
        reopened = Ledger(self.database)
        record = reopened.list_entries()[0]
        self.assertEqual((record.id, record.category, record.amount_cents, record.note), (first_id, "工资", 1010, "正常备注"))
        self.assertEqual(record.kind, "income")
        self.assertEqual(record.entry_date, "2026-09-01")
        second_id = reopened.add(kind="expense", amount="0.10", category="零食", entry_date="2026-09-02")
        self.assertGreater(second_id, first_id)
        connection = sqlite3.connect(self.database)
        try:
            values = connection.execute("SELECT typeof(amount_cents), amount_cents FROM entries ORDER BY id").fetchall()
        finally:
            connection.close()
        self.assertEqual(values, [("integer", 1010), ("integer", 10)])

    def test_default_date_is_local_today(self):
        before = date.today().isoformat()
        ledger = Ledger(self.database)
        ledger.add(kind="expense", amount="1", category="餐饮")
        after = date.today().isoformat()
        self.assertIn(ledger.list_entries()[0].entry_date, {before, after})

    def test_list_orders_by_date_then_id(self):
        ledger = Ledger(self.database)
        later = ledger.add(kind="income", amount="1", category="工资", entry_date="2026-09-02")
        earlier = ledger.add(kind="income", amount="2", category="工资", entry_date="2026-09-01")
        same_date = ledger.add(kind="expense", amount="3", category="餐饮", entry_date="2026-09-01")
        self.assertEqual([record.id for record in ledger.list_entries()], [earlier, same_date, later])

    def test_month_summary_excludes_neighboring_months(self):
        ledger = Ledger(self.database)
        for kind, amount, entry_date in (
            ("income", "1000", "2023-12-31"),
            ("income", "10.10", "2024-01-01"),
            ("income", "0.20", "2024-01-15"),
            ("expense", "3.31", "2024-01-31"),
            ("expense", "1000", "2024-02-01"),
        ):
            ledger.add(kind=kind, amount=amount, category="测试", entry_date=entry_date)
        summary = ledger.summary("2024-01")
        self.assertEqual(summary, Summary(1030, 331))
        self.assertEqual(summary.net_cents, 699)
        self.assertEqual(ledger.summary("2024-03"), Summary(0, 0))

    def test_leap_month_and_extreme_year_boundaries(self):
        ledger = Ledger(self.database)
        for entry_date in ("2024-02-29", "0001-01-01", "9999-12-31"):
            ledger.add(kind="income", amount="0.01", category="测试", entry_date=entry_date)
            self.assertEqual(ledger.summary(entry_date[:7]), Summary(1, 0))

    def test_expense_only_summary_has_negative_net(self):
        ledger = Ledger(self.database)
        ledger.add(kind="expense", amount="0.01", category="测试", entry_date="2026-09-18")
        self.assertEqual(ledger.summary("2026-09").net_cents, -1)

    def test_totals_can_exceed_sqlite_integer_range(self):
        ledger = Ledger(self.database)
        for _ in range(2):
            ledger.add(kind="income", amount="92233720368547758.07", category="测试", entry_date="2026-09-18")
        self.assertEqual(ledger.summary("2026-09").income_cents, MAX_AMOUNT_CENTS * 2)

    def test_invalid_records_are_not_saved(self):
        ledger = Ledger(self.database)
        valid = dict(kind="income", amount="1", category="测试", entry_date="2026-09-18")
        for changes in (
            {"kind": "transfer"}, {"amount": "0"}, {"amount": "1.234"},
            {"category": " "}, {"entry_date": "2026-02-29"}, {"entry_date": ""},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    ledger.add(**(valid | changes))
        self.assertEqual(ledger.list_entries(), [])

    def test_note_and_category_are_stored_as_text_not_sql(self):
        ledger = Ledger(self.database)
        text = "餐饮'); DROP TABLE entries; --\n备注\t字段"
        ledger.add(kind="expense", amount="1", category=text, note=text, entry_date="2026-09-18")
        record = ledger.list_entries()[0]
        self.assertEqual(record.category, text)
        self.assertEqual(record.note, text)

    def test_directory_database_path_is_rejected(self):
        with self.assertRaises(ValidationError):
            Ledger(self.directory)
