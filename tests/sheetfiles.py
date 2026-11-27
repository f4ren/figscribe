"""Spreadsheet files for the tests, written with the standard library.

`write_ods` is the writer of `examples/make.py`; `write_xlsx` writes the same
rows as an Excel file. Cells: numbers, text, True or False, datetimes,
`Formula`, `Error`, or None for empty.
"""

from __future__ import annotations

import importlib.util
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from xml.sax.saxutils import escape, quoteattr

_spec = importlib.util.spec_from_file_location(
    "figscribe_examples_make", Path(__file__).parents[1] / "examples" / "make.py"
)
_make = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_make)
Formula = _make.Formula
write_ods = _make.write_ods


class Error(NamedTuple):
    """A cell holding a formula error, as Excel stores it."""

    code: str = "#DIV/0!"


def letters(index: int) -> str:
    """The letters of the column `index` (from 0): A, B, ..., Z, AA."""
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(ord("A") + rest) + name
    return name


def write_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    office = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package = "http://schemas.openxmlformats.org/package/2006"
    kinds = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    head = '<?xml version="1.0" encoding="UTF-8"?>'
    parts = {
        "_rels/.rels": f'<Relationships xmlns="{package}/relationships">'
        f'<Relationship Id="rId1" Type="{office}/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>',
        "xl/styles.xml": f'<styleSheet xmlns="{main}"><cellXfs count="2">'
        '<xf numFmtId="0"/><xf numFmtId="22" applyNumberFormat="1"/>'
        "</cellXfs></styleSheet>",
    }
    entries, relations, types = [], [], []
    for i, (name, rows) in enumerate(sheets.items(), 1):
        entries.append(f'<sheet name={quoteattr(name)} sheetId="{i}" r:id="rId{i}"/>')
        relations.append(
            f'<Relationship Id="rId{i}" Type="{office}/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
        )
        types.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            f'ContentType="{kinds}.worksheet+xml"/>'
        )
        lines = []
        for r, row in enumerate(rows, 1):
            cells = "".join(
                _cell(f"{letters(c)}{r}", value) for c, value in enumerate(row)
            )
            lines.append(f'<row r="{r}">{cells}</row>')
        parts[f"xl/worksheets/sheet{i}.xml"] = (
            f'<worksheet xmlns="{main}"><sheetData>{"".join(lines)}'
            "</sheetData></worksheet>"
        )
    parts["xl/workbook.xml"] = (
        f'<workbook xmlns="{main}" xmlns:r="{office}">'
        f"<sheets>{''.join(entries)}</sheets></workbook>"
    )
    styles = len(sheets) + 1
    relations.append(
        f'<Relationship Id="rId{styles}" Type="{office}/styles" Target="styles.xml"/>'
    )
    parts["xl/_rels/workbook.xml.rels"] = (
        f'<Relationships xmlns="{package}/relationships">{"".join(relations)}'
        "</Relationships>"
    )
    parts["[Content_Types].xml"] = (
        f'<Types xmlns="{package}/content-types">'
        '<Default Extension="rels" ContentType='
        '"application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{kinds}.sheet.main+xml"/>'
        f'<Override PartName="/xl/styles.xml" ContentType="{kinds}.styles+xml"/>'
        f"{''.join(types)}</Types>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, head + text)


def _cell(at: str, value: object) -> str:
    formula = ""
    if isinstance(value, Formula):
        formula = f"<f>{escape(value.text)}</f>"
        value = value.value
        if value is None:
            return f'<c r="{at}">{formula}</c>'
    if value is None:
        return ""
    if isinstance(value, Error):
        return f'<c r="{at}" t="e"><f>1/0</f><v>{value.code}</v></c>'
    if isinstance(value, bool):
        return f'<c r="{at}" t="b">{formula}<v>{int(value)}</v></c>'
    if isinstance(value, datetime):
        days = (value - datetime(1899, 12, 30)).total_seconds() / 86400
        return f'<c r="{at}" s="1">{formula}<v>{days}</v></c>'
    if isinstance(value, str):
        if formula:
            return f'<c r="{at}" t="str">{formula}<v>{escape(value)}</v></c>'
        space = ' xml:space="preserve"' if re.match(r"\s|.*\s$", value) else ""
        return f'<c r="{at}" t="inlineStr"><is><t{space}>{escape(value)}</t></is></c>'
    return f'<c r="{at}">{formula}<v>{float(value)!r}</v></c>'
