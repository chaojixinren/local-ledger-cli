import csv
import io

from ledger.storage import Ledger, Summary
from ledger.validation import ValidationError
from tests.support import DatabaseTestCase


class FilterFixture(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.ledger = Ledger(self.database)
        for entry_date, kind, category, amount in (
            ("2026-09-30", "expense", "餐饮", "10.50"),
            ("2026-08-31", "expense", "餐饮", "100"),
            ("2026-09-01", "income", "餐饮", "20"),
            ("2026-10-01", "expense", "餐饮", "200"),
            ("2026-09-01", "expense", "交通", "3"),
            ("2026-09-01", "expense", "餐饮", "2.25"),
        ):
            self.ledger.add(kind=kind, amount=amount, category=category, entry_date=entry_date)


class FilterStorageTests(FilterFixture):
    def test_omitting_filters_preserves_all_records_and_order(self):
        self.assertEqual([entry.id for entry in self.ledger.list_entries()], [2, 3, 5, 6, 1, 4])

    def test_all_filters_are_combined_with_and(self):
        entries = self.ledger.list_entries(month="2026-09", kind="expense", category=" 餐饮 ")
        self.assertEqual([entry.id for entry in entries], [6, 1])

    def test_individual_filters_and_empty_matches(self):
        for filters, expected in (
            ({"month": "2026-09"}, [3, 5, 6, 1]),
            ({"kind": "income"}, [3]),
            ({"category": "交通"}, [5]),
            ({"month": "2026-07"}, []),
            ({"month": "2026-09", "kind": "income", "category": "交通"}, []),
        ):
            with self.subTest(filters=filters):
                self.assertEqual([entry.id for entry in self.ledger.list_entries(**filters)], expected)

    def test_category_is_exact_not_substring_wildcard_or_sql(self):
        literal = self.ledger.add(kind="expense", amount="1", category="餐饮%_", entry_date="2026-09-01")
        self.ledger.add(kind="expense", amount="1", category="餐饮其他", entry_date="2026-09-01")
        self.assertEqual([entry.id for entry in self.ledger.list_entries(category="餐饮%_")], [literal])
        for value in ("餐", "%", "_", "%' OR 1=1 --"):
            with self.subTest(category=value):
                self.assertEqual(self.ledger.list_entries(category=value), [])

    def test_invalid_filters_raise_validation_errors(self):
        for filters in ({"month": "2026-13"}, {"month": "2026-9"}, {"month": ""}, {"category": ""}, {"category": "  "}, {"kind": "transfer"}):
            with self.subTest(filters=filters):
                with self.assertRaises(ValidationError):
                    self.ledger.list_entries(**filters)

    def test_category_summary_and_unfiltered_compatibility(self):
        summary = self.ledger.summary("2026-09", category=" 餐饮 ")
        self.assertEqual(summary, Summary(2000, 1275))
        self.assertEqual(summary.net_cents, 725)
        self.assertEqual(self.ledger.summary("2026-09"), Summary(2000, 1575))
        self.assertEqual(self.ledger.summary("2026-09", category="不存在"), Summary(0, 0))
        self.assertEqual(self.ledger.summary("2026-07", category="餐饮"), Summary(0, 0))
        for value in ("", " "):
            with self.subTest(category=value):
                with self.assertRaises(ValidationError):
                    self.ledger.summary("2026-09", category=value)

    def test_month_filters_include_leap_day_and_extreme_years(self):
        for entry_date in ("2024-02-29", "0001-01-01", "9999-12-31"):
            entry_id = self.ledger.add(kind="expense", amount="1", category="边界", entry_date=entry_date)
            entries = self.ledger.list_entries(month=entry_date[:7], category="边界")
            self.assertEqual([entry.id for entry in entries], [entry_id])
        self.ledger.add(kind="income", amount="1", category="边界", entry_date="2024-03-01")
        self.assertEqual(len(self.ledger.list_entries(month="2024-02")), 1)


class FilterCliTests(FilterFixture):
    def test_list_combined_filters(self):
        result = self.run_cli("list", "--month", "2026-09", "--kind", "expense", "--category", " 餐饮 ")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = list(csv.reader(io.StringIO(result.stdout), delimiter="\t"))
        self.assertEqual([row[0] for row in rows[1:]], ["6", "1"])

    def test_filtered_list_empty_result_is_clear(self):
        result = self.run_cli("list", "--category", "不存在")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("暂无记账记录", result.stdout)

    def test_category_summary_outputs_exact_totals_or_zero(self):
        result = self.run_cli("summary", "--month", "2026-09", "--category", " 餐饮 ")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "月份：2026-09\n收入：20.00\n支出：12.75\n净额：7.25\n")
        empty = self.run_cli("summary", "--month", "2026-09", "--category", "不存在")
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(empty.stdout, "月份：2026-09\n收入：0.00\n支出：0.00\n净额：0.00\n")

    def test_invalid_filter_inputs_have_no_traceback(self):
        output = self.directory / "invalid.csv"
        for command in (["list"], ["export", "--output", str(output)]):
            for options in (["--category", ""], ["--category", " "], ["--month", "2026-13"], ["--month", "2026-9"], ["--kind", "transfer"]):
                with self.subTest(command=command, options=options):
                    result = self.run_cli(*command, *options)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue(result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
        for category in ("", " "):
            result = self.run_cli("summary", "--month", "2026-09", "--category", category)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("分类", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(output.exists())
