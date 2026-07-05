"""Report generators — from ResultStore to JSON/CSV/Text/HTML."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

from parallelines.engine import ResultStore


def generate_report_from_store(
    store: ResultStore, fmt: str, output_dir: str | Path
) -> Path:
    """从 ResultStore 生成报告。替代旧的 generate_report()。"""
    data = store.to_dict()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext_map = {"json": "json", "text": "txt", "csv": "csv", "html": "html"}
    ext = ext_map.get(fmt, "json")
    out_path = output_dir / f"parallelines_report_{timestamp}.{ext}"

    if fmt == "json":
        _write_json(data, out_path)
    elif fmt == "text":
        _write_text_from_store(store, out_path)
    elif fmt == "csv":
        _write_csv_from_store(store, out_path)
    elif fmt == "html":
        _write_html_from_store(store, out_path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    return out_path.resolve()


def _write_json(data: dict, path: Path) -> None:
    """Write dict data as JSON."""
    text = json.dumps(data, indent=2, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")


def _write_text_from_store(store: ResultStore, path: Path) -> None:
    """每个关系一个 PrettyTable，写入文本文件。"""
    from prettytable import PrettyTable

    lines: list[str] = []
    for rel_name in ("files", "hash_conflicts", "dep_conflicts", "isolated", "impact"):
        rel = getattr(store, rel_name, None)
        if rel is None or len(rel) == 0:
            continue
        table = PrettyTable()
        table.title = rel_name
        table.field_names = list(rel.columns)
        for row in rel.rows:
            table.add_row(
                [
                    str(getattr(row, c)) if not isinstance(row, tuple) else str(row[i])
                    for i, c in enumerate(rel.columns)
                ]
            )
        lines.append(table.get_string())
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_csv_from_store(store: ResultStore, path: Path) -> None:
    """每个关系一个 CSV 块，写入文本 CSVs 合并。"""
    buffer = io.StringIO()
    for rel_name in ("files", "hash_conflicts", "dep_conflicts", "isolated", "impact"):
        rel = getattr(store, rel_name, None)
        if rel is None or len(rel) == 0:
            continue
        buffer.write(f"# {rel_name}\n")
        writer = csv.writer(buffer)
        writer.writerow(rel.columns)
        for row in rel.rows:
            writer.writerow(
                [
                    str(getattr(row, c)) if not isinstance(row, tuple) else str(row[i])
                    for i, c in enumerate(rel.columns)
                ]
            )
        buffer.write("\n")
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _write_html_from_store(store: ResultStore, path: Path) -> None:
    """每个关系一个 HTML <table>。"""
    lines: list[str] = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<title>Parallelines Analysis Report</title>",
        "<style>body{font-family:sans-serif;margin:2em}",
        "table{border-collapse:collapse;margin:1em 0;width:100%}",
        "th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}",
        "th{background:#f5f5f5}</style></head><body>",
        "<h1>Parallelines Analysis Report</h1>",
    ]
    for rel_name in ("files", "hash_conflicts", "dep_conflicts", "isolated", "impact"):
        rel = getattr(store, rel_name, None)
        if rel is None or len(rel) == 0:
            continue
        lines.append(f"<h2>{rel_name}</h2><table><thead><tr>")
        for c in rel.columns:
            lines.append(f"<th>{c}</th>")
        lines.append("</tr></thead><tbody>")
        for row in rel.rows:
            lines.append("<tr>")
            for i, c in enumerate(rel.columns):
                val = getattr(row, c) if not isinstance(row, tuple) else row[i]
                lines.append(f"<td>{val}</td>")
            lines.append("</tr>")
        lines.append("</tbody></table>")
    lines.append("</body></html>")
    path.write_text("\n".join(lines), encoding="utf-8")
