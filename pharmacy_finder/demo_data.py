"""
데모 모드용 데이터 (API 인증키가 없을 때 화면 확인용)
- 병원: 실제 병원 이름과 대략적인 위치
- 약국: 병원 주변에 자동 배치한 가상의 약국 (실제 약국 정보가 아님)
"""
from math import cos, radians, sin

from geo_utils import offset_point
from models import Hospital, Pharmacy

DEMO_HOSPITALS = [
    Hospital("demo-snuh", "서울대학교병원", "상급종합", "서울특별시 종로구 대학로 101", "", 37.5796, 126.9990),
    Hospital("demo-snudh", "서울대학교치과병원", "치과병원", "서울특별시 종로구 대학로 101", "", 37.5807, 126.9975),
    Hospital("demo-sev", "세브란스병원", "상급종합", "서울특별시 서대문구 연세로 50-1", "", 37.5622, 126.9409),
    Hospital("demo-smc", "삼성서울병원", "상급종합", "서울특별시 강남구 일원로 81", "", 37.4882, 127.0855),
    Hospital("demo-amc", "서울아산병원", "상급종합", "서울특별시 송파구 올림픽로43길 88", "", 37.5265, 127.1084),
    Hospital("demo-pnuh", "부산대학교병원", "상급종합", "부산광역시 서구 구덕로 179", "", 35.1003, 129.0172),
]

# 병원에서 떨어진 거리(m). 문전약국처럼 가까운 곳에 몰리고 멀수록 드문드문
_DISTANCES_M = [60, 85, 110, 150, 190, 240, 290, 350, 420, 480, 560, 700, 850,
                1000, 1200, 1450, 1700, 2000, 2300, 2700, 2950, 3400]
_GOLDEN_ANGLE_DEG = 137.5


def _make_pharmacies():
    pharmacies = []
    for letter, hospital in zip("ABCDEFGHIJ", DEMO_HOSPITALS):
        region = " ".join(hospital.address.split()[:2])
        for i, distance in enumerate(_DISTANCES_M, start=1):
            angle = radians(i * _GOLDEN_ANGLE_DEG)
            lat, lon = offset_point(hospital.lat, hospital.lon, distance * cos(angle), distance * sin(angle))
            pharmacies.append(Pharmacy(
                id=f"{hospital.id}-{i:02d}",
                name=f"데모약국 {letter}-{i:02d}",
                address=f"{region} (데모 주소)",
                tel="",
                lat=lat,
                lon=lon,
            ))
    return pharmacies


DEMO_PHARMACIES = _make_pharmacies()
