"""CSV export helpers.

Cell values are sanitized against spreadsheet formula injection: a cell that
starts with ``=``, ``+``, ``-`` or ``@`` is executed as a formula by Excel,
LibreOffice and Google Sheets, which would let a document title run commands
on the machine of whoever opens the export. Such values are prefixed with a
single quote, the standard spreadsheet escape.
"""
import csv
import io

from flask import Response

# Leading characters that a spreadsheet interprets as the start of a formula.
_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def sanitize_cell(value):
    """Return a value that is safe to write into a CSV cell."""
    if value is None:
        return ''
    text = value if isinstance(value, str) else str(value)
    if text[:1] in _FORMULA_PREFIXES:
        return "'" + text
    return text


def build_csv(headers, rows):
    """Build CSV bytes for the given headers and rows, RFC 4180 encoded."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator='\r\n')
    writer.writerow([sanitize_cell(h) for h in headers])
    for row in rows:
        writer.writerow([sanitize_cell(cell) for cell in row])
    # utf-8-sig adds the BOM that makes Excel detect UTF-8 and show Greek text.
    return buffer.getvalue().encode('utf-8-sig')


def csv_response(filename, headers, rows):
    """Build a downloadable CSV response for the given headers and rows."""
    payload = build_csv(headers, rows)
    return Response(payload, mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"',
                             'Cache-Control': 'private, no-store',
                             'X-Content-Type-Options': 'nosniff'})
