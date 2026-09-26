from dataclasses import replace
from math import asin, cos, radians, sin, sqrt

from models import Pharmacy

EARTH_RADIUS_M = 6_371_000
METERS_PER_DEGREE_LAT = 111_320
WALK_SPEED_M_PER_MIN = 67   # 시속 약 4km

RADIUS_OPTIONS_M = [300, 500, 1000, 2000, 3000]


def haversine_m(lat1, lon1, lat2, lon2):
    """두 위경도 사이의 직선거리(m)"""
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def walk_minutes(distance_m):
    """직선거리 기준 예상 도보시간(분), 최소 1분"""
    return max(1, round(distance_m / WALK_SPEED_M_PER_MIN))


def format_distance(distance_m):
    """80 → '80m', 1000 → '1km', 1234 → '1.2km'"""
    if round(distance_m) < 1000:
        return f"{round(distance_m)}m"
    return f"{distance_m / 1000:.1f}".rstrip("0").rstrip(".") + "km"


def within_radius(lat, lon, pharmacies, radius_m):
    """기준점에서 반경 안의 약국만 남기고 거리순으로 정렬"""
    result = []
    for p in pharmacies:
        d = haversine_m(lat, lon, p.lat, p.lon)
        if d <= radius_m:
            result.append(replace(p, distance_m=d))
    return sorted(result, key=lambda p: p.distance_m)


def bounding_box(lat, lon, radius_m):
    """반경 원을 감싸는 사각형 [[남, 서], [북, 동]] (지도 fit_bounds 용)"""
    dlat = radius_m / METERS_PER_DEGREE_LAT
    dlon = radius_m / (METERS_PER_DEGREE_LAT * cos(radians(lat)))
    return [[lat - dlat, lon - dlon], [lat + dlat, lon + dlon]]


def offset_point(lat, lon, north_m, east_m):
    """기준점에서 북쪽/동쪽으로 이동한 좌표 (데모 데이터 생성용)"""
    return (
        lat + north_m / METERS_PER_DEGREE_LAT,
        lon + east_m / (METERS_PER_DEGREE_LAT * cos(radians(lat))),
    )
