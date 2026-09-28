import html
from urllib.parse import quote

import folium
from folium.plugins import MarkerCluster

from geo_utils import bounding_box, format_distance, walk_minutes

RADIUS_COLOR = "#2563eb"
PHARMACY_COLOR = "#16a34a"
NEAREST_COLOR = "#14532d"
CLUSTER_THRESHOLD = 40   # 약국이 이보다 많으면 마커 묶음 표시 (문전약국 밀집 대비)


def kakao_directions_url(name, lat, lon):
    return f"https://map.kakao.com/link/to/{quote(name, safe='')},{lat},{lon}"


def _hospital_popup(hospital):
    tel = html.escape(hospital.tel) if hospital.tel else "전화번호 없음"
    return (
        '<div style="font-size:13px;line-height:1.5;min-width:180px">'
        f"<b>🏥 {html.escape(hospital.name)}</b> ({html.escape(hospital.kind)})<br>"
        f"{html.escape(hospital.address)}<br>"
        f"📞 {tel}"
        "</div>"
    )


def _pharmacy_popup(rank, pharmacy):
    tel = (
        f'<a href="tel:{html.escape(pharmacy.tel)}">{html.escape(pharmacy.tel)}</a>'
        if pharmacy.tel else "전화번호 없음"
    )
    url = kakao_directions_url(pharmacy.name, pharmacy.lat, pharmacy.lon)
    return (
        '<div style="font-size:13px;line-height:1.5;min-width:180px">'
        f"<b>{rank}. {html.escape(pharmacy.name)}</b><br>"
        f"{html.escape(pharmacy.address)}<br>"
        f"📍 {format_distance(pharmacy.distance_m)} · 도보 약 {walk_minutes(pharmacy.distance_m)}분<br>"
        f"📞 {tel}<br>"
        f'<a href="{url}" target="_blank" rel="noopener">카카오맵 길찾기</a>'
        "</div>"
    )


def _number_icon(rank, color):
    return folium.DivIcon(
        html=(
            f'<div style="background:{color};color:#fff;border:2px solid #fff;border-radius:50%;'
            "width:26px;height:26px;line-height:22px;text-align:center;font-size:12px;"
            f'font-weight:700;box-shadow:0 1px 4px rgba(0,0,0,.4)">{rank}</div>'
        ),
        icon_size=(26, 26),
        icon_anchor=(13, 13),
    )


def make_map(hospital, pharmacies, radius_m):
    """병원 마커 + 반경 원 + 거리순 번호가 붙은 약국 마커"""
    center = [hospital.lat, hospital.lon]
    m = folium.Map(location=center, tiles="OpenStreetMap", control_scale=True)

    folium.Circle(
        location=center,
        radius=radius_m,
        color=RADIUS_COLOR,
        weight=2,
        fill=True,
        fill_opacity=0.08,
        tooltip=f"반경 {format_distance(radius_m)}",
    ).add_to(m)

    folium.Marker(
        center,
        icon=folium.Icon(color="red", icon="plus-sign"),
        tooltip=html.escape(hospital.name),
        popup=folium.Popup(_hospital_popup(hospital), max_width=300),
        z_index_offset=1000,
    ).add_to(m)

    layer = m
    if len(pharmacies) > CLUSTER_THRESHOLD:
        layer = MarkerCluster(disable_clustering_at_zoom=17).add_to(m)

    for rank, p in enumerate(pharmacies, start=1):
        folium.Marker(
            [p.lat, p.lon],
            icon=_number_icon(rank, NEAREST_COLOR if rank == 1 else PHARMACY_COLOR),
            tooltip=f"{rank}. {html.escape(p.name)} · {format_distance(p.distance_m)}",
            popup=folium.Popup(_pharmacy_popup(rank, p), max_width=300),
        ).add_to(layer)

    m.fit_bounds(bounding_box(hospital.lat, hospital.lon, radius_m))
    return m
