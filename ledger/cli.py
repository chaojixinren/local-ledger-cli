"""The public command-line interface."""

import argparse
import csv
import sqlite3
import sys

from .exporting import ExportError, export_csv, export_path
from .storage import Ledger
from .validation import DEFAULT_DATABASE, ValidationError, format_amount


def add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--month", metavar="YYYY-MM", help="仅查询指定自然月")
    parser.add_argument("--kind", choices=("income", "expense"), help="仅查询收入或支出")
    parser.add_argument("--category", help="分类去除首尾空白后精确匹配")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m ledger",
        description="本地个人记账：记录收入和支出，查看指定月份的净额。",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DATABASE),
        metavar="FILE",
        help="src 目录内的 SQLite 文件；相对路径以 src 为基准，默认 ledger.db",
    )
    commands = parser.add_subparsers(dest="command", required=True, title="命令")
    add = commands.add_parser("add", help="新增收入或支出")
    add.add_argument("--kind", required=True, choices=("income", "expense"), help="收入或支出")
    add.add_argument("--amount", required=True, help="正数金额，最多两位小数")
    add.add_argument("--category", required=True, help="非空分类")
    add.add_argument("--date", metavar="YYYY-MM-DD", help="交易日期，默认本地当天")
    add.add_argument("--note", default="", help="可选备注")
    listing = commands.add_parser("list", help="按日期及 ID 升序列出记录")
    add_filters(listing)
    summary = commands.add_parser("summary", help="查看自然月收入、支出和净额")
    summary.add_argument("--month", required=True, metavar="YYYY-MM", help="统计月份")
    summary.add_argument("--category", help="仅统计指定分类，去除首尾空白后精确匹配")
    export = commands.add_parser("export", help="导出 UTF-8 CSV，拒绝覆盖已有文件")
    export.add_argument("--output", required=True, metavar="FILE", help="src 内尚不存在的导出文件")
    add_filters(export)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            export_path(args.output, args.db)
        ledger = Ledger(args.db)
        if args.command == "add":
            entry_id = ledger.add(
                kind=args.kind,
                amount=args.amount,
                category=args.category,
                entry_date=args.date,
                note=args.note,
            )
            print(f"已添加记录，ID：{entry_id}")
        elif args.command == "list":
            entries = ledger.list_entries(month=args.month, kind=args.kind, category=args.category)
            if not entries:
                print("暂无记账记录。")
            else:
                writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
                writer.writerow(("ID", "日期", "类型", "分类", "金额", "备注"))
                for entry in entries:
                    writer.writerow((
                        entry.id,
                        entry.entry_date,
                        entry.kind,
                        entry.category,
                        format_amount(entry.amount_cents),
                        entry.note,
                    ))
        elif args.command == "export":
            entries = ledger.list_entries(month=args.month, kind=args.kind, category=args.category)
            path = export_csv(entries, args.output, database=ledger.path)
            print(f"已导出 {len(entries)} 条记录：{path}")
        else:
            result = ledger.summary(args.month, category=args.category)
            print(f"月份：{args.month}")
            print(f"收入：{format_amount(result.income_cents)}")
            print(f"支出：{format_amount(result.expense_cents)}")
            print(f"净额：{format_amount(result.net_cents)}")
    except ValidationError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except ExportError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except (OSError, sqlite3.Error, ValueError) as exc:
        label = "导出操作失败" if args.command == "export" else "数据库操作失败"
        print(f"{label}：{exc}", file=sys.stderr)
        return 1
    return 0
