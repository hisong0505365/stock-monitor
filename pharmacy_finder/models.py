from dataclasses import dataclass


@dataclass(frozen=True)
class Hospital:
    id: str            # 심평원 암호화 요양기호(ykiho)
    name: str
    kind: str          # 종별: 상급종합 / 종합병원 / 병원 / 의원 ...
    address: str
    tel: str
    lat: float         # 위도 (심평원 YPos)
    lon: float         # 경도 (심평원 XPos)


@dataclass(frozen=True)
class Pharmacy:
    id: str
    name: str
    address: str
    tel: str
    lat: float
    lon: float
    distance_m: float = 0.0   # 기준 병원과의 직선거리
