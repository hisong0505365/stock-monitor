import streamlit as st
import time
from datetime import datetime
from data_collector import (
    get_stock_history, get_stock_info, get_stock_list,
    get_top_by_market_cap, get_top_by_change
)
from chart_maker import make_combined_chart, make_comparison_chart, make_analysis_chart
from stock_analyzer import generate_signals

# ===== 페이지 설정 =====
st.set_page_config(
    page_title="Stock Monitor Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    /* 전체 배경 */
    .stApp {
        background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
    }
    
    /* 사이드바 */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #16213e 0%, #0f3460 100%);
        border-right: 1px solid #2a2a4a;
    }
    
    [data-testid="stSidebar"] * {
        color: #e0e0e0 !important;
    }
    
    /* 메인 헤더 */
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #2a2a4a;
        border-radius: 16px;
        padding: 24px 32px;
        margin-bottom: 20px;
        text-align: center;
    }
    
    .main-header h1 {
        color: #ffffff;
        font-size: 28px;
        font-weight: 700;
        margin: 0;
    }
    
    .main-header p {
        color: #8892b0;
        font-size: 14px;
        margin: 4px 0 0 0;
    }
    
    /* 메트릭 카드 */
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 20px 24px;
        text-align: center;
        transition: transform 0.2s, box-shadow 0.2s;
    }
    
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    }
    
    .metric-label {
        color: #8892b0;
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }
    
    .metric-value {
        font-size: 32px;
        font-weight: 700;
        margin-bottom: 4px;
    }
    
    .metric-value.price { color: #ffffff; }
    .metric-value.up { color: #00d26a; }
    .metric-value.down { color: #f92f60; }
    .metric-value.name { color: #64ffda; font-size: 22px; }
    
    .metric-delta {
        font-size: 14px;
        font-weight: 500;
    }
    
    .metric-delta.up { color: #00d26a; }
    .metric-delta.down { color: #f92f60; }
    
    /* 탭 스타일 */
    .stTabs [data-baseweb="tab-list"] {
        background: #1a1a2e;
        border-radius: 12px;
        padding: 4px;
        gap: 4px;
        border: 1px solid #2a2a4a;
    }
    
    .stTabs [data-baseweb="tab"] {
        color: #8892b0;
        border-radius: 8px;
        font-weight: 600;
        padding: 8px 16px;
    }
    
    .stTabs [aria-selected="true"] {
        background: #2563eb !important;
        color: #ffffff !important;
    }
    
    /* 신호 카드 */
    .signal-card {
        background: #1a1a2e;
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
    }
    
    .signal-total {
        font-size: 36px;
        font-weight: 800;
        text-align: center;
        padding: 16px;
        border-radius: 12px;
        margin-bottom: 16px;
    }
    
    .signal-buy {
        background: linear-gradient(135deg, #003d1a 0%, #00522a 100%);
        color: #00d26a;
        border: 1px solid #00d26a;
    }
    
    .signal-sell {
        background: linear-gradient(135deg, #3d0019 0%, #52002a 100%);
        color: #f92f60;
        border: 1px solid #f92f60;
    }
    
    .signal-hold {
        background: linear-gradient(135deg, #3d3200 0%, #524800 100%);
        color: #ffd700;
        border: 1px solid #ffd700;
    }
    
    .indicator-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 16px 20px;
        text-align: center;
    }
    
    .indicator-name {
        color: #8892b0;
        font-size: 13px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    .indicator-value {
        color: #ffffff;
        font-size: 28px;
        font-weight: 700;
        margin: 8px 0;
    }
    
    .indicator-signal {
        font-size: 14px;
        font-weight: 700;
        padding: 4px 12px;
        border-radius: 20px;
        display: inline-block;
    }
    
    .badge-buy { background: #003d1a; color: #00d26a; border: 1px solid #00d26a; }
    .badge-sell { background: #3d0019; color: #f92f60; border: 1px solid #f92f60; }
    .badge-neutral { background: #3d3200; color: #ffd700; border: 1px solid #ffd700; }
    
    /* 요약 정보 카드 */
    .info-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 24px;
    }
    
    .info-row {
        display: flex;
        justify-content: space-between;
        padding: 10px 0;
        border-bottom: 1px solid #2a2a4a;
    }
    
    .info-label { color: #8892b0; font-weight: 500; }
    .info-value { color: #ffffff; font-weight: 600; }
    
    /* 면책 조항 */
    .disclaimer {
        background: #1a1a2e;
        border: 1px solid #f92f60;
        border-radius: 8px;
        padding: 12px 16px;
        color: #f92f60;
        font-size: 13px;
        text-align: center;
        margin-top: 16px;
    }
    
    /* Streamlit 기본 요소 숨기기/수정 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    .stMetric { display: none; }
    
    h1, h2, h3, p, span, label, div {
        color: #e0e0e0;
    }
    
    .stDivider {
        border-color: #2a2a4a !important;
    }
    
    .stAlert {
        border-radius: 8px;
    }
    
    /* ===== 드롭다운 수정 ===== */
            
        /* 선택된 값 텍스트 */
    [data-baseweb="select"] > div {
        background-color: #16213e !important;
        color: #ffffff !important;
    }
    
    [data-baseweb="select"] span,
    [data-baseweb="select"] div[class*="ValueContainer"] *,
    [data-baseweb="select"] div[class*="singleValue"] * {
        color: #ffffff !important;
    }
    
    /* selectbox 전체 배경 */
    [data-baseweb="select"] div[class*="control"],
    [data-baseweb="select"] div:first-child {
        background-color: #16213e !important;
        border-color: #2a2a4a !important;
    }

    
    /* 사이드바 드롭다운 텍스트 */
    [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] {
        color: #ffffff !important;
        background-color: #1a1a3e !important;
        border: 1px solid #2a2a4a !important;
    }
    
    [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] * {
        color: #ffffff !important;
    }
    
        /* 드롭다운 목록 (펼쳤을 때) */
    [data-baseweb="menu"],
    [data-baseweb="popover"] {
        background-color: #16213e !important;
        border: 1px solid #2a2a4a !important;
    }
    
    [data-baseweb="menu"] li,
    [data-baseweb="menu"] ul li,
    [data-baseweb="menu"] div,
    [role="option"],
    [role="option"] * {
        color: #ffffff !important;
        background-color: #16213e !important;
    }
    
    [role="option"]:hover,
    [role="option"]:hover * {
        background-color: #2563eb !important;
        color: #ffffff !important;
    }
    
    /* 드롭다운 선택된 항목 */
    [aria-selected="true"][role="option"],
    [aria-selected="true"][role="option"] * {
        background-color: #2563eb !important;
        color: #ffffff !important;
    }
    
    /* 드롭다운 input 영역 */
    [data-baseweb="select"] input {
        color: #ffffff !important;
    }
    
    [data-baseweb="select"] [data-baseweb="tag"] {
        background-color: #2563eb !important;
        color: #ffffff !important;
    }

    
    /* 멀티셀렉트 (종목 비교) */
    [data-testid="stSidebar"] .stMultiSelect div[data-baseweb="select"] {
        color: #ffffff !important;
        background-color: #1a1a3e !important;
        border: 1px solid #2a2a4a !important;
    }
    
    [data-testid="stSidebar"] .stMultiSelect div[data-baseweb="select"] * {
        color: #ffffff !important;
    }
    
    /* 라디오 버튼 */
    [data-testid="stSidebar"] .stRadio label {
        color: #ffffff !important;
    }
    
    /* 체크박스 */
    [data-testid="stSidebar"] .stCheckbox label {
        color: #ffffff !important;
    }
</style>
""", unsafe_allow_html=True)


# ===== 캐싱 함수 =====
@st.cache_data(ttl=600)
def cached_market_cap(market, count):
    return get_top_by_market_cap(market, count)

@st.cache_data(ttl=600)
def cached_top_change(market, count):
    return get_top_by_change(market, count)

# ===== 사이드바 =====
st.sidebar.markdown("## ⚙️ 설정")

# 1) 시장 선택
market = st.sidebar.radio("🌏 시장 선택", ["국내", "국외"])

# 2) 종목 선택 방식
select_mode = st.sidebar.selectbox(
    "📋 종목 선택 방식",
    ["직접 선택", "시가총액 상위", "최근 상승률 상위"]
)

# 3) 종목 결정
if select_mode == "직접 선택":
    stock_list = get_stock_list(market)
    options = [f"{name} ({ticker})" for ticker, name in stock_list]
    selected = st.sidebar.selectbox("종목 선택", options)
    ticker = selected.split("(")[1].replace(")", "")

elif select_mode == "시가총액 상위":
    count = st.sidebar.selectbox("상위 몇 개?", [10, 20, 30])
    with st.sidebar:
        with st.spinner(f"⏳ 시가총액 상위 {count}개 조회 중..."):
            top_stocks = cached_market_cap(market, count)
    if top_stocks:
        options = []
        for t, name, cap in top_stocks:
            if cap >= 1_000_000_000_000:
                cap_str = f"{cap/1_000_000_000_000:.1f}조"
            elif cap >= 100_000_000:
                cap_str = f"{cap/100_000_000:.0f}억"
            else:
                cap_str = f"{cap:,.0f}"
            options.append(f"{name} ({t}) - {cap_str}")
        selected = st.sidebar.selectbox("종목 선택", options)
        ticker = selected.split("(")[1].split(")")[0]
    else:
        st.sidebar.error("조회 실패!")
        ticker = "AAPL"

else:
    count = st.sidebar.selectbox("상위 몇 개?", [10, 20, 30])
    with st.sidebar:
        with st.spinner(f"⏳ 상승률 상위 {count}개 조회 중..."):
            top_stocks = cached_top_change(market, count)
    if top_stocks and len(top_stocks) > 0:
        options = []
        for item in top_stocks:
            if len(item) == 3:
                t, name, change = item
                options.append(f"{name} ({t}) - {change:+.2f}%")
            else:
                t, name = item
                options.append(f"{name} ({t})")
        selected = st.sidebar.selectbox("종목 선택", options)
        ticker = selected.split("(")[1].split(")")[0]
    else:
        st.sidebar.error("조회 실패!")
        ticker = "AAPL"

# 4) 기간
period = st.sidebar.selectbox("📅 기간 선택", ["1달", "3달", "6달", "1년"])

# 5) 종목 비교
st.sidebar.markdown("---")
st.sidebar.markdown("## 📊 종목 비교")
stock_list = get_stock_list(market)
all_tickers = [f"{name} ({t})" for t, name in stock_list]
compare_selected = st.sidebar.multiselect("비교할 종목 선택", all_tickers, default=[])
compare_tickers = [s.split("(")[1].replace(")", "") for s in compare_selected]

# 6) 새로고침
st.sidebar.markdown("---")
auto_refresh = st.sidebar.checkbox("🔄 자동 새로고침 (30초)")
if auto_refresh:
    time.sleep(30)
    st.rerun()
if st.sidebar.button("🔄 새로고침"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption(f"🕐 {datetime.now().strftime('%H:%M:%S')} 업데이트")

# ===== 메인 영역 =====
info = get_stock_info(ticker)

# 헤더
st.markdown("""
<div class="main-header">
    <h1>📊 Stock Monitor Pro</h1>
    <p>실시간 주식 모니터링 & AI 기술적 분석</p>
</div>
""", unsafe_allow_html=True)

# 메트릭 카드
if info:
    change = info["current_price"] - info['prev_close']
    change_pct = (change / info['prev_close']) * 100
    direction = "up" if change >= 0 else "down"
    arrow = "▲" if change >= 0 else "▼"
    
    if info['currency'] == 'KRW':
        price_str = f"₩{info['current_price']:,.0f}"
        change_str = f"{arrow} {abs(change):,.0f}"
    else:
        price_str = f"${info['current_price']:,.2f}"
        change_str = f"{arrow} {abs(change):,.2f}"

    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">현재가</div>
            <div class="metric-value price">{price_str}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">전일대비</div>
            <div class="metric-value {direction}">{change_pct:+.2f}%</div>
            <div class="metric-delta {direction}">{change_str}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">종목명</div>
            <div class="metric-value name">{info['name']}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ===== 탭 =====
tab1, tab2, tab3, tab4 = st.tabs(["📈 가격 차트", "📊 종목 비교", "📋 요약 정보", "🤖 AI 분석"])

with tab1:
    fig = make_combined_chart(ticker, period)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    if compare_tickers:
        compare_list = [ticker] + compare_tickers
        fig2 = make_comparison_chart(compare_list, period)
        if fig2:
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("👈 사이드바에서 비교할 종목을 선택하세요!")

with tab3:
    if info:
        if info['currency'] == 'KRW':
            price_display = f"₩{info['current_price']:,.0f}"
            prev_display = f"₩{info['prev_close']:,.0f}"
        else:
            price_display = f"${info['current_price']:,.2f}"
            prev_display = f"${info['prev_close']:,.2f}"
        
        st.markdown(f"""
        <div class="info-card">
            <div class="info-row">
                <span class="info-label">종목명</span>
                <span class="info-value">{info['name']}</span>
            </div>
            <div class="info-row">
                <span class="info-label">현재가</span>
                <span class="info-value">{price_display}</span>
            </div>
            <div class="info-row">
                <span class="info-label">전일종가</span>
                <span class="info-value">{prev_display}</span>
            </div>
            <div class="info-row">
                <span class="info-label">등락률</span>
                <span class="info-value" style="color: {'#00d26a' if change >= 0 else '#f92f60'}">
                    {change_pct:+.2f}%
                </span>
            </div>
            <div class="info-row" style="border-bottom: none;">
                <span class="info-label">통화</span>
                <span class="info-value">{info['currency']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

with tab4:
    fig3 = make_analysis_chart(ticker, period)
    if fig3:
        st.plotly_chart(fig3, use_container_width=True)

    df = get_stock_history(ticker, period)

    if df is not None:
        signals = generate_signals(df)

        # 종합 판단
        if "매수" in signals['total']:
            signal_class = "signal-buy"
        elif "매도" in signals['total']:
            signal_class = "signal-sell"
        else:
            signal_class = "signal-hold"

        st.markdown(f"""
        <div class="signal-total {signal_class}">
            {signals['total']}
        </div>
        """, unsafe_allow_html=True)

        # 지표 카드
        col1, col2, col3 = st.columns(3)

        indicators = [
            ("RSI", signals['rsi_value'], signals['rsi_signal']),
            ("MACD", signals['macd_value'], signals['macd_signal']),
            ("볼린저 밴드", f"{signals['bb_lower']} ~ {signals['bb_upper']}", signals['bb_signal']),
        ]

        for col, (ind_name, ind_value, ind_signal) in zip([col1, col2, col3], indicators):
            if ind_signal in ["매수"]:
                badge_class = "badge-buy"
            elif ind_signal in ["매도"]:
                badge_class = "badge-sell"
            else:
                badge_class = "badge-neutral"

            with col:
                st.markdown(f"""
                <div class="indicator-card">
                    <div class="indicator-name">{ind_name}</div>
                    <div class="indicator-value">{ind_value}</div>
                    <span class="indicator-signal {badge_class}">{ind_signal}</span>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("""
        <div class="disclaimer">
            ⚠️ 본 분석은 기술적 지표 기반이며, 투자 결정의 참고 자료로만 활용하세요.
            실제 투자 손실에 대한 책임은 투자자 본인에게 있습니다.
        </div>
        """, unsafe_allow_html=True)
