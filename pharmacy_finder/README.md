# 💊 병원 근처 약국 찾기

병원을 검색하고 반경(300m ~ 3km)을 고르면, 주변 약국을 지도와 거리순 목록으로 보여주는 Streamlit 앱입니다.
기획 내용은 [PLAN.md](PLAN.md)를 참고하세요.

## 실행

```bash
cd pharmacy_finder
pip install -r requirements.txt
streamlit run app.py
```

인증키가 없으면 **데모 모드**로 실행됩니다. 데모 모드에서는 몇몇 병원 주변에 가상의 약국을 배치해 화면만 확인할 수 있습니다.
(검색 예: `서울대학교`, `세브란스`, `삼성서울`, `서울아산`, `부산대학교`)

> 지도는 인터넷에서 Leaflet 라이브러리(cdn.jsdelivr.net)와 OpenStreetMap 타일을 불러오므로 인터넷 연결이 필요합니다.

## 실제 데이터 사용하기 (공공데이터포털 인증키)

1. [공공데이터포털](https://www.data.go.kr)에 가입한 뒤 아래 두 API를 **활용신청**합니다.
   - [건강보험심사평가원_병원정보서비스](https://www.data.go.kr/data/15001698/openapi.do): 병원 검색
   - [건강보험심사평가원_약국정보서비스](https://www.data.go.kr/data/15001673/openapi.do): 반경 내 약국 조회
2. 마이페이지에서 **일반 인증키**를 복사합니다. Encoding·Decoding 키 중 어느 것을 넣어도 됩니다.
3. 키를 설정합니다. 둘 중 하나를 고르세요.
   ```bash
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # 파일을 열어 키 입력
   # 또는
   export DATA_GO_KR_SERVICE_KEY="발급받은_키"
   ```
4. `streamlit run app.py`로 실행하면 데모 모드 안내가 사라지고 실제 데이터로 동작합니다.

활용신청 승인 직후에는 키가 동작하기까지 시간이 걸릴 수 있습니다. 그 사이에는 "등록되지 않은 인증키" 오류가 날 수 있습니다.

## 테스트

```bash
cd pharmacy_finder
python -m pytest
```

네트워크 없이 실행됩니다. API 응답은 샘플 XML로 대신합니다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `app.py` | Streamlit 화면 (사이드바 검색 → 병원 선택 → 반경, 지도 + 약국 목록) |
| `api_client.py` | 심평원 API 호출·XML 파싱(`HiraClient`), 데모 데이터 클라이언트(`DemoClient`) |
| `geo_utils.py` | 하버사인 거리, 도보시간, 반경 필터, 거리 표기 |
| `map_maker.py` | folium 지도 (병원 마커, 반경 원, 번호 붙은 약국 마커, 팝업, 길찾기 링크) |
| `models.py` | `Hospital`, `Pharmacy` 데이터 클래스 |
| `demo_data.py` | 데모 모드용 병원·가상 약국 데이터 |
