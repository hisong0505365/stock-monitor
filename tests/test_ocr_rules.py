# OCR 후처리 규칙 — 2026-09-27 OCR 정확도 개선에서 찾은 문제의 회귀 테스트
#
# 대부분 Tesseract 없이 돈다(합성 이미지·합성 단어 좌표). 맨 아래 한 건만 실제 PDF 와
# Tesseract 가 있어야 돈다(RUN_OCR_TESTS=1, 문서당 약 1분).
import glob
import os
import shutil

import numpy as np
import pytest

from parsing_accuracy import (
    _find_header, _period_headers, _remove_table_lines, _rows_to_records, _visual_rows,
    merge_numeric_fragments, parse_amount_lenient,
)


def _w(x0, x1, y, text, h=8):
    return (x0, y - h / 2, x1, y + h / 2, text)


# ===== 표 선 제거 =====

def test_표_선은_지우고_세로로_정렬된_숫자_획은_남긴다():
    """오른쪽 정렬 금액의 '1' 세로획이 같은 x 에 수십 행 겹치면, 예전 규칙(세로 픽셀 합 >
    높이 15%)은 이를 세로선으로 보고 지웠다 → '1'→'7', '3'→'8' 오인식의 주원인"""
    img = np.full((1000, 600), 255, np.uint8)
    img[100, 20:580] = 0                       # 가로 테두리
    img[50:950, 300] = 0                       # 세로 테두리 (끊김 없음)
    for row in range(13):   # 13행에 걸친 '1' 세로획 — 300dpi 실제 비율: 글자 37px, 행 간격 62px
        y = 110 + row * 62
        img[y:y + 37, 450:453] = 0
    assert (img[:, 450:453] == 0).sum(axis=0).min() > 1000 * 0.15   # 예전 규칙이면 '세로선'
    out = _remove_table_lines(img)
    assert (out[100, 20:580] == 255).all()
    assert (out[50:950, 300] == 255).all()
    assert (out[110:147, 450:453] == 0).all()                 # 숫자 획은 그대로
    strokes = slice(105, 1000)                                # 가로 테두리(y=100) 아래
    assert ((out[strokes, 450:453] == 0) == (img[strokes, 450:453] == 0)).all()


# ===== 숫자 조각 합치기 =====

def test_공백으로_갈라진_숫자_조각을_잇는다():
    words = [_w(300, 340, 100, "3,309,341"), _w(342, 370, 100, "062,502)")]
    assert [w[4] for w in merge_numeric_fragments(words)] == ["3,309,341062,502)"]


def test_쉼표로_끝난_조각_위에_겹친_조각을_잇는다():
    """지오영 '36,930,695,735' → '36,930,695,' + 겹친 '735' (y 가 436.8 과 436.4 로 갈림)"""
    words = [_w(359.8, 408.5, 436.8, "36,930,695,"), _w(410.9, 424.6, 436.4, "735"),
             _w(239.5, 281.8, 436.8, "4,5,6,9,35")]
    merged = [w[4] for w in merge_numeric_fragments(words)]
    assert "36,930,695,735" in merged and "735" not in merged


def test_왼쪽_열의_숫자와_오른쪽_대시는_합치지_않는다():
    """경동사 '기부금 118,000 | -' — 대시가 먼저 정렬돼 왼쪽 숫자를 '겹침'으로 삼키던 문제"""
    words = [_w(454.6, 459.1, 286.4, "-"), _w(257.0, 289.2, 286.8, "118,000")]
    merged = sorted(merge_numeric_fragments(words))
    assert [w[4] for w in merged] == ["118,000", "-"]


@pytest.mark.parametrize("text, value", [
    ("(1,234)", -1234), ("1,234)", -1234), ("1.234.567", 1234567), ("-", 0), ("12a", None),
])
def test_OCR_금액_읽기(text, value):
    assert parse_amount_lenient(text) == value


# ===== 머리글 · 계정명 조립 =====

def test_OCR_머리글_과목을_못_읽어도_기간이_둘이면_머리글():
    rows = _visual_rows([
        _w(171, 180, 79, "제"), _w(184, 195, 79, "21"), _w(202, 208, 79, "기"),   # 표지 기간 줄
        _w(53, 70, 140, "oS"),                                                  # '과 목'
        _w(180, 188, 140, "제"), _w(191, 204, 140, "21("), _w(206, 211, 140, "당"),
        _w(212, 215, 140, ")"), _w(221, 226, 140, "기"),
        _w(364, 372, 140, "제"), _w(376, 389, 140, "20("), _w(390, 395, 140, "전"),
        _w(396, 399, 140, ")"), _w(405, 410, 140, "기"),
    ])
    assert rows[_find_header(rows)]["y"] == 140


def test_과목_줄이_있으면_그_위_두_줄_머리글보다_우선():
    """아주약품 재무상태표: '제1(전)기말 … 제1(전)기초' 윗줄에도 기간이 둘"""
    rows = _visual_rows([
        _w(327, 360, 100, "제 1(전) 기말"), _w(437, 470, 100, "제 1(전) 기초"),
        _w(52, 60, 110, "과"), _w(76, 84, 110, "목"), _w(216, 250, 110, "제 2(당) 기말"),
    ])
    assert rows[_find_header(rows)]["y"] == 110


def test_OCR_기간_머리글_글자_조각을_x_순서로_잇는다():
    """윗변 y 로 정렬하면 '제' '21(' '당' ')' '기' 가 섞여 기간을 못 읽었다"""
    words = [_w(180, 188, 140.4, "제"), _w(191, 204, 139.8, "21("), _w(206, 211, 140.6, "당"),
             _w(212, 215, 139.9, ")"), _w(221, 226, 140.2, "기")]
    assert [h["label"] for h in _period_headers(words, 100)] == ["당기"]


def test_당_을_못_읽으면_기수로_당기_전기를_정한다():
    """경동사: '제40(당)기' 를 '제40(&)기' 로 읽음"""
    words = [_w(203, 212, 171, "제"), _w(214, 240, 171, "40(&)"), _w(244, 250, 171, "기"),
             _w(376, 385, 171, "제"), _w(387, 400, 171, "39("), _w(402, 407, 171, "전"),
             _w(408, 411, 171, ")"), _w(417, 422, 171, "기")]
    assert [h["label"] for h in _period_headers(words, 100)] == ["당기", "전기"]


def test_통째로_깨진_기간_머리글은_빠진_기간으로():
    """아주약품 손익계산서: '제 1(전) 기' 를 'mre)!' 로 읽음"""
    words = [_w(239, 247, 171, "제"), _w(249, 256, 171, "2("), _w(258, 263, 171, "당"),
             _w(264, 268, 171, ")"), _w(271, 276, 171, "기"), _w(394, 420, 171, "mre)!"),
             _w(394, 470, 182, "(감사받지않은재무제표)")]
    assert [h["label"] for h in _period_headers(words, 100)] == ["당기", "전기"]


def test_OCR_계정명은_줄_순서와_x_순서로_잇고_머리표_주석을_지운다():
    """'기초상품재고액' → '기상재액초품고'(글자마다 윗변 높이가 달라 섞임),
    '( 주 석 3)' 은 띄어져 주석 참조로 안 지워짐, 'Ⅰ.' → '|.'"""
    layout = {"period_x0": 200, "edges": [300], "period_of": ["당기"]}
    glyphs = "기초상품재고액"
    tops = [0.6, -0.4, 0.3, -0.2, 0.5, -0.5, 0.1]
    words = [_w(53, 58, 100, "|.")] + [
        _w(60 + i * 8, 67 + i * 8, 100 + t, g) for i, (g, t) in enumerate(zip(glyphs, tops))]
    words += [_w(120, 124, 100, "("), _w(126, 132, 100, "주"), _w(134, 140, 100.6, "석"),
              _w(142, 150, 100, "3)"), _w(250, 300, 100, "1,234")]
    records = _rows_to_records(0, _visual_rows(words), layout, parse_amount_lenient)
    assert records[0]["account"] == "기초상품재고액"
    assert records[0]["values"] == {"당기": 1234}


# ===== 실제 PDF + Tesseract =====

PDF_DIR = os.environ.get("AUDIT_PDF_DIR", "")


@pytest.mark.skipif(not (os.environ.get("RUN_OCR_TESTS") and shutil.which("tesseract")
                         and glob.glob(os.path.join(PDF_DIR, "c7b5fece*.pdf"))),
                    reason="RUN_OCR_TESTS=1 · tesseract(kor) · AUDIT_PDF_DIR 에 경동사 감사보고서 필요")
def test_경동사_스캔_조건_OCR_이_텍스트_레이어와_모든_칸에서_일치():
    """열 배치까지 OCR 로 찾는 조건(스캔 PDF 와 같음). 2026-09-27 이전 316칸 중 10칸 오류"""
    from parsing_accuracy import evaluate
    report = evaluate(glob.glob(os.path.join(PDF_DIR, "c7b5fece*.pdf"))[0], ocr=True)
    for stype, entry in report["statements"].items():
        assert entry["scan_values"]["errors"] == [], stype
