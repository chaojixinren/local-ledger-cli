"""Publish a complete UTF-8 CSV without replacing existing files."""

import csv
import os
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from .storage import Entry
from .validation import PROJECT_ROOT, ValidationError, database_path, format_amount


class ExportError(Exception):
    """An export failed while creating or publishing the CSV."""


def export_path(value: str | Path, database: str | Path) -> Path:
    if not str(value).strip():
        raise ValidationError("导出文件路径不能为空。")
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    # Normalize '..' lexically, before probing any filesystem paths.
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(PROJECT_ROOT) or path == PROJECT_ROOT:
        raise ValidationError("导出文件必须位于本项目的 src 目录内。")
    if path == database_path(database):
        raise ValidationError("导出目标不能是数据库文件。")
    current = PROJECT_ROOT
    for part in path.relative_to(PROJECT_ROOT).parts:
        current = current / part
        if current.is_symlink():
            raise ValidationError("导出路径不能包含符号链接。")
    if path.exists():
        raise ValidationError("导出目标已存在，不会覆盖原文件。")
    return path


@contextmanager
def _parent_directory(path: Path):
    # Directory descriptors and O_NOFOLLOW prevent symlink substitutions
    # between validation and writing. These APIs are available on macOS/Linux.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(PROJECT_ROOT, flags)
    try:
        for part in path.relative_to(PROJECT_ROOT).parts[:-1]:
            try:
                os.mkdir(part, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def export_csv(
    entries: Iterable[Entry], output: str | Path, *, database: str | Path
) -> Path:
    path = export_path(output, database)
    try:
        with _parent_directory(path) as directory:
            temporary = None
            try:
                name = f".ledger-export-{secrets.token_hex(16)}.tmp"
                descriptor = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
                temporary = name
                try:
                    stream = os.fdopen(descriptor, "w", encoding="utf-8", newline="")
                except BaseException:
                    os.close(descriptor)
                    raise
                with stream:
                    writer = csv.writer(stream)
                    writer.writerow(("id", "date", "kind", "category", "amount", "note"))
                    for entry in entries:
                        writer.writerow((
                            entry.id, entry.entry_date, entry.kind, entry.category,
                            format_amount(entry.amount_cents), entry.note,
                        ))
                    stream.flush()
                    os.fsync(stream.fileno())
                # Hard-link creation is atomic and fails if the target exists.
                # The final name only becomes visible after the CSV is complete.
                os.link(
                    temporary, path.name,
                    src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False,
                )
            finally:
                if temporary is not None:
                    os.unlink(temporary, dir_fd=directory)
    except (OSError, ValueError, csv.Error) as exc:
        raise ExportError(f"CSV 导出失败：{exc}") from exc
    return path
