"""Export the normalized pgvector retrieval database to an Excel workbook."""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from psycopg import sql

logger = logging.getLogger(__name__)

EXPORT_TABLES = ("documents", "parents", "children", "figures", "tables", "table_chunks")
DEFAULT_OUTPUT_PATH = Path("dummy_data/morpheus_retrieval_export.xlsx")
EXCEL_FORMULA_PREFIXES = ("=", "+", "-", "@")
EXCEL_CELL_CHARACTER_LIMIT = 32_767


def _database_url() -> str:
    """Return the configured database URL before starting an export."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set to export the retrieval database.")
    return database_url


def _excel_value(value: Any) -> Any:
    """Convert PostgreSQL values to safe, human-readable Excel cell values."""
    if value is None or isinstance(value, (bool, int, float, date, datetime)):
        return value
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)

    sanitized_text = ILLEGAL_CHARACTERS_RE.sub("", text)
    if sanitized_text != text:
        logger.warning("Removed Excel-invalid control characters from exported cell")
    if len(sanitized_text) > EXCEL_CELL_CHARACTER_LIMIT:
        raise ValueError(
            "A retrieval database value exceeds Excel's 32,767-character cell limit; "
            "export that record to a text-based format instead."
        )
    if sanitized_text.startswith(EXCEL_FORMULA_PREFIXES):
        return f"'{sanitized_text}"
    return sanitized_text


def export_retrieval_database(output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, int]:
    """Write every retrieval table to its own Excel sheet.

    Args:
        output_path: Destination for the generated ``.xlsx`` workbook.

    Returns:
        A mapping of table names to exported row counts.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.remove(workbook.active)
    exported_rows: dict[str, int] = {}

    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            for table_name in EXPORT_TABLES:
                logger.info("Exporting retrieval table", extra={"table": table_name})
                cursor.execute(
                    sql.SQL("SELECT * FROM {}.{} ORDER BY 1").format(
                        sql.Identifier("public"), sql.Identifier(table_name)
                    )
                )
                columns = [column.name for column in cursor.description]
                worksheet = workbook.create_sheet(table_name)
                worksheet.append(columns)
                for cell in worksheet[1]:
                    cell.font = Font(bold=True)
                worksheet.freeze_panes = "A2"

                rows = cursor.fetchall()
                for row in rows:
                    worksheet.append([_excel_value(value) for value in row])
                worksheet.auto_filter.ref = worksheet.dimensions
                exported_rows[table_name] = len(rows)
                logger.info(
                    "Exported retrieval table",
                    extra={"table": table_name, "row_count": exported_rows[table_name]},
                )

    workbook.save(output_path)
    logger.info("Retrieval database Excel export complete", extra={"output_path": str(output_path)})
    return exported_rows


def main() -> None:
    """Run the retrieval database exporter from the command line."""
    parser = argparse.ArgumentParser(description="Export all retrieval tables to an Excel workbook.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Workbook destination path.")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    row_counts = export_retrieval_database(arguments.output)
    print(f"Exported workbook: {arguments.output}")
    print(f"Table row counts: {row_counts}")


if __name__ == "__main__":
    main()
