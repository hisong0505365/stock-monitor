from api_client import DemoClient
from demo_data import DEMO_HOSPITALS
from map_maker import kakao_directions_url, make_map

SNUH = DEMO_HOSPITALS[0]


def render(m):
    return m.get_root().render()


def test_map_shows_hospital_radius_and_numbered_pharmacies():
    pharmacies = DemoClient().find_pharmacies(SNUH.lat, SNUH.lon, 500)
    html = render(make_map(SNUH, pharmacies, 500))

    assert SNUH.name in html
    assert '"radius": 500' in html
    assert pharmacies[0].name in html and pharmacies[-1].name in html
    assert f"\\u003e{len(pharmacies)}\\u003c/div\\u003e" in html   # 마지막 순번 마커 (JSON 이스케이프됨)
    assert "markerClusterGroup" not in html


def test_many_pharmacies_are_clustered():
    pharmacies = DemoClient().find_pharmacies(SNUH.lat, SNUH.lon, 3000)
    many = pharmacies * 3
    html = render(make_map(SNUH, many, 3000))
    assert "markerClusterGroup" in html
    assert '"disableClusteringAtZoom": 17' in html


def test_names_are_html_escaped_in_popups():
    pharmacy = DemoClient().find_pharmacies(SNUH.lat, SNUH.lon, 300)[0]
    evil = pharmacy.__class__(**{**pharmacy.__dict__, "name": "<script>x</script>약국"})
    html = render(make_map(SNUH, [evil], 300))
    assert "<script>x</script>약국" not in html
    assert "&lt;script&gt;x&lt;/script&gt;약국" in html


def test_kakao_directions_url_encodes_name():
    url = kakao_directions_url("온누리 약국,1", 37.5, 127.0)
    assert url == "https://map.kakao.com/link/to/%EC%98%A8%EB%88%84%EB%A6%AC%20%EC%95%BD%EA%B5%AD%2C1,37.5,127.0"
