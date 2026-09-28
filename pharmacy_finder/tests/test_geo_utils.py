import pytest

from geo_utils import (
    bounding_box, format_distance, haversine_m, offset_point, walk_minutes, within_radius,
)
from models import Pharmacy

SNUH = (37.5796, 126.9990)   # 서울대학교병원 부근


def make_pharmacy(name, lat, lon):
    return Pharmacy(id=name, name=name, address="", tel="", lat=lat, lon=lon)


def test_one_degree_of_latitude_is_about_111km():
    assert haversine_m(0, 0, 1, 0) == pytest.approx(111_195, rel=1e-4)


def test_same_point_is_zero_and_distance_is_symmetric():
    a, b = SNUH, (37.5622, 126.9409)
    assert haversine_m(*a, *a) == 0
    assert haversine_m(*a, *b) == pytest.approx(haversine_m(*b, *a))


def test_offset_point_moves_the_requested_distance():
    lat, lon = offset_point(*SNUH, north_m=300, east_m=400)
    assert haversine_m(*SNUH, lat, lon) == pytest.approx(500, rel=0.01)


@pytest.mark.parametrize("distance, minutes", [(0, 1), (30, 1), (670, 10), (2010, 30)])
def test_walk_minutes(distance, minutes):
    assert walk_minutes(distance) == minutes


@pytest.mark.parametrize("distance, text", [
    (80.4, "80m"), (999.4, "999m"), (999.6, "1km"), (1000, "1km"), (1234, "1.2km"), (3000, "3km"),
])
def test_format_distance(distance, text):
    assert format_distance(distance) == text


def test_within_radius_drops_far_pharmacies_and_sorts_by_distance():
    far = make_pharmacy("far", *offset_point(*SNUH, 600, 0))
    near = make_pharmacy("near", *offset_point(*SNUH, 0, 100))
    middle = make_pharmacy("middle", *offset_point(*SNUH, -300, 0))

    result = within_radius(*SNUH, [far, middle, near], radius_m=500)

    assert [p.name for p in result] == ["near", "middle"]
    assert result[0].distance_m == pytest.approx(100, rel=0.01)
    assert result[1].distance_m == pytest.approx(300, rel=0.01)


def test_bounding_box_edges_are_radius_away_from_center():
    (south, west), (north, east) = bounding_box(*SNUH, 1000)
    lat, lon = SNUH
    for edge in [(north, lon), (south, lon), (lat, east), (lat, west)]:
        assert haversine_m(lat, lon, *edge) == pytest.approx(1000, rel=0.01)
