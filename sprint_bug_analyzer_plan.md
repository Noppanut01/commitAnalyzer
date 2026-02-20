# Sprint Bug Fix Analyzer — Planning Doc

## Overview

ระบบที่ใช้ Claude วิเคราะห์ commit ตลอด sprint เพื่อหาว่าอันไหนเป็น bug fix
และสรุปประสิทธิภาพของทีมออกมาเป็น Excel report

---

## 1. Input ที่ต้องการ

| Input | รายละเอียด |
|---|---|
| Azure DevOps PAT | Personal Access Token (สิทธิ์ Code Read) |
| Organization / Project / Repo | ชื่อ repo ที่จะวิเคราะห์ |
| Sprint date range | วันเริ่มต้น–สิ้นสุด sprint |
| Sprint name | ชื่อ sprint สำหรับใส่ใน report |

---

## 2. Flow การทำงาน

```
Azure DevOps API
      │
      ▼
ดึง commits ทั้งหมดใน date range
      │
      ▼
สำหรับแต่ละ commit → ดึง diff (code changes)
      │
      ▼
ส่งให้ Claude วิเคราะห์ (commit message + diff)
      │   Claude ดูทั้ง:
      │   - keyword pattern (fix:, bug:, hotfix, แก้บัค ฯลฯ)
      │   - โครงสร้าง code ที่เปลี่ยน (error handling, condition fix ฯลฯ)
      │
      ▼
รวมผลวิเคราะห์ทั้งหมด
      │
      ▼
Export Excel Report
```

---

## 3. สิ่งที่ Claude วิเคราะห์ต่อ 1 commit

Claude จะตัดสินใจและให้ข้อมูลดังนี้:

- **is_bug_fix** — ใช่หรือไม่ (boolean)
- **confidence** — ความมั่นใจ (High / Medium / Low)
- **category** — ประเภทของ commit เช่น `Bug Fix`, `Feature`, `Refactor`, `Chore`, `Unclear`
- **bug_type** — ถ้าเป็น bug fix ระบุประเภท เช่น `Logic Error`, `UI Bug`, `Performance`, `Crash`, `Security`
- **severity** — ความรุนแรง (Critical / Major / Minor) — ประเมินจาก code ที่แก้
- **reasoning** — อธิบายว่าทำไมถึงตัดสินใจแบบนี้ (1–2 ประโยค)
- **files_changed** — ไฟล์ที่เปลี่ยน

---

## 4. Excel Report Structure

### Sheet 1: Summary Dashboard

| Section | ข้อมูล |
|---|---|
| Sprint name & date range | |
| Total commits | |
| Bug fix commits | จำนวน + % |
| Bug fix by developer | ตารางแยกคน |
| Bug fix by category | Breakdown |
| Severity breakdown | Critical / Major / Minor |

### Sheet 2: Commit Details

ตารางรายการ commit ทุกอัน พร้อมผลวิเคราะห์จาก Claude

| Column | รายละเอียด |
|---|---|
| Date | วันที่ commit |
| Commit ID | short hash |
| Author | ชื่อคนทำ |
| Message | commit message |
| Is Bug Fix | ✅ / ❌ |
| Category | Bug Fix / Feature / ฯลฯ |
| Bug Type | ประเภท bug (ถ้ามี) |
| Severity | Critical / Major / Minor |
| Confidence | High / Medium / Low |
| Files Changed | รายชื่อไฟล์ |
| Reasoning | เหตุผลจาก Claude |

### Sheet 3: Bug Fix Only

เหมือน Sheet 2 แต่ filter เฉพาะ bug fix commits — ใช้สำหรับ sprint retrospective

---

## 5. Tech Stack ที่วางแผนจะใช้

| Component | เลือกใช้ | เหตุผล |
|---|---|---|
| Azure DevOps data | REST API | ง่าย ไม่ต้องติดตั้งอะไรเพิ่ม |
| AI วิเคราะห์ | Anthropic Python SDK | เรียก Claude โดยตรง |
| Excel output | openpyxl | รองรับ formatting ได้ดี |
| Config | .env file | เก็บ token ปลอดภัย |

---

## 6. วิธี Run (Draft)

ยังไม่ได้ตัดสินใจ 100% แต่ตัวเลือกที่น่าจะ fit ที่สุด:

### Option A — Python Script (แนะนำตอนนี้)
```bash
# ติดตั้งครั้งแรก
pip install requests anthropic openpyxl python-dotenv

# ตั้งค่าใน .env
AZURE_ORG=your-org
AZURE_PROJECT=your-project
AZURE_REPO=your-repo
AZURE_PAT=xxxx
ANTHROPIC_API_KEY=xxxx
SPRINT_START=2025-01-01
SPRINT_END=2025-01-14
SPRINT_NAME=Sprint 1

# รัน
python sprint_bug_analyzer.py
```

**ข้อดี:** ไม่ต้องติดตั้ง server อะไร รันบน local ได้เลย

### Option B — Claude Desktop + MCP
ใช้ azure-devops-mcp ของ Microsoft ให้ Claude ดึงข้อมูลได้โดยตรง
เหมาะถ้าอยากใช้แบบ interactive chat

### Option C — Scheduled Script (ถ้าอยากรันอัตโนมัติ)
ใช้ GitHub Actions / Azure Pipeline รัน script ทุกสิ้น sprint แล้ว upload report ไปยังที่ที่กำหนด

---

## 7. ข้อจำกัดที่ควรรู้

- **API Rate Limit** — Azure DevOps REST API มี rate limit ถ้า commit เยอะมาก (100+) อาจต้องทำ pagination
- **Diff ขนาดใหญ่** — commit ที่แก้ไฟล์เยอะมากจะตัด diff ก่อนส่ง Claude (ประหยัด token)
- **ความแม่นยำ** — commit ที่ message ไม่ชัดและ diff ซับซ้อน Claude อาจให้ confidence = Low
- **Cost** — ถ้ามี 100 commits × Claude call อาจมีค่า token ประมาณ $0.10–$0.50 ต่อ sprint

---

## 8. สิ่งที่ต้องตัดสินใจก่อน build

- [ ] จะ run แบบไหน? (local script / scheduled / Claude Desktop)
- [ ] มีสิทธิ์ขอ Azure PAT ได้มั้ย?
- [ ] มี Anthropic API Key มั้ย?
- [ ] อยากให้ report มี chart/graph ใน Excel ด้วยมั้ย?
- [ ] อยากส่ง report ไปที่ไหนหลัง run? (email, Teams, ไฟล์ในโฟลเดอร์)
