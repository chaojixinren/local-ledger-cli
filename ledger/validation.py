"""Validate user input without using floating-point arithmetic."""

import re
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = PROJECT_ROOT / "ledger.db"
MAX_AMOUNT_CENTS = 2**63 - 1


class ValidationError(ValueError):
    """An input value cannot be used by the ledger."""


def parse_amount(value: str) -> int:
    value = value.strip()
    if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]{1,2})?|\.[0-9]{1,2})", value):
        raise ValidationError("金额必须为正的十进制数，最多两位小数，例如 12.50。")
    whole, _, fraction = value.partition(".")
    whole = whole.lstrip("0") or "0"
    if len(whole) > 17:
        raise ValidationError("金额过大，单笔金额不能超过 92233720368547758.07。")
    cents = int(whole) * 100 + int(fraction.ljust(2, "0"))
    if cents <= 0:
        raise ValidationError("金额必须大于零。")
    if cents > MAX_AMOUNT_CENTS:
        raise ValidationError("金额过大，单笔金额不能超过 92233720368547758.07。")
    return cents


def format_amount(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"


def parse_date(value: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValidationError("日期必须使用 YYYY-MM-DD 格式。")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("日期无效，请填写真实存在的日期。") from exc
    return value


def parse_month(value: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise ValidationError("月份必须使用 YYYY-MM 格式。")
    try:
        date(int(value[:4]), int(value[5:]), 1)
    except ValueError as exc:
        raise ValidationError("月份无效，年份须为 0001–9999，月份须为 01–12。") from exc
    return value


def parse_category(value: str) -> str:
    category = value.strip()
    if not category:
        raise ValidationError("分类去除首尾空白后不能为空。")
    return category


def database_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    if not resolved.is_relative_to(PROJECT_ROOT) or resolved == PROJECT_ROOT:
        raise ValidationError("数据库文件必须位于本项目的 src 目录内。")
    if resolved.exists() and not resolved.is_file():
        raise ValidationError("数据库路径必须指向文件，不能是目录。")
    return resolved
