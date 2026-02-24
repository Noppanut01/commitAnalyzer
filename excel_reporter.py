import re
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
HEADER_BG  = "4472C4"   # softer blue
HEADER_FG  = "FFFFFF"
TAB_BLUE   = "4472C4"
TAB_RED    = "C0504D"   # softer red

# KPI card colours  (bg, value_text, label_text)
KPI_BLUE  = ("4472C4", "FFFFFF", "BDD7EE")
KPI_RED   = ("C0504D", "FFFFFF", "F4CCCC")
KPI_AMBER = ("D98C3A", "FFFFFF", "FCE4CD")
KPI_GREEN = ("5DAB4F", "FFFFFF", "C9EBC5")

# Row tints by category
CATEGORY_FILLS = {
    Category.BUG_FIX:  "FCE4E4",   # soft pink
    Category.FEATURE:  "E8F5E9",   # soft green
    Category.REFACTOR: "E3F2FD",   # soft blue
    Category.CHORE:    "FFF8E1",   # soft yellow
    Category.UNCLEAR:  "F3E5F5",   # soft purple
}

# Short description for each category (shown in Summary sheet)
CATEGORY_DESC = {
    Category.BUG_FIX:  "แก้ไขข้อบกพร่อง, crash, หรือพฤติกรรมที่ไม่ถูกต้องในโค้ดที่มีอยู่",
    Category.FEATURE:  "เพิ่มฟังก์ชันการทำงานหรือความสามารถใหม่ให้กับระบบ",
    Category.REFACTOR: "ปรับโครงสร้างโค้ดโดยไม่เปลี่ยนพฤติกรรมภายนอก",
    Category.CHORE:    "งานบำรุงรักษา — อัปเดต dependency, CI/CD pipeline, เอกสาร และ test (ไม่กระทบ business logic)",
    Category.UNCLEAR:  "ไม่สามารถระบุเจตนาได้ — commit message ไม่ชัดเจนหรือกำกวม",
}


SEVERITY_FILLS = {
    "Critical": ("A93226", "FFFFFF"),   # dark muted red
    "Major":    ("E05C55", "FFFFFF"),   # soft red  (was FF0000)
    "Minor":    ("F5A623", "000000"),   # warm amber (was FFC000)
    "N/A":      ("AAAAAA", "FFFFFF"),   # neutral grey
}
CONFIDENCE_FILLS = {
    "High":   ("5CB85C", "FFFFFF"),   # pleasant green
    "Medium": ("F0AD4E", "000000"),   # pleasant amber
    "Low":    ("D9534F", "FFFFFF"),   # soft red  (was FF0000)
}
BUG_FIX_YES_FILL = PatternFill(start_color="5CB85C", end_color="5CB85C", fill_type="solid")  # green
BUG_FIX_NO_FILL  = PatternFill(start_color="D9534F", end_color="D9534F", fill_type="solid")  # soft red

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

MSG_MAX_CHARS  = 100        # max message chars in Excel cells (fits ≤ 2 wrapped lines)
MERGE_LIGHT_BG = "EBF5F7"  # very light teal for merge-commit rows
PR_CHILD_BG    = "F4FBFC"  # barely-there teal for PR child rows
PR_TAB_COLOR   = "2C5F6B"  # teal tab for PR detail sheets


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


def _truncate(text: str, n: int = MSG_MAX_CHARS) -> str:
    """Truncate text to n chars with ellipsis, keeping cells to ≤ 2 wrapped lines."""
    if not text or len(text) <= n:
        return text
    return text[:n].rstrip() + "…"


def _pr_sheet_name(merge_sha: str, message: str = "") -> str:
    """Return the Excel sheet name for a PR's detail sheet.

    Prefers the numeric Azure DevOps PR ID parsed from the merge commit message
    (e.g. "Merged PR 6555: fix: ..." → "PR-6555").
    Falls back to the first 7 chars of the merge commit SHA.
    """
    if message:
        m = re.match(r'Merged PR\s+(\d+)', message, re.IGNORECASE)
        if m:
            return f"PR-{m.group(1)}"
    return f"PR-{merge_sha[:7]}"


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

    for idx, color in enumerate(["C0504D", "5DAB4F"]):
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
    ("#",                    5),   # col 1
    ("Date",                12),   # col 2
    ("Commit ID",           10),   # col 3
    ("Source PR",           10),   # col 4 — merge commit SHA this came from (empty = direct)
    ("Author",              22),   # col 5
    ("Message",             42),   # col 6
    ("Bug Fix",              9),   # col 7
    ("Category",            14),   # col 8
    ("Bug Type",            14),   # col 9
    ("Severity",            11),   # col 10
    ("Confidence",          12),   # col 11
    ("Files Changed",       28),   # col 12
    ("Keyword Signals / Reasoning", 52),  # col 13
]


def _build_details(wb: Workbook, commits: list[CommitInfo],
                   analyses: list[CommitAnalysis],
                   sheet_name: str, tab_color: str,
                   bug_fix_only: bool = False,
                   sprint_name: str = "",
                   pr_sheet_map: dict | None = None):
    """Build a commit-detail sheet.

    pr_sheet_map: {merge_commit_id (full sha) -> excel_sheet_name}
    When provided, merge-commit rows get a hyperlink to their PR detail sheet.
    """
    ws = wb.create_sheet(title=sheet_name)
    ws.sheet_properties.tabColor = tab_color

    cols = DETAIL_COLS.copy()
    if bug_fix_only:
        cols.append(("Sprint", 16))

    commit_map = {c.commit_id: c for c in commits}
    items: list[CommitAnalysis] = [
        a for a in analyses if not bug_fix_only or a.is_bug_fix
    ]

    # ── Header row ────────────────────────────────────────────────────────
    row = 1
    for col_idx, (label, _) in enumerate(cols, 1):
        _hdr(ws, row, col_idx, label)
    ws.row_dimensions[row].height = 24
    row += 1

    # ── Data rows ─────────────────────────────────────────────────────────
    for seq, analysis in enumerate(items, 1):
        commit     = commit_map.get(analysis.commit_id)
        date_str   = commit.date[:10]          if commit else ""
        short_id   = analysis.commit_id[:7]
        author     = commit.author             if commit else ""
        message    = commit.message            if commit else ""
        is_merge   = commit.is_merge_commit    if commit else False
        from_merge = commit.from_merge_commit  if commit else ""

        # Row fill — merge gets a very light teal tint, PR child slightly lighter,
        # direct commits use category colour.  All use dark text (no white-on-dark).
        if is_merge:
            row_fill = _fill(MERGE_LIGHT_BG)
        elif from_merge:
            row_fill = _fill(PR_CHILD_BG)
        else:
            row_fill = _fill(CATEGORY_FILLS.get(analysis.category, "FFFFFF"))

        text_color = "333333"
        row_height = 30   # fits ≤ 2 wrapped lines at 10 pt

        # ── inner helper ──────────────────────────────────────────────────
        def _r(col_idx, value, align=LEFT, fill=row_fill, bold=False, color=text_color):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.font      = Font(bold=bold, size=10, color=color)
            cell.border    = THIN_BORDER
            cell.alignment = align
            cell.fill      = fill

        _r(1, seq, align=CENTER)
        _r(2, date_str, align=CENTER)
        _r(3, short_id, align=CENTER)

        # ── Source PR column ──────────────────────────────────────────────
        #   • merge commit  → hyperlink to its PR detail sheet
        #   • PR child      → parent merge SHA (small green badge)
        #   • direct commit → em-dash
        if is_merge:
            target_sheet = (pr_sheet_map or {}).get(analysis.commit_id, "")
            if target_sheet:
                cell = ws.cell(row=row, column=4, value=target_sheet)
                cell.hyperlink  = f"#'{target_sheet}'!A1"
                cell.font       = Font(bold=True, size=10, color="0563C1",
                                       underline="single")
                cell.border     = THIN_BORDER
                cell.alignment  = CENTER
                cell.fill       = row_fill
            else:
                _r(4, "PR", align=CENTER, bold=True)
        elif from_merge:
            _r(4, from_merge[:7], align=CENTER,
               fill=_fill("D4EDDA"), color="155724")
        else:
            _r(4, "—", align=CENTER, color="AAAAAA")

        _r(5, author, bold=is_merge)

        # ── Message — truncated to ≤ 2 lines ──────────────────────────────
        cell = ws.cell(row=row, column=6, value=_truncate(message))
        cell.font      = Font(bold=is_merge, size=10, color=text_color)
        cell.border    = THIN_BORDER
        cell.alignment = WRAP
        cell.fill      = row_fill

        # ── Bug Fix badge ─────────────────────────────────────────────────
        bf_label = "Yes" if analysis.is_bug_fix else "No"
        cell = ws.cell(row=row, column=7, value=bf_label)
        cell.font      = Font(bold=True, size=10, color="FFFFFF")
        cell.fill      = BUG_FIX_YES_FILL if analysis.is_bug_fix else BUG_FIX_NO_FILL
        cell.border    = THIN_BORDER
        cell.alignment = CENTER

        _r(8, analysis.category.value, bold=is_merge)
        _r(9, analysis.bug_type.value)

        _badge(ws, row, 10, analysis.severity.value,   SEVERITY_FILLS)
        _badge(ws, row, 11, analysis.confidence.value, CONFIDENCE_FILLS)

        # ── Files changed ─────────────────────────────────────────────────
        files_str = "\n".join(analysis.files_changed[:10])
        if len(analysis.files_changed) > 10:
            files_str += f"\n+{len(analysis.files_changed) - 10} more…"
        cell = ws.cell(row=row, column=12, value=files_str)
        cell.font      = Font(size=9, color="444444")
        cell.border    = THIN_BORDER
        cell.alignment = WRAP
        cell.fill      = row_fill

        # ── Reasoning ────────────────────────────────────────────────────
        cell = ws.cell(row=row, column=13, value=analysis.reasoning)
        cell.font      = Font(size=10, color=text_color)
        cell.border    = THIN_BORDER
        cell.alignment = WRAP
        cell.fill      = row_fill

        if bug_fix_only:
            _r(14, sprint_name)

        ws.row_dimensions[row].height = row_height
        row += 1

    # ── Auto-filter + freeze header ───────────────────────────────────────
    last_col = get_column_letter(len(cols))
    ws.auto_filter.ref = f"A1:{last_col}1"
    ws.freeze_panes = "A2"

    # ── Column widths ─────────────────────────────────────────────────────
    for col_idx, (_, w) in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = w


# ---------------------------------------------------------------------------
# PR detail sheet  (one per merge commit)
# ---------------------------------------------------------------------------

PR_DETAIL_COLS = [
    ("#",           5),
    ("Date",       12),
    ("Commit ID",  10),
    ("Author",     22),
    ("Message",    44),
    ("Bug Fix",     9),
    ("Category",   14),
    ("Bug Type",   14),
    ("Severity",   11),
    ("Confidence", 12),
    ("Reasoning",  52),
]


def _build_pr_sheet(wb: Workbook,
                    merge_commit: CommitInfo,
                    merge_analysis,
                    child_commits: list[CommitInfo],
                    child_analyses: list[CommitAnalysis],
                    sheet_name: str) -> None:
    """Build a sheet listing all commits inside one PR."""
    ws = wb.create_sheet(title=sheet_name)
    ws.sheet_properties.tabColor = PR_TAB_COLOR

    banner_cols = len(PR_DETAIL_COLS)

    # ── Banner ────────────────────────────────────────────────────────────
    ws.merge_cells(start_row=1, start_column=1,
                   end_row=1,   end_column=banner_cols)
    for c in range(1, banner_cols + 1):
        ws.cell(row=1, column=c).fill = _fill(PR_TAB_COLOR)
    cell = ws.cell(row=1, column=1,
                   value=f"PR Commits — {sheet_name}  ({len(child_commits)} commits)")
    cell.font      = Font(bold=True, size=13, color="FFFFFF")
    cell.alignment = LEFT
    ws.row_dimensions[1].height = 28

    # ── Merge commit info row ─────────────────────────────────────────────
    ws.merge_cells(start_row=2, start_column=1,
                   end_row=2,   end_column=banner_cols)
    for c in range(1, banner_cols + 1):
        ws.cell(row=2, column=c).fill = _fill("D0E8EE")
    merge_date = merge_commit.date[:10] if merge_commit.date else ""
    merge_info = (
        f"Merge commit: {merge_commit.commit_id[:7]}  |  "
        f"{merge_date}  |  {merge_commit.author}  |  "
        f"{_truncate(merge_commit.message, 120)}"
    )
    cell = ws.cell(row=2, column=1, value=merge_info)
    cell.font      = Font(size=10, color="1F3864", italic=True)
    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 22

    # ── Back-link ─────────────────────────────────────────────────────────
    ws.merge_cells(start_row=3, start_column=1,
                   end_row=3,   end_column=banner_cols)
    cell = ws.cell(row=3, column=1, value="← กลับไปที่ Commit Details")
    cell.hyperlink  = "#'Commit Details'!A1"
    cell.font       = Font(size=10, color="0563C1", underline="single")
    cell.alignment  = LEFT
    cell.fill       = _fill("FFFFFF")
    ws.row_dimensions[3].height = 18

    # ── Column headers ────────────────────────────────────────────────────
    row = 4
    for col_idx, (label, _) in enumerate(PR_DETAIL_COLS, 1):
        _hdr(ws, row, col_idx, label)
    ws.row_dimensions[row].height = 22
    row += 1

    # ── Child commit rows ─────────────────────────────────────────────────
    analysis_map = {a.commit_id: a for a in child_analyses}

    for seq, commit in enumerate(child_commits, 1):
        analysis = analysis_map.get(commit.commit_id)
        if analysis is None:
            continue

        row_fill = _fill(CATEGORY_FILLS.get(analysis.category, "FFFFFF"))

        def _r(ci, value, align=LEFT, fill=row_fill, bold=False, color="333333"):
            cell = ws.cell(row=row, column=ci, value=value)
            cell.font      = Font(bold=bold, size=10, color=color)
            cell.border    = THIN_BORDER
            cell.alignment = align
            cell.fill      = fill

        _r(1, seq, align=CENTER)
        _r(2, commit.date[:10], align=CENTER)
        _r(3, commit.commit_id[:7], align=CENTER)
        _r(4, commit.author)

        cell = ws.cell(row=row, column=5, value=_truncate(commit.message))
        cell.font      = Font(size=10, color="333333")
        cell.border    = THIN_BORDER
        cell.alignment = WRAP
        cell.fill      = row_fill

        bf_label = "Yes" if analysis.is_bug_fix else "No"
        cell = ws.cell(row=row, column=6, value=bf_label)
        cell.font      = Font(bold=True, size=10, color="FFFFFF")
        cell.fill      = BUG_FIX_YES_FILL if analysis.is_bug_fix else BUG_FIX_NO_FILL
        cell.border    = THIN_BORDER
        cell.alignment = CENTER

        _r(7, analysis.category.value)
        _r(8, analysis.bug_type.value)
        _badge(ws, row,  9, analysis.severity.value,   SEVERITY_FILLS)
        _badge(ws, row, 10, analysis.confidence.value, CONFIDENCE_FILLS)

        cell = ws.cell(row=row, column=11, value=analysis.reasoning)
        cell.font      = Font(size=10, color="333333")
        cell.border    = THIN_BORDER
        cell.alignment = WRAP
        cell.fill      = row_fill

        ws.row_dimensions[row].height = 30
        row += 1

    ws.freeze_panes = "A5"
    for col_idx, (_, w) in enumerate(PR_DETAIL_COLS, 1):
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

    # ── Summary dashboard ─────────────────────────────────────────────────
    _build_summary(wb, commits, analyses, sprint_name, sprint_start, sprint_end)

    # ── Build PR detail sheets (one per merge commit) ─────────────────────
    analysis_map = {a.commit_id: a for a in analyses}

    merge_commits = [c for c in commits if c.is_merge_commit]

    # Group child commits by their parent merge SHA
    children_of: dict[str, list[CommitInfo]] = {}
    for c in commits:
        if c.from_merge_commit:
            children_of.setdefault(c.from_merge_commit, []).append(c)

    # ── Build pr_sheet_map first (names only, sheets created later) ──────
    pr_sheet_map: dict[str, str] = {}
    for mc in merge_commits:
        pr_sheet_map[mc.commit_id] = _pr_sheet_name(mc.commit_id, mc.message)

    # ── Main detail sheets first ──────────────────────────────────────────
    _build_details(wb, commits, analyses, "Commit Details", TAB_BLUE,
                   bug_fix_only=False, sprint_name=sprint_name,
                   pr_sheet_map=pr_sheet_map)
    _build_details(wb, commits, analyses, "Bug Fix Only", TAB_RED,
                   bug_fix_only=True,  sprint_name=sprint_name,
                   pr_sheet_map=pr_sheet_map)

    # ── PR detail sheets at the back (one per merge commit) ───────────────
    for mc in merge_commits:
        sname          = pr_sheet_map[mc.commit_id]
        child_commits  = children_of.get(mc.commit_id, [])
        child_analyses = [analysis_map[c.commit_id]
                          for c in child_commits if c.commit_id in analysis_map]
        _build_pr_sheet(wb, mc, analysis_map.get(mc.commit_id),
                        child_commits, child_analyses, sname)

    try:
        wb.save(filepath)
    except PermissionError:
        raise PermissionError(
            f"Cannot save '{filepath}' — please close the file in Excel and try again."
        )
