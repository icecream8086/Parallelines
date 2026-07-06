"""Output formatting for REPL query results."""
from __future__ import annotations
import csv
import io
import json
from typing import Literal
from prettytable import PrettyTable
from parallelines.engine.store import Relation

OutputMode = Literal["table", "vertical", "json", "csv"]
_PAGE_SIZE = 50

def format_result(rel: Relation, mode: OutputMode = "table") -> str:
    if len(rel) == 0:
        return "Empty set."
    if mode == "table":
        return _format_table(rel)
    if mode == "vertical":
        return _format_vertical(rel)
    if mode == "json":
        return _format_json(rel)
    if mode == "csv":
        return _format_csv(rel)
    return _format_table(rel)

def _format_table(rel: Relation) -> str:
    pt = PrettyTable()
    pt.field_names = list(rel.columns)
    pt.align = "l"
    for row in rel.rows:
        pt.add_row([str(v) for v in _row_to_tuple(row)])
    return pt.get_string()

def _format_vertical(rel: Relation) -> str:
    lines: list[str] = []
    for i, row in enumerate(rel.rows, 1):
        lines.append(f"********** {i}. row **********")
        for col, val in zip(rel.columns, _row_to_tuple(row)):
            lines.append(f"  {col}: {val}")
    return "\n".join(lines)

def _format_json(rel: Relation) -> str:
    return json.dumps(
        [dict(zip(rel.columns, _row_to_tuple(r))) for r in rel.rows],
        indent=2, ensure_ascii=False, default=str,
    )

def _format_csv(rel: Relation) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(rel.columns)
    for row in rel.rows:
        w.writerow([str(v) for v in _row_to_tuple(row)])
    return buf.getvalue().strip()

def _row_to_tuple(row) -> tuple:
    if isinstance(row, tuple):
        return row
    import dataclasses
    return tuple(getattr(row, f.name) for f in dataclasses.fields(row))

def pager(text: str, page_size: int = _PAGE_SIZE) -> None:
    lines = text.split("\n")
    if len(lines) <= page_size:
        print(text)
        return
    total = len(lines)
    for start in range(0, total, page_size):
        end = min(start + page_size, total)
        print("\n".join(lines[start:end]))
        if end < total:
            try:
                input(f"-- More -- ({total - end} lines remaining, Enter=continue, q=quit) ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
