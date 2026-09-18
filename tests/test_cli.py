import csv
import io

from tests.support import DatabaseTestCase


class CliTests(DatabaseTestCase):
    def test_help_succeeds_without_creating_database(self):
        for arguments in (("--help",), ("add", "--help"), ("list", "--help"), ("summary", "--help"), ("export", "--help")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)
                self.assertEqual(result.stderr, "")
        self.assertFalse(self.database.exists())

    def test_empty_list_and_summary(self):
        listing = self.run_cli("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn("暂无记账记录", listing.stdout)
        summary = self.run_cli("summary", "--month", "2026-09")
        self.assertEqual(summary.returncode, 0, summary.stderr)
        self.assertIn("收入：0.00", summary.stdout)
        self.assertIn("支出：0.00", summary.stdout)
        self.assertIn("净额：0.00", summary.stdout)

    def test_add_list_summary_persist_across_processes(self):
        income = self.run_cli("add", "--kind", "income", "--amount", "100.20", "--category", " 工资 ", "--date", "2026-09-01", "--note", "收入备注")
        expense = self.run_cli("add", "--kind", "expense", "--amount", "12.35", "--category", "餐饮", "--date", "2026-09-02")
        for result, entry_id in ((income, 1), (expense, 2)):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"ID：{entry_id}", result.stdout)
        listing = self.run_cli("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        rows = list(csv.reader(io.StringIO(listing.stdout), delimiter="\t"))
        self.assertEqual(rows[0], ["ID", "日期", "类型", "分类", "金额", "备注"])
        self.assertEqual(rows[1], ["1", "2026-09-01", "income", "工资", "100.20", "收入备注"])
        self.assertEqual(rows[2], ["2", "2026-09-02", "expense", "餐饮", "12.35", ""])
        summary = self.run_cli("summary", "--month", "2026-09")
        self.assertEqual(summary.returncode, 0, summary.stderr)
        self.assertIn("收入：100.20", summary.stdout)
        self.assertIn("支出：12.35", summary.stdout)
        self.assertIn("净额：87.85", summary.stdout)

    def test_multiline_note_and_tab_are_preserved_in_list(self):
        note = '备注\t字段\n第二行 "原文"'
        result = self.run_cli("add", "--kind", "income", "--amount", "1", "--category", "测试", "--note", note)
        self.assertEqual(result.returncode, 0, result.stderr)
        listing = self.run_cli("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        rows = list(csv.reader(io.StringIO(listing.stdout), delimiter="\t"))
        self.assertEqual(rows[1][-1], note)

    def test_invalid_input_returns_nonzero_without_traceback(self):
        base = ["add", "--kind", "expense", "--category", "测试"]
        cases = [
            (base + ["--amount", amount], "金额")
            for amount in ("abc", "0", "-1", "1.234", "NaN", "1e2")
        ]
        cases += [
            (base + ["--amount", "1", "--date", "2026-02-29"], "日期"),
            (base + ["--amount", "1", "--category", " "], "分类"),
            (["summary", "--month", "2026-13"], "月份"),
            (["summary", "--month", "2026-9"], "月份"),
            (["summary", "--month", "2026-09-01"], "月份"),
            (["add", "--kind", "transfer"], "invalid choice"),
            (["add"], "required"),
            ([], "required"),
            (["unknown"], "invalid choice"),
        ]
        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        listing = self.run_cli("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn("暂无记账记录", listing.stdout)

    def test_outside_database_path_is_rejected(self):
        result = self.run_cli("--db", "../outside.sqlite3", "list")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("src 目录内", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_database_error_is_reported_without_traceback(self):
        self.database.write_text("This is not a SQLite database.", encoding="utf-8")
        result = self.run_cli("list")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("数据库操作失败", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
