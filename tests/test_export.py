import csv
import io
import os
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from ledger.cli import main
from ledger.storage import Ledger
from ledger.validation import PROJECT_ROOT
from tests.support import DatabaseTestCase


class ExportTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.ledger = Ledger(self.database)
        self.note = '午餐, "双引号"\n第二行\r\n第三行\t结束'
        self.ledger.add(kind="expense", amount="12.30", category='餐饮,"聚餐"', entry_date="2026-09-30", note=self.note)
        self.ledger.add(kind="income", amount="100", category="工资", entry_date="2026-09-01")
        self.ledger.add(kind="expense", amount="1", category="交通", entry_date="2026-08-31")
        self.ledger.add(kind="expense", amount="2", category="交通", entry_date="2026-10-01")
        self.ledger.add(kind="expense", amount="3", category="交通", entry_date="2026-09-01")

    def read_csv(self, path):
        with path.open(encoding="utf-8", newline="") as stream:
            return list(csv.reader(stream))

    def invoke_in_process(self, output):
        stderr, stdout = io.StringIO(), io.StringIO()
        with redirect_stderr(stderr), redirect_stdout(stdout):
            status = main(["--db", str(self.database), "export", "--output", str(output)])
        self.assertNotEqual(status, 0)
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertTrue(stderr.getvalue())
        return stderr.getvalue()

    def test_csv_header_utf8_special_characters_amount_and_order(self):
        output = self.directory / "reports" / "nested" / "all.csv"
        relative = output.relative_to(PROJECT_ROOT)
        result = self.run_cli("export", "--output", str(relative))
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.read_csv(output)
        self.assertEqual(rows[0], ["id", "date", "kind", "category", "amount", "note"])
        self.assertEqual([row[0] for row in rows[1:]], ["3", "2", "5", "1", "4"])
        self.assertEqual(rows[4], ["1", "2026-09-30", "expense", '餐饮,"聚餐"', "12.30", self.note])
        self.assertEqual(rows[2][4], "100.00")
        self.assertIn('""双引号""'.encode("utf-8"), output.read_bytes())
        self.assertEqual(list(output.parent.iterdir()), [output])

    def test_export_uses_exactly_the_same_filters_as_list(self):
        filters = (
            [], ["--month", "2026-09"], ["--kind", "income"], ["--category", "交通"],
            ["--month", "2026-09", "--kind", "expense", "--category", " 交通 "],
        )
        for index, options in enumerate(filters):
            with self.subTest(options=options):
                output = self.directory / f"filtered-{index}.csv"
                result = self.run_cli("export", "--output", str(output), *options)
                self.assertEqual(result.returncode, 0, result.stderr)
                listing = self.run_cli("list", *options)
                self.assertEqual(listing.returncode, 0, listing.stderr)
                list_rows = list(csv.reader(io.StringIO(listing.stdout, newline=""), delimiter="\t"))
                # subprocess text mode normalizes CRLF in terminal output.
                export_rows = [[value.replace("\r\n", "\n") for value in row] for row in self.read_csv(output)[1:]]
                self.assertEqual(export_rows, list_rows[1:])

    def test_no_matches_still_exports_header(self):
        output = self.directory / "empty.csv"
        result = self.run_cli("export", "--output", str(output), "--month", "2026-09", "--category", "不存在")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_csv(output), [["id", "date", "kind", "category", "amount", "note"]])

    def test_existing_file_is_preserved_exactly(self):
        output = self.directory / "existing.csv"
        original = b"original content\x00\xff"
        output.write_bytes(original)
        result = self.run_cli("export", "--output", str(output))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("已存在", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(output.read_bytes(), original)

    def test_database_and_hardlink_to_it_cannot_be_overwritten(self):
        original = self.database.read_bytes()
        alias = self.directory / "database-alias.csv"
        os.link(self.database, alias)
        for output in (self.database, alias):
            with self.subTest(output=output):
                result = self.run_cli("export", "--output", str(output))
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(self.database.read_bytes(), original)
                self.assertEqual(alias.read_bytes(), original)

    def test_output_equal_to_missing_database_is_rejected_before_initialization(self):
        missing = self.directory / "not-created.sqlite3"
        result = self.run_cli("--db", str(missing), "export", "--output", str(missing))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("数据库", result.stderr)
        self.assertFalse(missing.exists())

    def test_successful_export_does_not_modify_database(self):
        original = self.database.read_bytes()
        result = self.run_cli("export", "--output", str(self.directory / "safe.csv"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.database.read_bytes(), original)

    def test_invalid_output_paths_are_rejected(self):
        for output in ("", " ", "../outside.csv", str(PROJECT_ROOT), str(self.directory)):
            with self.subTest(output=output):
                result = self.run_cli("export", "--output", output)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_symlinks_and_symlink_parent_directories_are_rejected(self):
        real = self.directory / "real"
        real.mkdir()
        alias = self.directory / "alias"
        alias.symlink_to(real, target_is_directory=True)
        dangling = self.directory / "dangling.csv"
        dangling.symlink_to(self.directory / "missing.csv")
        outside = self.directory / "outside"
        outside.symlink_to(PROJECT_ROOT.parent / "not-accessed", target_is_directory=True)
        for output in (alias / "report.csv", dangling, outside / "report.csv"):
            with self.subTest(output=output):
                result = self.run_cli("export", "--output", str(output))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("符号链接", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(list(real.iterdir()), [])
        self.assertFalse((self.directory / "missing.csv").exists())

    def test_non_directory_parent_reports_failure_without_partial_file(self):
        parent = self.directory / "plain-file"
        parent.write_text("keep me", encoding="utf-8")
        before = set(self.directory.iterdir())
        result = self.run_cli("export", "--output", str(parent / "report.csv"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("导出", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(parent.read_text(encoding="utf-8"), "keep me")
        self.assertEqual(set(self.directory.iterdir()), before)

    def test_write_failure_removes_temporary_file(self):
        output = self.directory / "failed.csv"
        before = set(self.directory.iterdir())
        with patch("ledger.exporting.os.fsync", side_effect=OSError("模拟磁盘写入失败")):
            error = self.invoke_in_process(output)
        self.assertIn("CSV 导出失败", error)
        self.assertFalse(output.exists())
        self.assertEqual(set(self.directory.iterdir()), before)

    def test_publish_failure_removes_temporary_file(self):
        output = self.directory / "failed.csv"
        before = set(self.directory.iterdir())
        with patch("ledger.exporting.os.link", side_effect=OSError("模拟发布失败")):
            self.invoke_in_process(output)
        self.assertFalse(output.exists())
        self.assertEqual(set(self.directory.iterdir()), before)

    def test_concurrent_target_creation_preserves_new_target(self):
        output = self.directory / "raced.csv"
        original = b"another process created this"

        def racing_link(source, target, **kwargs):
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=kwargs["dst_dir_fd"])
            try:
                os.write(descriptor, original)
            finally:
                os.close(descriptor)
            raise FileExistsError("目标在写入期间已被创建")

        with patch("ledger.exporting.os.link", side_effect=racing_link):
            self.invoke_in_process(output)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(set(self.directory.iterdir()), {self.database, output})

    def test_parent_symlink_substitution_is_rejected_before_writing(self):
        real = self.directory / "real"
        real.mkdir()
        output = self.directory / "reports" / "safe.csv"
        mkdir = os.mkdir

        def substitute_parent(path, *args, **kwargs):
            if path == "reports":
                os.symlink(str(real), path, dir_fd=kwargs["dir_fd"], target_is_directory=True)
            return mkdir(path, *args, **kwargs)

        with patch("ledger.exporting.os.mkdir", side_effect=substitute_parent):
            self.invoke_in_process(output)
        self.assertEqual(list(real.iterdir()), [])
