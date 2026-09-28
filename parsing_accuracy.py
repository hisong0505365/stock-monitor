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
import os
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
# 주석 번호: '4,' '5,' '14' '6,26,32'. OCR 은 쉼표를 '.' 으로 읽기도 한다('4.5,14')
NOTE_REF = re.compile(r"^\d{1,2}([,.]\s?\d{1,2})*[,.]?$")
# OCR 이 로마숫자 머리표(Ⅰ. Ⅱ. Ⅳ. Ⅶ. Ⅸ.)를 '|.' 'Il.' 'iI.' 'LL.' 'I].' '1/.' 'Vil,' 'IX,' 로 읽은 것
OCR_ROMAN_PREFIX = re.compile(r"^[|lIiLVvXx\]\[!1/\\]{1,4}[.,]")
ROW_TOL = 3        # 같은 줄로 볼 y 차이
WRAP_GAP = 12      # 이보다 가까운 줄은 한 행(계정명 줄바꿈). 일반 행 간격은 14~17pt
EDGE_TOL = 4       # 오른쪽 정렬 열 경계 허용 오차


# ===== 단어 소스 =====

def words_from_text_layer(page):
    # 빈 셀에는 전각 공백(U+3000)이 찍혀 있고, '　-' 처럼 값에 붙어 나오기도 한다
    words = [(w[0], w[1], w[2], w[3], w[4].strip("　 ")) for w in page.get_text("words")]
    return [w for w in words if w[4]]


def _long_runs(dark, length, axis):
    """axis 방향으로 length 픽셀 이상 이어진 어두운 픽셀 (1차원 열림 연산: 침식 → 팽창)"""
    import numpy as np
    d = np.moveaxis(dark, axis, 0).astype(np.int32)
    c = np.concatenate([np.zeros((1, d.shape[1]), np.int32), np.cumsum(d, axis=0)])
    n = d.shape[0]
    core = np.zeros_like(d, dtype=bool)                      # 길이 length 창이 전부 어두운 시작점
    core[:n - length + 1] = (c[length:] - c[:n - length + 1]) == length
    cc = np.concatenate([np.zeros((1, d.shape[1]), np.int32), np.cumsum(core, axis=0)])
    idx = np.arange(n)
    lo = np.clip(idx - length + 1, 0, n)                     # 이 픽셀을 덮는 창 시작점 범위
    covered = (cc[idx + 1] - cc[lo]) > 0
    return np.moveaxis(covered, 0, axis)


def _remove_table_lines(gray, min_len_pt=20, dpi=300):
    """표 테두리 제거 — 선이 남아 있으면 Tesseract 가 표 영역을 통째로 깨진 글자로 읽는다

    예전에는 '어두운 픽셀 합이 높이의 15% 를 넘는 세로줄' 을 선으로 봤는데, 오른쪽 정렬된 금액은
    같은 자리 숫자('1' 의 세로획)가 수십 행에 걸쳐 같은 x 에 놓여 그 기준을 넘는다 → 숫자 획이
    지워져 '1'→'7', '3'→'8' 오인식의 주원인이 됐다(2026-09-27 발견). 이제는 실제로 끊김 없이
    min_len_pt(글자 높이의 2배 이상) 넘게 이어진 선만 지운다.
    """
    import numpy as np
    dark = gray < 200                                          # 안티에일리어싱된 선 가장자리까지
    length = int(min_len_pt * dpi / 72)
    lines = _long_runs(dark, length, 0) | _long_runs(dark, length, 1)
    # 선 옆 1픽셀 번짐까지
    lines[1:] |= lines[:-1]; lines[:-1] |= lines[1:]
    lines[:, 1:] |= lines[:, :-1]; lines[:, :-1] |= lines[:, 1:]
    a = gray.copy()
    a[lines] = 255
    return a


# Tesseract 의 OpenMP 다중 스레드는 여러 개를 함께 돌리면 서로 CPU 를 기다리며 수십 배
# 느려진다(4코어에서 5건 동시 실행 시 10분 넘게 멈춤). 한 스레드로 돌리고 병렬은 프로세스로 한다
_TESS_ENV = {**os.environ, "OMP_THREAD_LIMIT": "1"}

# 금액 0 을 뜻하는 '-' 를 한국어 모델은 'ㆍ'(가운뎃점)·'一' 등으로 읽는다(아주약품 포괄손익)
DASH_LIKE = {"ㆍ", "·", "•", "—", "–", "―", "ー", "一", "_", "－"}


def words_from_ocr(page, dpi=300, lang="kor+eng", clean_lines=True):
    """Tesseract TSV → PDF 좌표계(pt) 단어 목록"""
    from PIL import Image
    gray = _render_gray(page, dpi, clean_lines)
    scale = 72 / dpi
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "page.png"
        Image.fromarray(gray).save(img)
        out = subprocess.run(
            ["tesseract", str(img), "stdout", "-l", lang, "--psm", "6", "tsv"],
            capture_output=True, text=True, check=True, env=_TESS_ENV).stdout
    words = []
    for line in out.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        left, top, width, height = (int(c) for c in cols[6:10])
        text = cols[11].strip()
        words.append((left * scale, top * scale, (left + width) * scale,
                      (top + height) * scale, "-" if text in DASH_LIKE else text))
    return words


_OCR_NUMERIC = re.compile(r"^[\d,.()\-]+$")
DIGITS_ONLY = "tessedit_char_whitelist=0123456789,()-"


def _render_gray(page, dpi, clean_lines=True):
    import numpy as np
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return _remove_table_lines(gray, dpi=dpi) if clean_lines else gray


def _ocr_line(img, lang="eng"):
    """이미지 한 조각을 한 줄(psm 7)·숫자 문자만으로 읽는다"""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cell.png"
        Image.fromarray(img).save(path)
        return subprocess.run(
            ["tesseract", str(path), "stdout", "-l", lang, "--psm", "7", "-c", DIGITS_ONLY],
            capture_output=True, text=True, env=_TESS_ENV,
        ).stdout.strip().replace(" ", "")


# 1단계가 숫자 사이에 잡문자를 끼워 읽은 칸('6,/98,809,489')도 재판독 대상
_NUMERIC_LIKE = re.compile(r"^[\d,.()\-/|lIoO]+$")


def _numeric_like(text):
    return bool(_NUMERIC_LIKE.match(text)) and sum(c.isdigit() for c in text) >= len(text) / 2


def reread_numbers(page, words, x_min, dpi=300, tiebreak_dpi=400, workers=4):
    """2단계 OCR: 1단계(페이지 전체 OCR)가 찾은 금액 칸만 잘라 다시 읽는다

    페이지를 통째로 읽으면 주변 글자 문맥에 끌린 오답이 섞인다. 같은 칸을 잘라 한 줄
    모드·숫자 문자(0-9 , ( ) -)만으로 다시 읽는다. 1단계와 2단계가 다르면 설정을 바꿔
    (다른 해상도 · 한국어 모델) 두 번 더 읽어 다수결로 정한다 — 설정마다 틀리는 칸이 달라서
    (인천약품 '2,520,675,257': 300dpi 영문 2,920 · 400dpi 영문 2,020 · 한영 2,520) 표가
    갈리면 정답이 남는다. 동점이면 2단계 값. 1단계는 숫자가 '어디' 있는지를 주로 쓴다.
    """
    import numpy as np
    from concurrent.futures import ThreadPoolExecutor
    images = {d: _render_gray(page, d) for d in (dpi, tiebreak_dpi)}
    targets = [i for i, w in enumerate(words) if w[2] > x_min and _numeric_like(w[4])]

    def read(i, d, lang="eng"):
        w, s, gray = words[i], d / 72, images[d]
        x0, y0 = max(int((w[0] - 4) * s), 0), max(int((w[1] - 3) * s), 0)
        x1, y1 = int((w[2] + 4) * s), int((w[3] + 3) * s)
        text = _ocr_line(np.pad(gray[y0:y1, x0:x1], 20, constant_values=255), lang)
        return text if text and _OCR_NUMERIC.match(text) else None

    with ThreadPoolExecutor(workers) as pool:
        second = dict(zip(targets, pool.map(lambda i: read(i, dpi), targets)))
        first = {i: words[i][4] if _OCR_NUMERIC.match(words[i][4]) else None for i in targets}
        disputed = [i for i in targets if second[i] != first[i] and first[i] and second[i]]
        extra = dict(zip(disputed, pool.map(
            lambda i: (read(i, tiebreak_dpi), read(i, dpi, "kor+eng")), disputed)))
    out = list(words)
    for i in targets:
        votes = [v for v in (first[i], second[i], *extra.get(i, ())) if v]
        if not votes:
            continue
        best = max(set(votes), key=lambda v: (votes.count(v), v == second[i]))
        out[i] = (*words[i][:4], best)
    return out


def merge_numeric_fragments(words, gap=6):
    """OCR 후처리: '3,309,341' + '062,502)' 처럼 공백으로 갈라진 숫자 조각을 합친다

    Tesseract 는 한 숫자를 겹친 두 조각('3,935,304,' 과 그 위에 겹친 '799')으로 내기도 한다.
    쉼표로 끝난 조각 뒤에 겹쳐 온 조각은 이어 붙이고, 그 밖의 겹침은 긴 쪽을 남긴다.
    """
    # 같은 줄은 y 중심을 이어 묶는다 — y 를 고정 간격으로 반올림하면 436.4 와 436.8 처럼
    # 같은 높이의 조각이 다른 줄로 갈린다(지오영)
    out = []
    for row in _visual_rows(words):
        merged = []
        for w in row["words"]:                                  # x 순
            p = merged[-1] if merged else None
            if (p and _OCR_NUMERIC.match(w[4]) and _OCR_NUMERIC.match(p[4])
                    and p[0] <= w[0] <= p[2] + gap):             # 앞 조각 안이나 바로 뒤에서 시작
                box = (p[0], min(p[1], w[1]), max(p[2], w[2]), max(p[3], w[3]))
                if w[0] >= p[2] or p[4].endswith(","):
                    text = p[4] + w[4]
                else:
                    text = max(p[4], w[4], key=len)
                merged[-1] = (*box, text)
            else:
                merged.append(w)
        out.extend(merged)
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
    texts = [squash("".join(w[4] for w in r["words"])) for r in rows]
    for i, text in enumerate(texts):
        if text.startswith("과목") or text.startswith("구분"):
            return i
    # OCR: '과 목' 을 '과 =' · 'HOS' 등으로 읽는다 — 기간 머리글('제21(당)기')이 둘 이상 있거나
    # '과' 로 시작하고 하나 있으면 머리글. 표지의 기간 줄은 줄마다 하나뿐이다.
    # (두 줄 머리글의 윗줄도 기간이 둘일 수 있어 '과목' 을 먼저 찾는다 — 아주약품 재무상태표)
    for i, text in enumerate(texts):
        periods = len(re.findall(r"제\d+", text))
        if periods >= 2 or (text.startswith("과") and periods):
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
    headers, unknown = [], []
    for g in groups:
        # 줄 순서 → 줄 안 x 순서. 윗변 y 로 정렬하면 OCR 글자 조각('제' '21(' '당' ')' '기')이 섞인다
        text = " ".join(w[4] for r in _visual_rows(g["words"]) for w in r["words"])
        h = {"label": _period_label(text), "x0": g["x0"], "x1": g["x1"],
             "term": next(iter(re.findall(r"제(\d+)", squash(text))), None)}
        if h["label"] in PERIODS:
            headers.append(h)
        elif re.search(r"제\d+|기초|기말", squash(text)):
            headers.append(h)                   # '제 1 기말' 처럼 (당)(전) 없이 쓴 머리글
        else:
            unknown.append(h)                   # '목' 조각, OCR 로 깨진 머리글('mre)!')
    return _resolve_periods(headers, unknown)


PERIODS = {"당기", "전기", "당기초", "전기초", "전전기"}


def _resolve_periods(headers, unknown):
    """OCR 로 '(당)'·'(전)' 을 못 읽은 기간 머리글 채우기 — 텍스트 레이어에서는 할 일이 없다

    · '제40(&)기' 처럼 기수는 읽었으면 기수로: 당기 기수와 같으면 당기, 하나 작으면 전기
    · 머리글이 통째로 깨졌으면('mre)!') 기간 영역 안에 있을 때만, 당기·전기 중 빠진 쪽으로
    """
    known = {h["term"]: h["label"] for h in headers if h["label"] in ("당기", "전기") and h["term"]}
    current = next((int(t) for t, lab in known.items() if lab == "당기"), None)
    if current is None:
        current = next((int(t) + 1 for t, lab in known.items() if lab == "전기"), None)
    for h in headers:
        if h["label"] not in PERIODS and h["term"] and current is not None:
            h["label"] = {current: "당기", current - 1: "전기"}.get(int(h["term"]), h["label"])
    labels = {h["label"] for h in headers}
    if headers and len(labels & {"당기", "전기"}) == 1 and len(unknown) >= 1:
        start = min(h["x0"] for h in headers)
        inside = [u for u in unknown if u["x0"] > start]
        if len(inside) == 1:
            inside[0]["label"] = "전기" if "당기" in labels else "당기"
            headers.append(inside[0])
    return [{k: h[k] for k in ("label", "x0", "x1")} for h in sorted(headers, key=lambda h: h["x0"])]


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
        # 줄 순서 → 줄 안 x 순서 그대로 (_visual_rows 가 줄마다 x 로 정렬해 둠). 윗변 y 로 다시
        # 정렬하면 글자마다 높이가 다른 OCR 한글이 '기초상품재고액' → '기상재액초품고' 로 섞인다
        for w in r["words"]:
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
        account, _ = normalize_account(OCR_ROMAN_PREFIX.sub("", "".join(label)))
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


def _evaluate_ocr(doc, pages, layouts, text_rows):
    """OCR 세 가지 조건을 텍스트 레이어 행과 칸 단위로 비교

    ocr_values   1단계(페이지 전체 OCR) · 열 배치는 텍스트 레이어에서 빌림 — 2026-09-26 기준선과 같은 조건
    ocr2_values  2단계(금액 칸 재판독) · 열 배치 빌림
    scan_values  2단계 · 열 배치도 OCR 로 찾음 — 텍스트 레이어가 없는 스캔 PDF 와 같은 조건
    """
    out = {}
    ocr_words = [(p, merge_numeric_fragments(words_from_ocr(doc[p]))) for p in pages]
    ocr_rows = extract_by_coordinates(ocr_words, layouts, parse_amount_lenient)
    out["ocr_values"] = compare_by_position(text_rows, ocr_rows)
    out["ocr_labels"] = label_accuracy(text_rows, ocr_rows)
    try:
        scan_layouts = detect_layouts(ocr_words)
    except ValueError as e:
        scan_layouts, out["scan_error"] = {}, str(e)
    reread = []
    for p, words in ocr_words:
        layout = scan_layouts.get(p) or layouts.get(p)
        if layout:
            reread.append((p, reread_numbers(doc[p], words, layout["period_x0"])))
    out["ocr2_values"] = compare_by_position(
        text_rows, extract_by_coordinates(reread, layouts, parse_amount_lenient))
    scan_rows = extract_by_coordinates(reread, scan_layouts, parse_amount_lenient)
    out["scan_values"] = compare_by_position(text_rows, scan_rows)
    out["scan_labels"] = label_accuracy(text_rows, scan_rows)
    return out


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
            entry.update(_evaluate_ocr(doc, pages, layouts, text_rows))
        report["statements"][stype] = entry
    return report


if __name__ == "__main__":
    use_ocr = "--ocr" in sys.argv
    for pdf in [a for a in sys.argv[1:] if not a.startswith("--")]:
        print(json.dumps(evaluate(pdf, ocr=use_ocr), ensure_ascii=False, indent=2, default=str))
