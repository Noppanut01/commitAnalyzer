from collections import Counter
from datetime import datetime

from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.series import DataPoint
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from models import Category, CommitAnalysis, CommitInfo, Severity, Confidence

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

NAVY       = "1F3864"
HEADER_BG  = "2E75B6"
HEADER_FG  = "FFFFFF"
TAB_BLUE   = "2E75B6"
TAB_RED    = "C00000"

# KPI card colours  (bg, value_text, label_text)
KPI_BLUE  = ("1D4ED8", "FFFFFF", "BFDBFE")
KPI_RED   = ("DC2626", "FFFFFF", "FECACA")
KPI_AMBER = ("D97706", "FFFFFF", "FDE68A")
KPI_GREEN = ("059669", "FFFFFF", "A7F3D0")

# Row tints by category
CATEGORY_FILLS = {
    Category.BUG_FIX:  "FFEBEE",
    Category.FEATURE:  "E8F5E9",
    Category.REFACTOR: "E3F2FD",
    Category.CHORE:    "FFF8E1",
    Category.UNCLEAR:  "F3E5F5",
}

# Short description for each category (shown in Summary sheet)
CATEGORY_DESC = {
    Category.BUG_FIX:  "Fixes defects, crashes, or incorrect behavior in existing code",
    Category.FEATURE:  "Adds new functionality or capabilities to the system",
    Category.REFACTOR: "Restructures code without changing external behavior",
    Category.CHORE:    "CI config, dependencies, docs, tests, version bumps",
    Category.UNCLEAR:  "Cannot determine intent — message too vague or ambiguous",
}

SEVERITY_FILLS = {
    "Critical": ("C00000", "FFFFFF"),
    "Major":    ("FF0000", "FFFFFF"),
    "Minor":    ("FFC000", "000000"),
    "N/A":      ("BFBFBF", "FFFFFF"),
}
CONFIDENCE_FILLS = {
    "High":   ("70AD47", "FFFFFF"),
    "Medium": ("FFC000", "000000"),
    "Low":    ("FF0000", "FFFFFF"),
}
BUG_FIX_YES_FILL = PatternFill(start_color="C00000", end_color="C00000", fill_type="solid")
BUG_FIX_NO_FILL  = PatternFill(start_color="70AD47", end_color="70AD47", fill_type="solid")

THIN_SIDE   = Side(style="thin", color="D9D9D9")
THIN_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
NO_BORDER   = Border()

HEADER_FONT  = Font(bold=True, color=HEADER_FG, size=10)
HEADER_FILL  = PatternFill(start_color=HEADER_BG, end_color=HEADER_BG, fill_type="solid")
LABEL_FONT   = Font(bold=True, size=10, color="333333")
VALUE_FONT   = Font(size=10, color="333333")
TITLE_FONT   = Font(bold=True, size=16, color=NAVY)
SUB_FONT     = Font(size=11, color="666666")
SECTION_FONT = Font(bold=True, size=11, color=NAVY)
SECTION_FILL = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")

CENTER = Alignment(horizontal="center", vertical="center")
LEFT   = Alignment(horizontal="left",   vertical="center")
WRAP   = Alignment(wrap_text=True,      vertical="top")


# ---------------------------------------------------------------------------
# Shared style helpers
# ---------------------------------------------------------------------------

def _fill(hex_color: str) -> PatternFill:
    return PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")


def _hdr(ws, row: int, col: int, value):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font      = HEADER_FONT
    cell.fill      = HEADER_FILL
    cell.border    = THIN_BORDER
    cell.alignment = CENTER
    return cell


def _val(ws, row: int, col: int, value, bold=False, align=LEFT, fill=None):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font      = Font(bold=bold, size=10, color="333333")
    cell.border    = THIN_BORDER
    cell.alignment = align
    if fill:
        cell.fill = fill
    return cell


def _section_title(ws, row: int, title: str, span: int) -> int:
    cell = ws.cell(row=row, column=1, value=title)
    cell.font      = SECTION_FONT
    cell.fill      = SECTION_FILL
    cell.border    = THIN_BORDER
    cell.alignment = LEFT
    if span > 1:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
        for c in range(2, span + 1):
            ws.cell(row=row, column=c).fill   = SECTION_FILL
            ws.cell(row=row, column=c).border = THIN_BORDER
    return row + 1


def _info_row(ws, row: int, key: str, value, span: int = 3) -> int:
    cell_k = ws.cell(row=row, column=1, value=key)
    cell_k.font      = LABEL_FONT
    cell_k.alignment = LEFT
    cell_k.border    = THIN_BORDER
    cell_k.fill      = _fill("F5F5F5")

    cell_v = ws.cell(row=row, column=2, value=value)
    cell_v.font      = VALUE_FONT
    cell_v.alignment = LEFT
    cell_v.border    = THIN_BORDER

    if span > 1:
        end_col = 1 + span
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=end_col)
        for c in range(3, end_col + 1):
            ws.cell(row=row, column=c).border = THIN_BORDER
    return row + 1


def _badge(ws, row: int, col: int, value: str, color_map: dict):
    bg, fg = color_map.get(value, ("BFBFBF", "FFFFFF"))
    cell = ws.cell(row=row, column=col, value=value)
    cell.font      = Font(bold=True, size=10, color=fg)
    cell.fill      = _fill(bg)
    cell.alignment = CENTER
    cell.border    = THIN_BORDER
    return cell


def _auto_width(ws, max_col: int, cap: int = 60):
    for col_idx in range(1, max_col + 1):
        letter  = get_column_letter(col_idx)
        max_len = 10
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, min(len(str(cell.value)), cap))
        ws.column_dimensions[letter].width = min(max_len + 4, cap)


# ---------------------------------------------------------------------------
# KPI card  (3 rows tall × width cols wide)
# ---------------------------------------------------------------------------

def _kpi_card(ws, top_row: int, left_col: int,
              label: str, value, sub: str = "",
              colors: tuple = KPI_BLUE, width: int = 3):
    bg, fg, label_fg = colors
    right_col = left_col + width - 1

    for r_off in range(3):
        ws.merge_cells(start_row=top_row + r_off, start_column=left_col,
                       end_row=top_row + r_off,   end_column=right_col)
        for c in range(left_col, right_col + 1):
            ws.cell(row=top_row + r_off, column=c).fill   = _fill(bg)
            ws.cell(row=top_row + r_off, column=c).border = NO_BORDER

    # label row
    c = ws.cell(row=top_row, column=left_col, value=label.upper())
    c.font = Font(bold=True, size=8, color=label_fg)
    c.fill = _fill(bg)
    c.alignment = CENTER

    # value row
    c = ws.cell(row=top_row + 1, column=left_col, value=value)
    c.font = Font(bold=True, size=24, color=fg)
    c.fill = _fill(bg)
    c.alignment = CENTER

    # sub-label row
    c = ws.cell(row=top_row + 2, column=left_col, value=sub)
    c.font = Font(size=8, color=label_fg)
    c.fill = _fill(bg)
    c.alignment = CENTER

    ws.row_dimensions[top_row].height     = 16
    ws.row_dimensions[top_row + 1].height = 36
    ws.row_dimensions[top_row + 2].height = 16


# ---------------------------------------------------------------------------
# Sheet 1 — Summary Dashboard
# ---------------------------------------------------------------------------

def _build_summary(wb: Workbook, commits: list[CommitInfo],
                   analyses: list[CommitAnalysis],
                   sprint_name: str, sprint_start: str, sprint_end: str):
    ws = wb.active
    ws.title = "Summary Dashboard"
    ws.sheet_properties.tabColor = TAB_BLUE

    bug_analyses = [a for a in analyses if a.is_bug_fix]
    total        = len(analyses)
    bug_count    = len(bug_analyses)
    clean_count  = total - bug_count   # Feature + Refactor + Chore + Unclear
    bug_pct      = round(bug_count / total * 100, 1) if total else 0

    # ── Title banner ──────────────────────────────────────────────────────
    row = 1
    ws.row_dimensions[row].height = 36
    for c in range(1, 13):
        ws.cell(row=row, column=c).fill = _fill(NAVY)
    cell = ws.cell(row=row, column=1,
                   value=f"Sprint Bug Fix Analyzer — {sprint_name}")
    cell.font      = Font(bold=True, size=18, color="FFFFFF")
    cell.alignment = Alignment(vertical="center")
    ws.merge_cells("A1:L1")

    row = 2
    ws.row_dimensions[row].height = 20
    for c in range(1, 13):
        ws.cell(row=row, column=c).fill = _fill(NAVY)
    cell = ws.cell(row=row, column=1,
                   value=f"Period: {sprint_start}  →  {sprint_end}    |    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    cell.font      = Font(size=10, color="CCCCCC")
    cell.alignment = LEFT
    ws.merge_cells("A2:L2")

    # ── KPI Cards (rows 4-6) ──────────────────────────────────────────────
    row = 3
    ws.row_dimensions[row].height = 8   # spacer

    _kpi_card(ws, top_row=4, left_col=1,  label="Total Commits",
              value=total,          colors=KPI_BLUE)
    _kpi_card(ws, top_row=4, left_col=4,  label="Bug Fixes",
              value=bug_count,      colors=KPI_RED)
    _kpi_card(ws, top_row=4, left_col=7,  label="Bug Fix Rate",
              value=f"{bug_pct}%",  colors=KPI_AMBER)
    _kpi_card(ws, top_row=4, left_col=10,
              label="Non-Bug-Fix",
              value=clean_count,
              sub="Feature / Refactor / Chore",
              colors=KPI_GREEN)

    row = 7
    ws.row_dimensions[row].height = 10   # spacer after KPI

    # ── Sprint Overview ────────────────────────────────────────────────────
    row = 8
    row = _section_title(ws, row, "Sprint Overview", 4)
    row = _info_row(ws, row, "Sprint Name",     sprint_name)
    row = _info_row(ws, row, "Date Range",      f"{sprint_start}  →  {sprint_end}")
    row = _info_row(ws, row, "Total Commits",   total)
    row = _info_row(ws, row, "Bug Fix Commits", f"{bug_count}  ({bug_pct}%)")
    row = _info_row(ws, row, "Non-Bug-Fix",     f"{clean_count}  (Feature / Refactor / Chore / Unclear)")

    row += 1   # spacer

    # ── Bug Fix by Developer ───────────────────────────────────────────────
    commit_map = {c.commit_id: c for c in commits}
    dev_bug:   Counter = Counter()
    dev_total: Counter = Counter()
    for a in analyses:
        author = commit_map.get(
            a.commit_id, CommitInfo("", "Unknown", "", "", "")
        ).author
        dev_total[author] += 1
        if a.is_bug_fix:
            dev_bug[author] += 1

    row = _section_title(ws, row, "Bug Fix by Developer", 4)
    _hdr(ws, row, 1, "Developer")
    _hdr(ws, row, 2, "Total Commits")
    _hdr(ws, row, 3, "Bug Fixes")
    _hdr(ws, row, 4, "Bug Fix %")
    row += 1

    i = 0
    devs_sorted = sorted(dev_total.keys(), key=lambda d: (-dev_bug.get(d, 0), d))
    for i, dev in enumerate(devs_sorted, 1):
        bugs      = dev_bug.get(dev, 0)
        total_dev = dev_total[dev]
        pct       = round(bugs / total_dev * 100, 1) if total_dev else 0
        fill      = _fill("FFF8F8") if i % 2 == 0 else None
        _val(ws, row, 1, dev,           fill=fill)
        _val(ws, row, 2, total_dev,     align=CENTER, fill=fill)
        _val(ws, row, 3, bugs,          align=CENTER, fill=fill,
             bold=(bugs > 0))
        _val(ws, row, 4, f"{pct}%",     align=CENTER, fill=fill)
        row += 1

    row += 1   # spacer

    # ── Category Breakdown ────────────────────────────────────────────────
    cat_counter: Counter = Counter(a.category for a in analyses)
    categories = [c for c in Category]

    row = _section_title(ws, row, "Category Breakdown", 4)
    _hdr(ws, row, 1, "Category")
    _hdr(ws, row, 2, "Count")
    _hdr(ws, row, 3, "%")
    _hdr(ws, row, 4, "Description")
    row += 1
    cat_data_start = row
    for cat in categories:
        cnt  = cat_counter.get(cat, 0)
        pct  = round(cnt / total * 100, 1) if total else 0
        tint = CATEGORY_FILLS.get(cat, "FFFFFF")
        fill = _fill(tint)
        desc = CATEGORY_DESC.get(cat, "")
        _val(ws, row, 1, cat.value,  fill=fill, bold=True)
        _val(ws, row, 2, cnt,        align=CENTER, fill=fill)
        _val(ws, row, 3, f"{pct}%",  align=CENTER, fill=fill)
        cell = ws.cell(row=row, column=4, value=desc)
        cell.font      = Font(size=9, color="555555", italic=True)
        cell.border    = THIN_BORDER
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        cell.fill      = fill
        ws.row_dimensions[row].height = 22
        row += 1
    cat_data_end = row - 1

    row += 1   # spacer

    # ── Severity Breakdown ────────────────────────────────────────────────
    sev_counter: Counter = Counter(
        a.severity.value for a in analyses if a.is_bug_fix
    )

    row = _section_title(ws, row, "Severity Breakdown  (Bug Fixes Only)", 3)
    _hdr(ws, row, 1, "Severity")
    _hdr(ws, row, 2, "Count")
    _hdr(ws, row, 3, "% of Bug Fixes")
    row += 1
    for sev in ("Critical", "Major", "Minor"):
        cnt  = sev_counter.get(sev, 0)
        pct  = round(cnt / bug_count * 100, 1) if bug_count else 0
        bg, fg = SEVERITY_FILLS.get(sev, ("BFBFBF", "FFFFFF"))
        cell = ws.cell(row=row, column=1, value=sev)
        cell.font      = Font(bold=True, size=10, color=fg)
        cell.fill      = _fill(bg)
        cell.border    = THIN_BORDER
        cell.alignment = LEFT
        _val(ws, row, 2, cnt,        align=CENTER)
        _val(ws, row, 3, f"{pct}%",  align=CENTER)
        row += 1

    row += 1   # spacer

    # ── Confidence Breakdown (Bug Fixes Only) ─────────────────────────────
    conf_counter: Counter = Counter(
        a.confidence.value for a in analyses if a.is_bug_fix
    )

    row = _section_title(ws, row, "Confidence Breakdown  (Bug Fixes Only)", 3)
    _hdr(ws, row, 1, "Confidence")
    _hdr(ws, row, 2, "Count")
    _hdr(ws, row, 3, "% of Bug Fixes")
    row += 1
    for conf_val, note in (
        ("High",   "Clear signal — fix keyword + matching diff"),
        ("Medium", "Probable fix — message or diff has some ambiguity"),
        ("Low",    "Weak signal — diff pattern only, no fix keyword"),
    ):
        cnt  = conf_counter.get(conf_val, 0)
        pct  = round(cnt / bug_count * 100, 1) if bug_count else 0
        bg, fg = CONFIDENCE_FILLS.get(conf_val, ("BFBFBF", "FFFFFF"))
        cell = ws.cell(row=row, column=1, value=conf_val)
        cell.font      = Font(bold=True, size=10, color=fg)
        cell.fill      = _fill(bg)
        cell.border    = THIN_BORDER
        cell.alignment = LEFT
        _val(ws, row, 2, cnt,        align=CENTER)
        _val(ws, row, 3, f"{pct}%",  align=CENTER)
        row += 1

    # ── Charts  ───────────────────────────────────────────────────────────
    # Charts are anchored in col F+ (tables use A-D), starting below KPI (row 8)
    _add_pie_chart(ws, bug_count, clean_count, anchor="F8")
    _add_bar_chart(ws, [c.value for c in categories],
                   [cat_counter.get(c, 0) for c in categories],
                   cat_data_start, cat_data_end,
                   anchor="F30")

    # Column widths
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 50
    for col in range(6, 13):
        ws.column_dimensions[get_column_letter(col)].width = 13


# ---------------------------------------------------------------------------
# Pie chart
# ---------------------------------------------------------------------------

def _add_pie_chart(ws, bug_count: int, non_bug_count: int, anchor: str):
    dr = ws.max_row + 3
    ws.cell(row=dr,     column=1, value="Bug Fix")
    ws.cell(row=dr + 1, column=1, value="Non-Bug-Fix")
    ws.cell(row=dr,     column=2, value=bug_count)
    ws.cell(row=dr + 1, column=2, value=non_bug_count)

    chart = PieChart()
    chart.title  = "Bug Fix vs Non-Bug-Fix"
    chart.style  = 10
    chart.width  = 14
    chart.height = 10

    labels = Reference(ws, min_col=1, min_row=dr, max_row=dr + 1)
    data   = Reference(ws, min_col=2, min_row=dr, max_row=dr + 1)
    chart.add_data(data)
    chart.set_categories(labels)
    chart.series[0].title = None

    for idx, color in enumerate(["C00000", "70AD47"]):
        pt = DataPoint(idx=idx)
        pt.graphicalProperties.solidFill = color
        chart.series[0].dPt.append(pt)

    ws.add_chart(chart, anchor)


# ---------------------------------------------------------------------------
# Bar chart
# ---------------------------------------------------------------------------

def _add_bar_chart(ws, categories: list[str], counts: list[int],
                   data_start: int, data_end: int, anchor: str):
    chart = BarChart()
    chart.type          = "col"
    chart.title         = "Commits by Category"
    chart.style         = 10
    chart.width         = 18
    chart.height        = 12
    chart.y_axis.title  = "Count"
    chart.x_axis.title  = "Category"

    data = Reference(ws, min_col=2, min_row=data_start - 1, max_row=data_end)
    cats = Reference(ws, min_col=1, min_row=data_start,     max_row=data_end)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.shape = 4

    ws.add_chart(chart, anchor)


# ---------------------------------------------------------------------------
# Sheet 2 & 3 — Commit Details
# ---------------------------------------------------------------------------

DETAIL_COLS = [
    ("#",                    5),
    ("Date",                12),
    ("Commit ID",           10),
    ("Author",              22),
    ("Message",             42),
    ("Bug Fix",              9),
    ("Category",            14),
    ("Bug Type",            14),
    ("Severity",            11),
    ("Confidence",          12),
    ("Files Changed",       28),
    ("Keyword Signals / Reasoning", 52),
]


def _build_details(wb: Workbook, commits: list[CommitInfo],
                   analyses: list[CommitAnalysis],
                   sheet_name: str, tab_color: str,
                   bug_fix_only: bool = False,
                   sprint_name: str = ""):
    ws = wb.create_sheet(title=sheet_name)
    ws.sheet_properties.tabColor = tab_color

    cols = DETAIL_COLS.copy()
    if bug_fix_only:
        cols.append(("Sprint", 16))

    commit_map = {c.commit_id: c for c in commits}
    items: list[CommitAnalysis] = [
        a for a in analyses if not bug_fix_only or a.is_bug_fix
    ]

    # ── Header ────────────────────────────────────────────────────────────
    row = 1
    for col_idx, (label, _) in enumerate(cols, 1):
        _hdr(ws, row, col_idx, label)
    ws.row_dimensions[row].height = 24
    row += 1

    # ── Data rows ─────────────────────────────────────────────────────────
    for seq, analysis in enumerate(items, 1):
        commit   = commit_map.get(analysis.commit_id)
        date_str = commit.date[:10] if commit else ""
        short_id = analysis.commit_id[:7]
        author   = commit.author   if commit else ""
        message  = commit.message  if commit else ""

        tint     = CATEGORY_FILLS.get(analysis.category, "FFFFFF")
        row_fill = _fill(tint)

        def _r(col_idx, value, align=LEFT, fill=row_fill, bold=False):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.font      = Font(bold=bold, size=10, color="333333")
            cell.border    = THIN_BORDER
            cell.alignment = align
            cell.fill      = fill

        _r(1,  seq,      align=CENTER)
        _r(2,  date_str, align=CENTER)
        _r(3,  short_id, align=CENTER)
        _r(4,  author)

        # Message — wrap
        cell = ws.cell(row=row, column=5, value=message)
        cell.font      = VALUE_FONT
        cell.border    = THIN_BORDER
        cell.alignment = WRAP
        cell.fill      = row_fill

        # Bug Fix badge
        bf_label = "Yes" if analysis.is_bug_fix else "No"
        cell = ws.cell(row=row, column=6, value=bf_label)
        cell.font      = Font(bold=True, size=10, color="FFFFFF")
        cell.fill      = BUG_FIX_YES_FILL if analysis.is_bug_fix else BUG_FIX_NO_FILL
        cell.border    = THIN_BORDER
        cell.alignment = CENTER

        _r(7, analysis.category.value)
        _r(8, analysis.bug_type.value)

        _badge(ws, row, 9,  analysis.severity.value,   SEVERITY_FILLS)
        _badge(ws, row, 10, analysis.confidence.value, CONFIDENCE_FILLS)

        # Files changed
        files_str = "\n".join(analysis.files_changed[:10])
        if len(analysis.files_changed) > 10:
            files_str += f"\n+{len(analysis.files_changed) - 10} more…"
        cell = ws.cell(row=row, column=11, value=files_str)
        cell.font      = Font(size=9, color="444444")
        cell.border    = THIN_BORDER
        cell.alignment = WRAP
        cell.fill      = row_fill

        # Keyword Signals / Reasoning
        cell = ws.cell(row=row, column=12, value=analysis.reasoning)
        cell.font      = VALUE_FONT
        cell.border    = THIN_BORDER
        cell.alignment = WRAP
        cell.fill      = row_fill

        if bug_fix_only:
            _r(13, sprint_name)

        ws.row_dimensions[row].height = max(30, min(len(message) // 3, 80))
        row += 1

    # ── Auto-filter + freeze header ───────────────────────────────────────
    last_col = get_column_letter(len(cols))
    ws.auto_filter.ref = f"A1:{last_col}1"
    ws.freeze_panes = "A2"

    # ── Column widths ─────────────────────────────────────────────────────
    for col_idx, (_, w) in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = w


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_report(
    commits: list[CommitInfo],
    analyses: list[CommitAnalysis],
    sprint_name: str,
    sprint_start: str,
    sprint_end: str,
    filepath: str,
) -> None:
    wb = Workbook()

    _build_summary(wb, commits, analyses, sprint_name, sprint_start, sprint_end)
    _build_details(wb, commits, analyses, "Commit Details", TAB_BLUE,
                   bug_fix_only=False, sprint_name=sprint_name)
    _build_details(wb, commits, analyses, "Bug Fix Only", TAB_RED,
                   bug_fix_only=True,  sprint_name=sprint_name)

    try:
        wb.save(filepath)
    except PermissionError:
        raise PermissionError(
            f"Cannot save '{filepath}' — please close the file in Excel and try again."
        )
