import plotly.graph_objects as go
from plotly.subplots import make_subplots
from data_collector import (
    get_stock_history, calculate_moving_average,
    get_stock_info, KOREA_STOCKS, US_STOCKS
)
from stock_analyzer import calculate_rsi, calculate_macd, calculate_bollinger

# ===== 다크 테마 색상 =====
COLORS = {
    'bg': '#0f0f1a',
    'paper': '#1a1a2e',
    'grid': '#2a2a4a',
    'text': '#8892b0',
    'white': '#e0e0e0',
    'blue': '#2563eb',
    'cyan': '#64ffda',
    'green': '#00d26a',
    'red': '#f92f60',
    'orange': '#ff9f43',
    'purple': '#a855f7',
    'yellow': '#ffd700',
}

DARK_LAYOUT = dict(
    plot_bgcolor=COLORS['bg'],
    paper_bgcolor=COLORS['paper'],
    font=dict(color=COLORS['text'], size=12),
    xaxis=dict(
        gridcolor=COLORS['grid'],
        linecolor=COLORS['grid'],
        zerolinecolor=COLORS['grid']
    ),
    yaxis=dict(
        gridcolor=COLORS['grid'],
        linecolor=COLORS['grid'],
        zerolinecolor=COLORS['grid']
    ),
    legend=dict(
        bgcolor='rgba(26,26,46,0.8)',
        bordercolor=COLORS['grid'],
        borderwidth=1,
        font=dict(color=COLORS['white'])
    ),
    margin=dict(l=60, r=20, t=60, b=40),
)


def get_stock_name(ticker):
    """티커 → 종목이름 변환"""
    all_stocks = KOREA_STOCKS + US_STOCKS
    for t, name in all_stocks:
        if t == ticker:
            return name
    return ticker


def make_combined_chart(ticker_symbol, period="1달"):

    df = get_stock_history(ticker_symbol, period)
    if df is None:
        return None

    df = calculate_moving_average(df, [5, 20])
    name = get_stock_name(ticker_symbol)

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.05
    )

    # 종가
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Close"],
        name="종가",
        line=dict(color=COLORS['cyan'], width=2.5),
        fill='tozeroy',
        fillcolor='rgba(100,255,218,0.05)'
    ), row=1, col=1)

    # 이동평균
    fig.add_trace(go.Scatter(
        x=df.index, y=df["MA5"],
        name="MA5",
        line=dict(color=COLORS['orange'], width=1.5, dash="dot")
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df.index, y=df["MA20"],
        name="MA20",
        line=dict(color=COLORS['purple'], width=1.5, dash="dash")
    ), row=1, col=1)

    # 거래량 (색상으로 상승/하락 구분)
    colors_vol = []
    for i in range(len(df)):
        if i == 0:
            colors_vol.append(COLORS['blue'])
        elif df["Close"].iloc[i] >= df["Close"].iloc[i-1]:
            colors_vol.append('rgba(0,210,106,0.6)')
        else:
            colors_vol.append('rgba(249,47,96,0.6)')

    fig.add_trace(go.Bar(
        x=df.index, y=df["Volume"],
        name="거래량",
        marker_color=colors_vol
    ), row=2, col=1)

    fig.update_layout(
        title=dict(
            text=f"📈 {name} 주가 + 거래량 ({period})",
            font=dict(size=18, color=COLORS['white'])
        ),
        height=550,
        showlegend=True,
        **DARK_LAYOUT
    )

    # 서브플롯 축 스타일
    for i in [1, 2]:
        fig.update_xaxes(gridcolor=COLORS['grid'], linecolor=COLORS['grid'], row=i, col=1)
        fig.update_yaxes(gridcolor=COLORS['grid'], linecolor=COLORS['grid'], row=i, col=1)

    fig.update_yaxes(title_text="가격", title_font=dict(color=COLORS['text']), row=1, col=1)
    fig.update_yaxes(title_text="거래량", title_font=dict(color=COLORS['text']), row=2, col=1)

    return fig


def make_comparison_chart(ticker_symbols, period="3달"):

    fig = go.Figure()
    chart_colors = [COLORS['cyan'], COLORS['orange'], COLORS['purple'],
                    COLORS['green'], COLORS['red'], COLORS['yellow']]

    for i, symbol in enumerate(ticker_symbols):
        df = get_stock_history(symbol, period)
        if df is None:
            continue

        first_price = df["Close"].iloc[0]
        returns = (df["Close"] / first_price - 1) * 100
        name = get_stock_name(symbol)
        color = chart_colors[i % len(chart_colors)]

        fig.add_trace(go.Scatter(
            x=df.index, y=returns,
            name=name,
            line=dict(width=2.5, color=color)
        ))

    fig.add_hline(y=0, line_dash="dash", line_color=COLORS['grid'], line_width=1)

    fig.update_layout(
        title=dict(
            text=f"📊 종목 비교 - 수익률 ({period})",
            font=dict(size=18, color=COLORS['white'])
        ),
        xaxis_title="날짜",
        yaxis_title="수익률 (%)",
        height=500,
        **DARK_LAYOUT
    )

    return fig


def make_analysis_chart(ticker, period):
    """AI 분석 차트: 볼린저 밴드 + RSI + MACD"""

    df = get_stock_history(ticker, period)
    if df is None:
        return None

    name = get_stock_name(ticker)

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.5, 0.25, 0.25],
        vertical_spacing=0.06,
        subplot_titles=(
            f"볼린저 밴드",
            "RSI (상대강도지수)",
            "MACD (이동평균 수렴·확산)"
        )
    )

    # ===== 1행: 볼린저 밴드 =====
    upper, middle, lower = calculate_bollinger(df)

    fig.add_trace(go.Scatter(
        x=df.index, y=upper,
        name="상단 밴드",
        line=dict(color='rgba(249,47,96,0.4)', width=1, dash="dash")
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df.index, y=lower,
        name="하단 밴드",
        line=dict(color='rgba(0,210,106,0.4)', width=1, dash="dash"),
        fill="tonexty",
        fillcolor="rgba(37,99,235,0.08)"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df.index, y=middle,
        name="중간 밴드",
        line=dict(color=COLORS['blue'], width=1, dash="dot")
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df.index, y=df['Close'],
        name="종가",
        line=dict(color=COLORS['cyan'], width=2.5)
    ), row=1, col=1)

    # ===== 2행: RSI =====
    rsi = calculate_rsi(df)

    fig.add_trace(go.Scatter(
        x=df.index, y=rsi,
        name="RSI",
        line=dict(color=COLORS['purple'], width=2)
    ), row=2, col=1)

    # 과매수/과매도 영역
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(249,47,96,0.1)",
                  line_width=0, row=2, col=1)
    fig.add_hrect(y0=0, y1=30, fillcolor="rgba(0,210,106,0.1)",
                  line_width=0, row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color=COLORS['red'],
                  line_width=1, row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color=COLORS['green'],
                  line_width=1, row=2, col=1)

    # ===== 3행: MACD =====
    macd_line, signal_line, histogram = calculate_macd(df)

    colors_hist = [COLORS['green'] if v >= 0 else COLORS['red'] for v in histogram]
    fig.add_trace(go.Bar(
        x=df.index, y=histogram,
        name="히스토그램",
        marker_color=colors_hist,
        opacity=0.6
    ), row=3, col=1)

    fig.add_trace(go.Scatter(
        x=df.index, y=macd_line,
        name="MACD",
        line=dict(color=COLORS['cyan'], width=1.5)
    ), row=3, col=1)

    fig.add_trace(go.Scatter(
        x=df.index, y=signal_line,
        name="Signal",
        line=dict(color=COLORS['orange'], width=1.5)
    ), row=3, col=1)

    fig.update_layout(
        title=dict(
            text=f"🤖 {name} 기술적 분석 ({period})",
            font=dict(size=18, color=COLORS['white'])
        ),
        height=700,
        showlegend=True,
        **DARK_LAYOUT
    )

    # 서브플롯 스타일
    for i in [1, 2, 3]:
        fig.update_xaxes(gridcolor=COLORS['grid'], linecolor=COLORS['grid'], row=i, col=1)
        fig.update_yaxes(gridcolor=COLORS['grid'], linecolor=COLORS['grid'], row=i, col=1)

    # 서브플롯 제목 색상
    for annotation in fig['layout']['annotations']:
        annotation['font'] = dict(color=COLORS['white'], size=14)

    fig.update_yaxes(title_text="가격", row=1, col=1)
    fig.update_yaxes(title_text="RSI", row=2, col=1)
    fig.update_yaxes(title_text="MACD", row=3, col=1)

    return fig
