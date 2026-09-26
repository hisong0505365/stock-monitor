# parsing_accuracy.py
# 감사보고서 파싱 정확도 검증
#
# disclosure_parser 는 표 테두리 선(find_tables)으로 행/열을 복원한다.
# 여기서는 원리가 다른 두 번째 추출기(선을 쓰지 않고 글자 좌표만으로 행/열 복원)를 두고
#   1) 텍스트 레이어 좌표 추출 vs 파서            → 구조(행·열·부호) 정확도
#   2) OCR(Tesseract) 좌표 추출 vs 텍스트 레이어   → OCR로 읽었을 때의 숫자·계정명 정확도
#   3) 사람이 페이지 이미지를 읽어 만든 정답표 vs 파서 → 표준 계정 정확도
#      (tests/fixtures/audit_ground_truth.json, tests/test_parsing_accuracy.py)
# 를 비교한다.
#
# OCR 비교는 OCR 에 유리하게 잡았다 — 표 선 제거 전처리, 갈라진 숫자 조각 합치기·괄호 보정
# 후처리, 그리고 열 배치는 텍스트 레이어에서 찾은 것을 그대로 빌려준다. 즉 "표 구조를 완벽히
# 안다고 쳤을 때 OCR 이 숫자를 얼마나 맞게 읽는가"의 상한이다.

import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf

from disclosure_parser import (
    STATEMENT_TITLES, _page_title, _period_label, extract_statements,
    normalize_account, parse_amount, squash,
)

pymupdf.no_recommend_layout()

TARGET = ("BS", "IS", "CF")          # 자본변동표는 열이 기간이 아니라 자본 구성요소라 제외
AMOUNT = re.compile(r"^\(?-?[\d,]+\)?$|^[-－—]$")
NOTE_REF = re.compile(r"^\d{1,2}(,\s?\d{1,2})*,?$")   # 주석 번호: '4,' '5,' '14' '6,26,32'
ROW_TOL = 3        # 같은 줄로 볼 y 차이
WRAP_GAP = 12      # 이보다 가까운 줄은 한 행(계정명 줄바꿈). 일반 행 간격은 14~17pt
EDGE_TOL = 4       # 오른쪽 정렬 열 경계 허용 오차


# ===== 단어 소스 =====

def words_from_text_layer(page):
    # 빈 셀에는 전각 공백(U+3000)이 찍혀 있고, '　-' 처럼 값에 붙어 나오기도 한다
    words = [(w[0], w[1], w[2], w[3], w[4].strip("　 ")) for w in page.get_text("words")]
    return [w for w in words if w[4]]


def _remove_table_lines(gray):
    """표 테두리 제거 — 선이 남아 있으면 Tesseract 가 표 영역을 통째로 깨진 글자로 읽는다"""
    import numpy as np
    a = gray.copy()
    dark = a < 160
    h, w = a.shape
    a[dark.sum(axis=1) > w * 0.4, :] = 255     # 가로선
    a[:, dark.sum(axis=0) > h * 0.15] = 255    # 세로선
    return a


def words_from_ocr(page, dpi=300, lang="kor+eng", clean_lines=True):
    """Tesseract TSV → PDF 좌표계(pt) 단어 목록"""
    import numpy as np
    from PIL import Image
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    if clean_lines:
        gray = _remove_table_lines(gray)
    scale = 72 / dpi
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "page.png"
        Image.fromarray(gray).save(img)
        out = subprocess.run(
            ["tesseract", str(img), "stdout", "-l", lang, "--psm", "6", "tsv"],
            capture_output=True, text=True, check=True).stdout
    words = []
    for line in out.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        left, top, width, height = (int(c) for c in cols[6:10])
        words.append((left * scale, top * scale, (left + width) * scale,
                      (top + height) * scale, cols[11].strip()))
    return words


_OCR_NUMERIC = re.compile(r"^[\d,.()\-]+$")


def merge_numeric_fragments(words, gap=6):
    """OCR 후처리: '3,309,341' + '062,502)' 처럼 공백으로 갈라진 숫자 조각을 합친다"""
    out = []
    for w in sorted(words, key=lambda w: (round((w[1] + w[3]) / 2 / ROW_TOL), w[0])):
        if (out and _OCR_NUMERIC.match(w[4]) and _OCR_NUMERIC.match(out[-1][4])
                and abs((out[-1][1] + out[-1][3]) / 2 - (w[1] + w[3]) / 2) <= ROW_TOL
                and 0 <= w[0] - out[-1][2] <= gap):
            p = out[-1]
            out[-1] = (p[0], min(p[1], w[1]), w[2], max(p[3], w[3]), p[4] + w[4])
        else:
            out.append(w)
    return out


def parse_amount_lenient(text):
    """OCR 후처리: 짝이 안 맞는 괄호도 음수로, '.' 을 천 단위 구분자로 본다"""
    s = text.replace(" ", "").replace(".", ",")
    if s in ("-", "－", "—"):
        return 0
    neg = s.startswith("(") or s.endswith(")") or s.startswith("-")
    digits = re.sub(r"[(),\-]", "", s)
    if not digits.isdigit():
        return None
    return -int(digits) if neg else int(digits)


# ===== 좌표 기반 표 복원 =====

def _visual_rows(words):
    rows = []
    for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
        yc = (w[1] + w[3]) / 2
        if rows and abs(rows[-1]["y"] - yc) <= ROW_TOL:
            rows[-1]["words"].append(w)
        else:
            rows.append({"y": yc, "words": [w]})
    for r in rows:
        r["words"].sort(key=lambda w: w[0])
    return rows


def _find_header(rows):
    for i, r in enumerate(rows):
        text = squash("".join(w[4] for w in r["words"]))
        if text.startswith("과목") or text.startswith("구분"):
            return i
    return None


def _period_headers(header_words, label_end):
    """머리글 영역 단어 → 기간 라벨('제 24(당) 기말')과 x 범위

    머리글이 두 줄인 열('제 1(전) 기말 / (감사받지 않은 재무제표)')은 다른 높이에 놓이므로
    머리글 줄 위아래 단어를 모두 받아 x 가 겹치거나 가까운 것끼리 한 기간으로 묶는다.
    """
    groups = []
    for w in sorted((w for w in header_words if w[0] >= label_end), key=lambda w: w[0]):
        if groups and w[0] <= groups[-1]["x1"] + 15:
            groups[-1]["words"].append(w)
            groups[-1]["x1"] = max(groups[-1]["x1"], w[2])
        else:
            groups.append({"words": [w], "x0": w[0], "x1": w[2]})
    headers = []
    for g in groups:
        text = " ".join(w[4] for w in sorted(g["words"], key=lambda w: (w[1], w[0])))
        # '목'(과 목 사이 공백으로 떨어진 글자)·'주석' 은 기간이 아니다
        if not re.search(r"제\d+|\((당|전)\)|기초|기말", squash(text)):
            continue
        headers.append({"label": _period_label(text), "x0": g["x0"], "x1": g["x1"]})
    return headers


def _column_edges(rows, period_x0):
    """금액은 열마다 오른쪽 정렬 → 오른쪽 끝 x 가 모이는 곳이 열 경계"""
    xs = sorted(w[2] for r in rows for w in r["words"]
                if AMOUNT.match(w[4]) and w[2] > period_x0)
    clusters = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= EDGE_TOL:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [sum(c) / len(c) for c in clusters if len(c) >= 2]


def _body_rows(words):
    footer = min((w[1] for w in words if "전자공시시스템" in w[4]), default=1e9)
    return _visual_rows([w for w in words if w[1] < footer - 1])


def detect_layouts(pages_words):
    """[(page_no, words)] → {page_no: 열 배치}. 넘김 페이지는 앞 페이지 배치를 이어받는다"""
    layouts, layout = {}, None
    for pno, words in pages_words:
        rows = _body_rows(words)
        h = _find_header(rows)
        if h is not None:
            header_y = rows[h]["y"]
            header_words = [w for r in rows if abs(r["y"] - header_y) <= WRAP_GAP
                            for w in r["words"]]
            note = next((w for w in rows[h]["words"] if squash(w[4]) == "주석"), None)
            label_end = rows[h]["words"][0][2] + 1   # '과' 오른쪽부터 머리글 후보
            periods = _period_headers(
                [w for w in header_words if not note or w[0] > note[2]], label_end)
            if not periods:
                raise ValueError(f"p{pno + 1}: 기간 머리글을 찾지 못함")
            period_x0 = min(p["x0"] for p in periods)
            body = [r for r in rows if r["y"] - header_y > WRAP_GAP]
            edges = _column_edges(body, period_x0)
            if not edges or len(edges) % len(periods):
                raise ValueError(f"p{pno + 1}: 열 {len(edges)}개를 기간 {len(periods)}개에 배정할 수 없음")
            per = len(edges) // len(periods)
            layout = {
                "header_y": header_y, "period_x0": period_x0, "edges": edges,
                "period_of": [periods[i // per]["label"] for i in range(len(edges))],
            }
            layouts[pno] = layout
        elif layout is not None:
            layouts[pno] = {**layout, "header_y": -1e9}
    return layouts


def extract_by_coordinates(pages_words, layouts=None, amount_parser=parse_amount):
    """[(page_no, words)] (한 재무제표의 연속 페이지) → 행 목록 {page, y, account, values}

    layouts 를 주면 열 배치를 찾지 않고 그대로 쓴다(OCR 에 텍스트 레이어 배치를 빌려줄 때).
    """
    layouts = layouts if layouts is not None else detect_layouts(pages_words)
    out = []
    for pno, words in pages_words:
        layout = layouts.get(pno)
        if layout is None:
            continue
        body = [r for r in _body_rows(words) if r["y"] - layout["header_y"] > WRAP_GAP]
        out.extend(_rows_to_records(pno, body, layout, amount_parser))
    return out


def _rows_to_records(pno, rows, layout, amount_parser):
    # 계정명 줄바꿈(행 간격 < WRAP_GAP) 합치기
    logical = []
    for r in rows:
        if logical and r["y"] - logical[-1]["y_last"] < WRAP_GAP:
            logical[-1]["words"].extend(r["words"])
            logical[-1]["y_last"] = r["y"]
        else:
            logical.append({"y": r["y"], "y_last": r["y"], "words": list(r["words"])})

    x0 = layout["period_x0"]
    records = []
    for r in logical:
        label, values = [], {}
        for w in sorted(r["words"], key=lambda w: (w[1], w[0])):
            text = w[4]
            if w[2] > x0 and (AMOUNT.match(text) or _OCR_NUMERIC.match(text)):
                col = min(range(len(layout["edges"])), key=lambda i: abs(layout["edges"][i] - w[2]))
                if abs(layout["edges"][col] - w[2]) > EDGE_TOL * 2:
                    continue
                period = layout["period_of"][col]
                if values.get(period) is None:
                    values[period] = amount_parser(text)
            elif NOTE_REF.match(text) and w[2] <= x0:
                continue   # 주석 번호 열
            elif w[0] < x0:
                label.append(text)
        account, _ = normalize_account(" ".join(label))
        if account or values:
            records.append({"page": pno + 1, "y": round(r["y"], 1),
                            "account": account, "values": values})
    return records


def statement_pages(doc):
    """재무제표 종류별 페이지 번호 (제목 줄 기준, 주석 전까지)"""
    pages, current = {}, None
    for pno, page in enumerate(doc):
        title = _page_title(page)
        if title.startswith("주석"):
            break
        stype = STATEMENT_TITLES.get(title)
        if stype:
            current = stype
        if current:
            pages.setdefault(current, []).append(pno)
    return {k: v for k, v in pages.items() if k in TARGET}


# ===== 비교 =====

def _triples(rows):
    return [(r["account"], p, v) for r in rows for p, v in r["values"].items() if v is not None]


def compare_triples(reference, candidate):
    """(계정, 기간, 값) 다중집합 비교"""
    ref, cand = Counter(_triples(reference)), Counter(_triples(candidate))
    return {
        "reference_cells": sum(ref.values()),
        "candidate_cells": sum(cand.values()),
        "matched": sum((ref & cand).values()),
        "missing": sorted((ref - cand).elements()),
        "extra": sorted((cand - ref).elements()),
    }


def _nearest(candidate, r, y_tol):
    cands = [c for c in candidate if c["page"] == r["page"] and abs(c["y"] - r["y"]) <= y_tol]
    return min(cands, key=lambda c: abs(c["y"] - r["y"])) if cands else None


def compare_by_position(reference, candidate, y_tol=5):
    """같은 페이지·같은 y 의 행끼리 기간별 값 비교 (OCR 은 계정명이 틀려도 위치로 맞춘다)"""
    total = matched = 0
    errors = []
    for r in reference:
        c = _nearest(candidate, r, y_tol)
        for period, v in r["values"].items():
            if v is None:
                continue
            total += 1
            got = c["values"].get(period) if c else None
            if got == v:
                matched += 1
            else:
                errors.append({"page": r["page"], "account": r["account"], "period": period,
                               "expected": v, "got": got})
    return {"cells": total, "matched": matched, "errors": errors}


def label_accuracy(reference, candidate, y_tol=5):
    """계정명 문자 정확도 (OCR 한글 인식 품질)"""
    exact, ratios, wrong = 0, [], []
    for r in reference:
        if not r["account"]:
            continue
        c = _nearest(candidate, r, y_tol)
        got = c["account"] if c else ""
        exact += got == r["account"]
        if got != r["account"]:
            wrong.append((r["account"], got))
        ratios.append(SequenceMatcher(None, r["account"], got).ratio())
    n = len(ratios)
    return {"labels": n, "exact": exact,
            "mean_similarity": round(sum(ratios) / n, 4) if n else None, "wrong": wrong}


def evaluate(path, ocr=False):
    doc = pymupdf.open(path)
    parser_rows = extract_statements(doc)
    report = {"file": Path(path).name, "statements": {}}
    for stype, pages in statement_pages(doc).items():
        text_words = [(p, words_from_text_layer(doc[p])) for p in pages]
        layouts = detect_layouts(text_words)
        text_rows = extract_by_coordinates(text_words, layouts)
        entry = {"pages": [p + 1 for p in pages],
                 "parser_vs_coordinates": compare_triples(parser_rows[stype]["rows"], text_rows)}
        if ocr:
            ocr_words = [(p, merge_numeric_fragments(words_from_ocr(doc[p]))) for p in pages]
            ocr_rows = extract_by_coordinates(ocr_words, layouts, parse_amount_lenient)
            entry["ocr_values"] = compare_by_position(text_rows, ocr_rows)
            entry["ocr_labels"] = label_accuracy(text_rows, ocr_rows)
        report["statements"][stype] = entry
    return report


if __name__ == "__main__":
    use_ocr = "--ocr" in sys.argv
    for pdf in [a for a in sys.argv[1:] if not a.startswith("--")]:
        print(json.dumps(evaluate(pdf, ocr=use_ocr), ensure_ascii=False, indent=2, default=str))
