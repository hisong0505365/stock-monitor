import os

import streamlit as st
from streamlit_folium import st_folium

from api_client import REGIONS, ApiError, make_client
from demo_data import DEMO_HOSPITALS
from geo_utils import RADIUS_OPTIONS_M, format_distance, walk_minutes
from map_maker import kakao_directions_url, make_map

# ===== 페이지 설정 =====
st.set_page_config(
    page_title="병원 근처 약국 찾기",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

MAP_HEIGHT = 620
MARKDOWN_SPECIAL = str.maketrans({c: "\\" + c for c in "\\`*_[]<>#|~$"})


def load_service_key():
    """공공데이터포털 인증키: .streamlit/secrets.toml → 환경변수 순서로 찾는다"""
    try:
        key = st.secrets.get("DATA_GO_KR_SERVICE_KEY", "")
    except FileNotFoundError:
        key = ""
    return key or os.environ.get("DATA_GO_KR_SERVICE_KEY", "")


def md(text):
    return text.translate(MARKDOWN_SPECIAL)


# ===== 캐시된 조회 (같은 검색은 1시간 동안 API를 다시 부르지 않음) =====
@st.cache_data(ttl=3600, show_spinner=False)
def search_hospitals(service_key, name, region):
    return make_client(service_key).search_hospitals(name, region)


@st.cache_data(ttl=3600, show_spinner=False)
def find_pharmacies(service_key, lat, lon, radius_m):
    return make_client(service_key).find_pharmacies(lat, lon, radius_m)


def widen_radius():
    idx = RADIUS_OPTIONS_M.index(st.session_state.radius)
    st.session_state.radius = RADIUS_OPTIONS_M[min(idx + 1, len(RADIUS_OPTIONS_M) - 1)]


service_key = load_service_key()
demo_mode = not service_key

st.session_state.setdefault("hospitals", None)   # None: 아직 검색 전
st.session_state.setdefault("radius", 500)

# ===== 사이드바: 검색 → 병원 선택 → 반경 =====
with st.sidebar:
    st.header("🏥 병원 근처 약국 찾기")

    with st.form("search_form"):
        query = st.text_input("병원 이름", placeholder="예: 서울대학교병원")
        region = st.selectbox("지역", ["전체", *REGIONS])
        submitted = st.form_submit_button("🔍 검색", type="primary", width="stretch")

    if submitted:
        if not query.strip():
            st.warning("병원 이름을 입력하세요.")
        else:
            try:
                with st.spinner("병원 검색 중..."):
                    st.session_state.hospitals = search_hospitals(
                        service_key, query.strip(), None if region == "전체" else region
                    )
                st.session_state.hospital_idx = 0
            except ApiError as e:
                st.error(str(e))

    hospitals = st.session_state.hospitals
    selected = None
    if hospitals:
        st.markdown(f"**검색 결과 {len(hospitals)}건**")
        box = st.container(height=320) if len(hospitals) > 5 else st.container()
        with box:
            idx = st.radio(
                "병원 선택",
                options=list(range(len(hospitals))),
                format_func=lambda i: md(f"{hospitals[i].name} ({hospitals[i].kind})"),
                captions=[md(h.address) for h in hospitals],
                key="hospital_idx",
                label_visibility="collapsed",
            )
        selected = hospitals[idx]

    st.select_slider("검색 반경", options=RADIUS_OPTIONS_M, format_func=format_distance, key="radius")

    st.divider()
    st.caption("ⓘ 공공데이터 기준 정보입니다. 휴·폐업이나 영업시간은 방문 전 전화로 확인하세요.")

# ===== 메인 =====
st.title("💊 병원 근처 약국 찾기")

if demo_mode:
    st.info(
        "🧪 **데모 모드** — API 인증키가 없어 가상의 약국 데이터로 동작합니다 (실제 약국 정보가 아닙니다).  \n"
        f"검색해 볼 수 있는 병원: {', '.join(h.name for h in DEMO_HOSPITALS)}  \n"
        "실제 데이터를 보려면 README의 인증키 설정 방법을 따라주세요."
    )

if hospitals is None:
    st.markdown(
        "#### 사용 방법\n"
        "1. 왼쪽에서 **병원 이름**을 검색하세요.\n"
        "2. 검색 결과에서 **병원을 선택**하세요.\n"
        "3. **검색 반경**을 고르면 주변 약국이 지도와 목록에 거리순으로 표시됩니다."
    )
    st.stop()

if not hospitals:
    st.warning(
        "검색 결과가 없습니다. 병원의 **공식 명칭 일부**로 검색해 보세요. "
        "(예: 서울대병원 → 서울대학교)"
    )
    st.stop()

radius_m = st.session_state.radius
try:
    with st.spinner("주변 약국 찾는 중..."):
        pharmacies = find_pharmacies(service_key, selected.lat, selected.lon, radius_m)
except ApiError as e:
    st.error(str(e))
    st.stop()

# ----- 선택 병원 + 요약 카드 -----
st.subheader(f"🏥 {md(selected.name)}")
st.caption(md(" · ".join(x for x in [selected.kind, selected.address, selected.tel] if x)))

c1, c2, c3 = st.columns(3)
c1.metric("검색 반경", format_distance(radius_m))
c2.metric("약국 수", f"{len(pharmacies)}곳")
if pharmacies:
    nearest = pharmacies[0]
    c3.metric("가장 가까운 약국", format_distance(nearest.distance_m), nearest.name,
              delta_color="off", delta_arrow="off")
else:
    c3.metric("가장 가까운 약국", "-")

if not pharmacies:
    st.warning(f"반경 {format_distance(radius_m)} 안에 약국이 없습니다.")
    if radius_m < RADIUS_OPTIONS_M[-1]:
        st.button("반경 넓히기", on_click=widen_radius)

# ----- 지도 + 목록 -----
map_col, list_col = st.columns([2, 1])

with map_col:
    st_folium(
        make_map(selected, pharmacies, radius_m),
        height=MAP_HEIGHT,
        use_container_width=True,
        returned_objects=[],
    )

with list_col:
    st.markdown("**약국 목록 (거리순)**")
    with st.container(height=MAP_HEIGHT - 40):
        if not pharmacies:
            st.caption("표시할 약국이 없습니다.")
        for rank, p in enumerate(pharmacies, start=1):
            tel = f"📞 {md(p.tel)}" if p.tel else "📞 전화번호 없음"
            st.markdown(
                f"**{rank}. {md(p.name)}** · {format_distance(p.distance_m)} · 도보 약 {walk_minutes(p.distance_m)}분  \n"
                f"{md(p.address)}  \n"
                f"{tel} · [길찾기]({kakao_directions_url(p.name, p.lat, p.lon)})"
            )
