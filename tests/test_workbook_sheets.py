from pathlib import Path
import sys

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.excel_to_sql.workbook import open_workbook_headers, resolve_sheet_candidates


def _save_workbook(path: Path, sheet_names):
    wb = Workbook()
    default = wb.active
    wb.remove(default)
    for name in sheet_names:
        ws = wb.create_sheet(name)
        ws.append(["日期", "地點"])
        ws.append(["2026-06-02", "基隆"])
    wb.save(path)


def test_open_workbook_headers_accepts_multiple_exact_sheet_names(tmp_path):
    excel_path = tmp_path / "source.xlsx"
    _save_workbook(excel_path, ["漁業活動資料", "漁業活動紀錄", "欄位說明"])

    cfg = {
        "source": {
            "excel_path": str(excel_path),
            "sheets": ["漁業活動資料", "漁業活動紀錄"],
            "sheet_match": "exact",
            "header_row": 1,
        }
    }

    sheets = open_workbook_headers(str(tmp_path / "config.json"), cfg)

    assert [sheet.sheet_name for sheet in sheets] == ["漁業活動資料", "漁業活動紀錄"]
    assert [sheet.match_type for sheet in sheets] == ["exact", "exact"]
    assert sheets[0].header_map == {"日期": 1, "地點": 2}


def test_smart_sheet_matching_can_return_multiple_matching_sheets():
    matches = resolve_sheet_candidates(
        available_sheet_names=["漁業活動資料_A", "漁業活動資料_B", "欄位說明"],
        expected_names=["漁業活動紀錄"],
        match_mode="smart",
    )

    assert [match[0] for match in matches] == ["漁業活動資料_A", "漁業活動資料_B"]
    assert [match[2] for match in matches] == ["prefix", "prefix"]
    assert "工作表" in matches[0][3]


def test_sheet_aliases_are_used_for_smart_matching(tmp_path):
    excel_path = tmp_path / "source.xlsx"
    _save_workbook(excel_path, ["漁業活動資料", "欄位說明"])

    cfg = {
        "source": {
            "excel_path": str(excel_path),
            "sheet": "漁業活動紀錄",
            "sheet_aliases": ["漁業活動資料"],
            "header_row": 1,
        }
    }

    sheets = open_workbook_headers(str(tmp_path / "config.json"), cfg)

    assert [sheet.sheet_name for sheet in sheets] == ["漁業活動資料"]
    assert sheets[0].match_type == "exact"
