"""
Export files for UC3 (Algorithm 2): CSV and PDF built from a `data.readings` result.

`gather` runs the (already validated) queries; everything else is a pure function of
its result, so the formats are easy to test. The router and backend/scripts/make_sample_export.py
both use `gather` + `render`, so the committed sample is made by the same code.

SEC-21: every text cell of a CSV goes through `safe_cell`, so a value such as
`=HYPERLINK(...)` is shown as text by Excel instead of being run as a formula.
"""
from __future__ import annotations

import csv
import io
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..db import Transaction
from . import data

LOCAL_TZ = ZoneInfo("Australia/Melbourne")
MIN_COMPLETENESS_PCT = 75
LARGE_EXPORT_ROWS = 50_000          # UC3: warn and ask for confirmation above this
MAX_EXPORT_BYTES = 4_000_000        # Vercel's response limit is 4.5 MB: refuse before hitting it
EXCEEDANCE_ROWS_IN_PDF = 200

RESOLUTION_LABELS = {"hour": "Hourly", "day": "Daily", "month": "Monthly", "season": "Seasonal",
                     "raw": "Raw (every reading)"}
DATA_SOURCE = ("Maribyrnong City Council environmental sensors (MCC air-quality units and Libelium units), "
               "cleaned and aggregated by the project data pipeline.")
COMPLETENESS_CAVEAT = (f"A period is valid only if at least {MIN_COMPLETENESS_PCT}% of the expected readings were "
                       "received. Periods marked valid = no are shown for transparency; treat them with caution.")
STATUS_EXCEEDED = "Threshold exceeded"
STATUS_NORMAL = "Normal"
STATUS_NO_STANDARD = "No standard set"

# OWASP CSV injection guidance: a cell starting with one of these is treated as a formula
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

# Same categorical palette as the dashboard (frontend/src/index.css, light mode; D-031)
SERIES_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK_2, MUTED, GRID, INVALID, CRITICAL = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#b4b2a9", "#d03b3b"


# --------------------------------------------------------------------------- gather + render
@dataclass(frozen=True)
class Gathered:
    """Everything one export needs, read in one transaction."""
    result: dict[str, Any]          # data.readings(...)
    exceedances: dict[str, Any]     # data.exceedances(...) for the same filters, oldest first
    land_uses: list[str]
    sensor_codes: list[str]         # codes of the requested sensor ids (empty = all)
    slots: dict[str, int]           # sensor_code -> dashboard colour slot (full sensor list)


def gather(tx: Transaction, variable: str, resolution: str, start: date, end: date, land_uses: list[str],
           sensor_ids: list[int], exclude_flagged: bool) -> Gathered:
    result = data.readings(tx, variable, resolution, start, end, land_uses, sensor_ids, exclude_flagged)
    exceedances = data.exceedances(tx, start, end, variable, land_uses, sensor_ids, "date", "asc", 100_000, 0)
    codes = {s["sensor_id"]: s["sensor_code"] for s in tx.fetch_all(data.SQL_SENSORS)}
    slots = {code: i for i, code in enumerate(sorted(codes.values()))}   # same colour as on the dashboard
    return Gathered(result, exceedances, list(land_uses), [codes.get(i, f"#{i}") for i in sensor_ids], slots)


def render(fmt: str, g: Gathered, now: datetime | None = None) -> bytes:
    """The file for one export format."""
    if fmt == "csv":
        return to_csv(g.result, g.land_uses, g.sensor_codes, now)
    status = sensor_status(g.result, {e["sensor_id"] for e in g.exceedances["items"]})
    return to_pdf(g.result, g.land_uses, g.sensor_codes, g.exceedances, status, g.slots, now)


# --------------------------------------------------------------------------- shared
def safe_cell(value: Any) -> Any:
    """SEC-21: prefix text that a spreadsheet would run as a formula with an apostrophe.
    Numbers are written as numbers (a negative temperature is a value, not a formula)."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def row_count(result: dict[str, Any]) -> int:
    """Number of data rows the export would contain (one per sensor per period)."""
    return sum(len(s["points"]) for s in result["series"])


def file_name(result: dict[str, Any], fmt: str) -> str:
    """Server-chosen download name: only validated values (enum, ISO dates), so no user text."""
    return f"maribyrnong_{result['variable']}_{result['resolution']}_{result['start']}_{result['end']}.{fmt}"


def generated_label(now: datetime | None = None) -> str:
    moment = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    return moment.strftime("%d %b %Y %H:%M ") + (moment.tzname() or "") + " (Melbourne time)"


def filter_summary(result: dict[str, Any], land_uses: list[str], sensor_codes: list[str]) -> list[tuple[str, str]]:
    """The applied filters as label/value pairs, for both formats."""
    return [
        ("Variable", f"{result['label']} ({result['unit']})"),
        ("Resolution", RESOLUTION_LABELS[result["resolution"]]),
        ("Date range", f"{result['start']} to {result['end']} (local time)"),
        ("Land use", ", ".join(land_uses) if land_uses else "All"),
        ("Sensors", ", ".join(sensor_codes) if sensor_codes else "All that measure this variable"),
        ("Flagged readings", "Excluded" if result["exclude_flagged"] else "Included"),
    ]


def sensor_status(result: dict[str, Any], exceeded_sensor_ids: set[int]) -> dict[int, str]:
    """Algorithm 2 status per sensor: any exceedance of a standard for this variable in the
    range -> 'Threshold exceeded'; a variable with no standard says so rather than 'Normal'."""
    has_standard = bool(result["thresholds"])
    return {s["sensor_id"]: (STATUS_EXCEEDED if s["sensor_id"] in exceeded_sensor_ids else
                             STATUS_NORMAL if has_standard else STATUS_NO_STANDARD)
            for s in result["series"]}


def summary_rows(result: dict[str, Any], status: dict[int, str]) -> list[dict[str, Any]]:
    """One row per sensor, sorted by mean, highest first (Algorithm 2); no data last."""
    rows = [{"sensor_code": s["sensor_code"], "sensor_name": s["sensor_name"], "land_use": s["land_use"],
             **s["summary"], "status": status[s["sensor_id"]]} for s in result["series"]]
    return sorted(rows, key=lambda r: (r["mean"] is None, -(r["mean"] or 0), r["sensor_code"]))


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


# --------------------------------------------------------------------------- CSV
def to_csv(result: dict[str, Any], land_uses: list[str], sensor_codes: list[str],
           now: datetime | None = None) -> bytes:
    """Metadata block, a blank line, then one row per sensor per period, units in headers.
    UTF-8 with a byte-order mark so Excel shows °C and µg/m³ correctly."""
    unit = result["unit"]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")

    def write(cells: list[Any]) -> None:
        writer.writerow([safe_cell(c) for c in cells])

    write(["Maribyrnong Environmental Monitor: data export"])
    for label, value in filter_summary(result, land_uses, sensor_codes):
        write([label, value])
    write(["Generated", generated_label(now)])
    write(["Data source", DATA_SOURCE])
    write(["Completeness", COMPLETENESS_CAVEAT])
    for note in result["notes"]:
        write(["Note", note])
    write(["Rows", row_count(result)])
    write([])
    raw = result["resolution"] == "raw"
    header = ["sensor_code", "sensor_name", "land_use", "location_verified",
              "reading_time_local" if raw else "period", f"mean ({unit})", f"min ({unit})", f"max ({unit})",
              "readings", "completeness (%)", "valid"]
    if raw:
        header.append("flagged")
    write(header)
    for s in result["series"]:
        for p in s["points"]:
            cells = [s["sensor_code"], s["sensor_name"], s["land_use"], _yes_no(s["location_verified"]), p["t"],
                     p["mean"], p["min"], p["max"], p["n"], p["completeness_pct"], _yes_no(p["valid"])]
            if raw:
                cells.append(_yes_no(p["flagged"]))
            write(cells)
    return ("﻿" + out.getvalue()).encode("utf-8")


# --------------------------------------------------------------------------- PDF
def _font_paths() -> tuple[Path, Path]:
    """DejaVu Sans ships with matplotlib; it has the characters Helvetica lacks (NO₂, CO₂)."""
    import matplotlib

    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    return base / "DejaVuSans.ttf", base / "DejaVuSans-Bold.ttf"


def _register_fonts() -> None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if "DejaVu" in pdfmetrics.getRegisteredFontNames():
        return
    regular, bold = _font_paths()
    pdfmetrics.registerFont(TTFont("DejaVu", str(regular)))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(bold)))


def _import_pyplot():
    # Vercel's file system is read-only except /tmp: matplotlib needs a writable cache dir
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib"))
    import matplotlib

    matplotlib.use("Agg")   # no display on a server
    import matplotlib.pyplot as plt

    return plt


def chart_png(result: dict[str, Any], slots: dict[str, int]) -> bytes:
    """Line chart of period means, one line per sensor in its dashboard colour. Periods
    below 75% completeness are grey hollow markers; daily standards are dashed red lines."""
    plt = _import_pyplot()
    buckets = sorted({p["t"] for s in result["series"] for p in s["points"]})
    index = {b: i for i, b in enumerate(buckets)}
    fig, ax = plt.subplots(figsize=(7.2, 3.3), dpi=150)
    try:
        many = len(buckets) > 16
        for s in result["series"]:
            colour = SERIES_COLOURS[slots.get(s["sensor_code"], 0) % len(SERIES_COLOURS)]
            xs = [index[p["t"]] for p in s["points"]]
            ys = [p["mean"] if p["valid"] else None for p in s["points"]]
            ax.plot(xs, [float("nan") if y is None else y for y in ys], color=colour, linewidth=1.6,
                    marker=None if many else "o", markersize=3.5, label=s["sensor_code"])
            bad = [(index[p["t"]], p["mean"]) for p in s["points"] if not p["valid"] and p["mean"] is not None]
            if bad:
                ax.scatter([x for x, _ in bad], [y for _, y in bad], s=8, facecolors="none", edgecolors=INVALID,
                           linewidths=0.7, zorder=3)
        if result["resolution"] == "day":
            for t in result["thresholds"]:
                if t["period"] == "day":
                    ax.axhline(float(t["value"]), color=CRITICAL, linewidth=1, linestyle="--")
                    ax.annotate(t["label"], xy=(0, float(t["value"])), xytext=(2, 3), textcoords="offset points",
                                fontsize=6.5, color=CRITICAL)
        step = max(1, len(buckets) // 8)
        ax.set_xticks(range(0, len(buckets), step))
        ax.set_xticklabels([buckets[i][:16] for i in range(0, len(buckets), step)], rotation=30, ha="right",
                           fontsize=6.5, color=INK_2)
        ax.tick_params(axis="y", labelsize=7, colors=INK_2)
        ax.set_ylabel(f"{result['label']} ({result['unit']})", fontsize=7.5, color=INK_2)
        ax.grid(axis="y", color=GRID, linewidth=0.6)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.legend(fontsize=6.5, frameon=False, ncol=min(6, len(result["series"])), loc="upper center",
                  bbox_to_anchor=(0.5, 1.13))
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        return buf.getvalue()
    finally:
        plt.close(fig)


def _fmt(value: Any, unit: str = "", places: int = 1) -> str:
    if value is None:
        return "No data"
    text = f"{float(value):.{places}f}"
    return f"{text}{unit}" if unit == "%" else f"{text} {unit}".strip()


def to_pdf(result: dict[str, Any], land_uses: list[str], sensor_codes: list[str], exceedances: dict[str, Any],
           status: dict[int, str], slots: dict[str, int], now: datetime | None = None) -> bytes:
    """Title, filters, summary table (mean descending, with status), chart, exceedance list,
    data-quality notes and 'Page X of Y' on every page."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _register_fonts()
    unit = result["unit"]
    body = ParagraphStyle("body", fontName="DejaVu", fontSize=8.5, leading=11.5, textColor=colors.HexColor(INK))
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=10, textColor=colors.HexColor(INK_2))
    h1 = ParagraphStyle("h1", parent=body, fontName="DejaVu-Bold", fontSize=15, leading=19, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=body, fontName="DejaVu-Bold", fontSize=10.5, leading=14, spaceBefore=8,
                        spaceAfter=4)

    def esc(text: Any) -> str:   # Paragraph understands mini-markup: escape every value
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def table(rows: list[list[Any]], widths: list[float], numeric_from: int | None = None) -> Table:
        cells = [[Paragraph(esc(c), small if r else ParagraphStyle("th", parent=small, fontName="DejaVu-Bold",
                                                                    textColor=colors.HexColor(INK)))
                  for c in row] for r, row in enumerate(rows)]
        t = Table(cells, colWidths=widths, repeatRows=1)
        style = [("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(INK_2)),
                 ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor(GRID)),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        t.setStyle(TableStyle(style))
        return t

    story: list[Any] = [
        Paragraph(f"{esc(result['label'])} report", h1),
        Paragraph("Maribyrnong Environmental Monitor · generated " + esc(generated_label(now)), small),
        Spacer(1, 6),
        table([["Filter", "Value"]] + [[k, v] for k, v in filter_summary(result, land_uses, sensor_codes)],
              [35 * mm, 140 * mm]),
        Paragraph("Summary by sensor (highest mean first)", h2),
    ]
    summary = summary_rows(result, status)
    story.append(table(
        [["Sensor", "Land use", f"Mean ({unit})", f"Min ({unit})", f"Max ({unit})", "Complete (%)", "Valid periods",
          "Status"]]
        + [[f"{r['sensor_code']} · {r['sensor_name']}", r["land_use"], _fmt(r["mean"]), _fmt(r["min"]),
            _fmt(r["max"]), _fmt(r["completeness_pct"]), f"{r['valid_buckets']} of {r['buckets']}", r["status"]]
           for r in summary],
        [42 * mm, 22 * mm, 17 * mm, 17 * mm, 17 * mm, 22 * mm, 17 * mm, 20 * mm]))
    story.append(Paragraph(
        "Mean: average over every period with data, weighted by the number of readings. Min and Max: the lowest "
        "and highest single readings. Complete: average share of expected readings received. Status: "
        "“Threshold exceeded” means the sensor exceeded a standard for this variable on at least one day in the "
        "range (see the exceedance list).", small))

    story.append(Paragraph(f"{esc(result['label'])} over time ({RESOLUTION_LABELS[result['resolution']].lower()})",
                           h2))
    png = chart_png(result, slots)
    story.append(Image(io.BytesIO(png), width=175 * mm, height=175 * mm * 3.3 / 7.2))
    story.append(Paragraph("Grey hollow markers: periods below 75% completeness (not joined into the line). "
                           "Dashed red line: a 24-hour standard (daily view only).", small))

    story.append(Paragraph("Threshold exceedances", h2))
    items = exceedances["items"][:EXCEEDANCE_ROWS_IN_PDF]
    if items:
        story.append(table(
            [["Date", "Sensor", "Standard", "Statistic", "Observed", "Threshold"]]
            + [[e["date_local"], e["sensor_code"], e["label"], e["statistic"], _fmt(e["observed_value"], e["unit"]),
                f"{e['operator']} {_fmt(e['threshold_value'], e['unit'])}"] for e in items],
            [22 * mm, 22 * mm, 50 * mm, 25 * mm, 28 * mm, 28 * mm]))
        if exceedances["total"] > len(items):
            story.append(Paragraph(f"Showing the first {len(items)} of {exceedances['total']} exceedances. "
                                   "Export the CSV or narrow the filters for the full list.", small))
    else:
        story.append(Paragraph("No threshold exceedances for these filters.", body))

    story.append(Paragraph("Data quality", h2))
    for note in [COMPLETENESS_CAVEAT, *result["notes"], f"Data source: {DATA_SOURCE}"]:
        story.append(Paragraph("• " + esc(note), small))

    class NumberedCanvas(rl_canvas.Canvas):
        """Two-pass canvas so every page can say 'Page X of Y'."""

        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self._pages: list[dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802 - reportlab API
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.setFont("DejaVu", 7.5)
                self.setFillColor(colors.HexColor(MUTED))
                self.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {self._pageNumber} of {total}")
                self.drawString(18 * mm, 10 * mm, "Maribyrnong Environmental Monitor")
                super().showPage()
            super().save()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=18 * mm, title=f"{result['label']} report",
                            author="Maribyrnong Environmental Monitor", subject="Environmental data export")
    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()
