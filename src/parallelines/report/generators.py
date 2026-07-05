"""Report generators -- convert AnalysisReport to various output formats."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from prettytable import PrettyTable

from parallelines.types import AnalysisReport


def generate_json_report(report: AnalysisReport, path: str | Path) -> None:
    """Serialize *report* to a JSON file with *path*.

    Each fragment's items are written as ``{"analyzer": name, "results": items}``.
    """
    try:
        output: list[dict[str, Any]] = []
        for fragment in report.fragments:
            output.append(
                {
                    "analyzer": fragment.analyzer_name,
                    "results": fragment.items or [],
                }
            )

        path = Path(path)
        text = json.dumps(output, indent=2, ensure_ascii=False)
        # Strip surrogate characters that cause UnicodeEncodeError
        text = text.encode("utf-8", errors="replace").decode("utf-8")
        path.write_text(text, encoding="utf-8")
    except Exception as exc:
        msg = f"Failed to write JSON report to {path}: {exc}"
        raise RuntimeError(msg) from exc


def generate_text_report(report: AnalysisReport, path: str | Path) -> None:
    """Write a human-readable text report using PrettyTable tables.

    Each fragment is rendered as a separate table headed by the analyzer name.
    If a fragment has no items the string ``"No issues found"`` is written instead.
    """
    try:
        lines: list[str] = []
        for fragment in report.fragments:
            lines.append(f"Analyzer: {fragment.analyzer_name}")
            lines.append("")

            if not fragment.items:
                lines.append("    No issues found")
                lines.append("")
                continue

            # Derive field names from the keys of the first item.
            field_names = list(fragment.items[0].keys())
            table = PrettyTable()
            table.title = fragment.analyzer_name
            table.field_names = field_names

            for item in fragment.items:
                row = [str(item.get(k, "")) for k in field_names]
                table.add_row(row)

            lines.append(table.get_string())
            lines.append("")

        path = Path(path)
        path.write_text("\n".join(lines), encoding="utf-8")
    except Exception as exc:
        msg = f"Failed to write text report to {path}: {exc}"
        raise type(exc)(msg) from exc


def generate_csv_report(report: AnalysisReport, path: str | Path) -> None:
    """Write a CSV file for each fragment in *report*.

    Each fragment is written to the *same* file separated by a comment line
    (``# analyzer_name``).  Dict items are flattened as CSV rows; the column
    order is derived from the keys of the first non-empty fragment.
    """
    try:
        path = Path(path)
        with path.open("w", newline="", encoding="utf-8") as fh:
            for fragment in report.fragments:
                fh.write(f"# {fragment.analyzer_name}\n")

                if not fragment.items:
                    continue

                field_names = list(fragment.items[0].keys())
                writer = csv.DictWriter(fh, fieldnames=field_names)
                writer.writeheader()
                for item in fragment.items:
                    writer.writerow(item)

        # Strip the trailing newline from the very last line for cleanliness.
        raw = path.read_text(encoding="utf-8")
        path.write_text(raw.rstrip("\n") + "\n", encoding="utf-8")
    except Exception as exc:
        msg = f"Failed to write CSV report to {path}: {exc}"
        raise type(exc)(msg) from exc


def generate_html_report(report: AnalysisReport, path: str | Path) -> None:
    """Generate a self-contained HTML report with styled tables.

    The HTML uses inline CSS with no external dependencies.  Each analyzer is
    a section containing a styled table.  Rows are colour-coded:
      - Green  (OK)       → no items (message row)
      - Yellow (warning)  → items present
      - Red    (critical) → items with severity ``"critical"`` or ``"high"``

    Filename values longer than 80 characters are truncated with an ellipsis.
    """
    try:
        path = Path(path)

        rows_html: list[str] = []
        for idx, fragment in enumerate(report.fragments):
            analyzer_label = escape(fragment.analyzer_name.replace("Analyzer", ""))
            rows_html.append(f'      <h2 style="color: #333;">{analyzer_label}</h2>\n')

            if not fragment.items:
                rows_html.append(
                    '      <table class="ok">\n'
                    '        <tr><td style="padding: 8px; color: #155724;">'
                    "No issues found</td></tr>\n"
                    "      </table>\n"
                )
                continue

            # Determine field names from the first item's keys
            field_names = list(fragment.items[0].keys())

            # Build header
            cols_html = "".join(
                f'<th style="padding: 8px 12px; border-bottom: 2px solid #ddd; '
                f'text-align: left; background: #f8f9fa;">'
                f"{escape(hdr)}</th>\n"
                for hdr in field_names
            )
            table_id = f"t{idx}"

            # Table class: "critical" if any item is critical/high severity
            has_critical = any(
                str(item.get("severity", "")).lower() in ("critical", "high")
                for item in fragment.items
            )
            table_class = "critical" if has_critical else "warn"

            table_html = (
                f'      <table id="{table_id}" class="{table_class}">\n'
                f"        <thead>\n"
                f"          <tr>{cols_html}        </tr>\n"
                f"        </thead>\n"
                f"        <tbody>\n"
            )

            for item in fragment.items:
                vals: list[str] = []
                for k in field_names:
                    raw = str(item.get(k, ""))
                    # Truncate long paths (typically the filename column)
                    if len(raw) > 80:
                        raw = raw[:77] + "..."
                    vals.append(escape(raw))
                row_cells = "".join(
                    f'<td style="padding: 6px 12px; border-bottom: 1px solid #eee;">'
                    f"{v}</td>\n"
                    for v in vals
                )
                table_html += f"          <tr>{row_cells}        </tr>\n"

            table_html += "        </tbody>\n      </table>\n"
            rows_html.append(table_html)

        html = (
            "<!DOCTYPE html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '  <meta charset="utf-8">\n'
            f"  <title>Parallelines Analysis Report</title>\n"
            "  <style>\n"
            "    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', "
            "Roboto, sans-serif; margin: 20px; background: #fff; color: #333; }\n"
            "    h1 { border-bottom: 2px solid #333; padding-bottom: 8px; }\n"
            "    .timestamp { color: #666; font-size: 0.9em; margin-bottom: 20px; }\n"
            "    table { border-collapse: collapse; width: 100%; margin-bottom: 24px; }\n"
            "    table.ok { background: #d4edda; border: 1px solid #c3e6cb; }\n"
            "    table.warn { background: #fff3cd; border: 1px solid #ffeeba; }\n"
            "    table.critical { background: #f8d7da; border: 1px solid #f5c6cb; }\n"
            "    th { font-weight: 600; }\n"
            "    tr:hover { opacity: 0.92; }\n"
            "  </style>\n"
            "</head>\n"
            "<body>\n"
            "  <h1>Parallelines Analysis Report</h1>\n"
            f'  <p class="timestamp">Generated: '
            f"{escape(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</p>\n"
            + "\n".join(rows_html)
            + "\n</body>\n</html>\n"
        )

        path.write_text(html, encoding="utf-8")
    except Exception as exc:
        msg = f"Failed to write HTML report to {path}: {exc}"
        raise RuntimeError(msg) from exc


def generate_report(
    report: AnalysisReport,
    output_format: str,
    output_dir: str | Path,
) -> Path:
    """Dispatch report generation to the appropriate formatter.

    Supported *output_format* values:

    ``"json"``
        Delegates to :func:`generate_json_report`.
    ``"text"``
        Delegates to :func:`generate_text_report`.
    ``"csv"``
        Delegates to :func:`generate_csv_report`.
    ``"html"``
        Delegates to :func:`generate_html_report`.

    The output directory is created if it does not exist.  The generated file
    is named ``parallelines_report_<timestamp>.<ext>``.

    Returns the absolute path of the generated file.
    """
    ext_map = {"json": "json", "text": "txt", "csv": "csv", "html": "html"}

    if output_format not in ext_map:
        msg = f"Unsupported output format: {output_format!r}.  Choose from {set(ext_map)}."
        raise ValueError(msg)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = ext_map[output_format]
    filename = f"parallelines_report_{timestamp}.{ext}"
    out_path = output_dir / filename

    if output_format == "json":
        generate_json_report(report, out_path)
    elif output_format == "text":
        generate_text_report(report, out_path)
    elif output_format == "csv":
        generate_csv_report(report, out_path)
    elif output_format == "html":
        generate_html_report(report, out_path)

    return out_path.resolve()
