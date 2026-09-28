# 병원 근처 약국 찾기 (pharmacy_finder)

병원을 검색하고 반경(300m~3km)을 고르면 주변 약국을 지도(folium)와 거리순 목록으로 보여주는 Streamlit 앱.
기획은 `PLAN.md`, 사용법은 `README.md` 참고. 사용자는 한국어로 소통한다.

## 명령어

```
pip install -r requirements.txt
streamlit run app.py          # 인증키 없으면 데모 모드로 실행
python -m pytest              # 네트워크 없이 실행되는 단위 테스트
```

## 구조

- `app.py`: Streamlit 화면 (사이드바 검색 → 병원 선택 → 반경, 메인에 지도 + 목록)
- `api_client.py`: 심평원 API 호출·XML 파싱(`HiraClient`), 데모용 `DemoClient`, `make_client()`
- `geo_utils.py`: 하버사인 거리, 반경 필터(`within_radius`), 도보시간, 거리 표기
- `map_maker.py`: folium 지도 (병원 마커, 반경 원, 번호 붙은 약국 마커, 팝업, 카카오맵 길찾기 링크)
- `models.py`: `Hospital`, `Pharmacy` (frozen dataclass)
- `demo_data.py`: 데모 병원(실제 이름·대략 위치) + 가상 약국
- 모듈은 한 폴더에 평평하게 두고 `from geo_utils import ...`처럼 import한다 (`pytest.ini`의 `pythonpath = .`)

## 반드시 지킬 것

- **좌표 순서**: 심평원 응답은 `XPos` = 경도, `YPos` = 위도. 카카오는 `x` = 경도, `y` = 위도. folium은 `[위도, 경도]`.
  API 응답을 받는 즉시 `lat` / `lon` 필드로 바꾸고, 그 뒤 코드에서는 `x`/`y`를 쓰지 않는다.
- **인증키**: `.streamlit/secrets.toml`의 `DATA_GO_KR_SERVICE_KEY` 또는 같은 이름의 환경변수. 절대 커밋하지 않는다 (`.gitignore`에 있음).
  `HiraClient`는 Encoding 키(`%` 포함)를 받으면 Decoding 키로 되돌린다.
- **데모 모드**: 키가 없으면 `DemoClient`를 쓴다. 가상 약국이 실제 정보처럼 보이지 않도록 화면의 데모 안내를 유지한다.
- **이스케이프**: API에서 온 문자열은 지도 팝업에서 `html.escape`, Streamlit 마크다운에서 `md()`로 감싼다.
- **거리**: API가 준 거리를 그대로 쓰지 않고 `within_radius`로 다시 계산해 반경 필터 + 거리순 정렬한다.
- **테스트**: 실제 API를 부르지 않는다. `tests/test_api_client.py`의 `FakeSession` + 샘플 XML 방식으로 추가한다.
  기능을 바꾸면 테스트를 함께 추가하고 `python -m pytest` 통과를 확인한다.

## 현재 상태

- PLAN.md 1단계(MVP) 구현 완료, 테스트 32개 통과.
- **아직 확인 못 한 것**:
  1. 실제 인증키로 API 호출. 응답 필드명(`yadmNm`, `addr`, `telno`, `XPos`, `YPos`, `clCdNm`, `ykiho`)이 파싱 코드와 맞는지 확인이 필요하다.
  2. 브라우저에서 지도가 실제로 그려지는지. 개발했던 환경에서는 Leaflet CDN과 OSM 타일이 차단돼 있었다.
- 다음 작업은 `PLAN.md` 9장 2단계 목록 (주소 검색, 운영시간/지금 영업 중, 약칭 검색 보완, SQLite 적재).

## Git

원본은 GitHub `hisong0505365/stock-monitor` 저장소 `claude/hospital-pharmacy-finder-nmzobx` 브랜치의 `pharmacy_finder/` 폴더다 (PR #1).
이 폴더가 zip으로 받은 사본이라 git에 연결돼 있지 않다면, 로컬 변경은 PR에 자동으로 반영되지 않는다.
PR에 올리는 방법은 사용자에게 먼저 확인한다.
