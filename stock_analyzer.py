# stock_analyzer.py
# Phase 7: 기술적 분석 + 매수/매도 신호

import pandas as pd

def calculate_rsi(df, period=14):
    """RSI (상대강도지수) 계산
    
    - 70 이상: 과매수 (너무 올랐다 → 매도 신호)
    - 30 이하: 과매도 (너무 떨어졌다 → 매수 신호)
    """
    delta = df['Close'].diff()
    
    gain = delta.copy()
    loss = delta.copy()
    
    gain[gain < 0] = 0       # 오른 날만
    loss[loss > 0] = 0       # 떨어진 날만
    loss = abs(loss)          # 양수로 변환
    
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_macd(df):
    """MACD (이동평균 수렴·확산) 계산
    
    - MACD가 Signal 위로 올라감 → 매수 신호
    - MACD가 Signal 아래로 내려감 → 매도 신호
    """
    ema12 = df['Close'].ewm(span=12).mean()
    ema26 = df['Close'].ewm(span=26).mean()
    
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def calculate_bollinger(df, period=20):
    """볼린저 밴드 계산
    
    - 상단 밴드 돌파 → 과매수 (매도 신호)
    - 하단 밴드 돌파 → 과매도 (매수 신호)
    """
    middle = df['Close'].rolling(window=period).mean()
    std = df['Close'].rolling(window=period).std()
    
    upper = middle + (std * 2)
    lower = middle - (std * 2)
    
    return upper, middle, lower


def generate_signals(df):
    """모든 지표를 종합해서 매수/매도 신호 생성"""
    
    signals = {}
    
    # 1. RSI 신호
    rsi = calculate_rsi(df)
    current_rsi = rsi.iloc[-1]
    signals['rsi_value'] = round(current_rsi, 1)
    
    if current_rsi >= 70:
        signals['rsi_signal'] = "매도"
    elif current_rsi <= 30:
        signals['rsi_signal'] = "매수"
    else:
        signals['rsi_signal'] = "중립"
    
    # 2. MACD 신호
    macd_line, signal_line, histogram = calculate_macd(df)
    current_hist = histogram.iloc[-1]
    prev_hist = histogram.iloc[-2]
    
    signals['macd_value'] = round(current_hist, 2)
    
    if current_hist > 0 and prev_hist <= 0:
        signals['macd_signal'] = "매수"
    elif current_hist < 0 and prev_hist >= 0:
        signals['macd_signal'] = "매도"
    elif current_hist > 0:
        signals['macd_signal'] = "상승 중"
    else:
        signals['macd_signal'] = "하락 중"
    
    # 3. 볼린저 밴드 신호
    upper, middle, lower = calculate_bollinger(df)
    current_price = df['Close'].iloc[-1]
    
    signals['bb_upper'] = round(upper.iloc[-1], 2)
    signals['bb_lower'] = round(lower.iloc[-1], 2)
    
    if current_price >= upper.iloc[-1]:
        signals['bb_signal'] = "매도"
    elif current_price <= lower.iloc[-1]:
        signals['bb_signal'] = "매수"
    else:
        signals['bb_signal'] = "중립"
    
    # 4. 종합 판단
    buy_count = 0
    sell_count = 0
    
    for key in ['rsi_signal', 'macd_signal', 'bb_signal']:
        if signals[key] == "매수":
            buy_count += 1
        elif signals[key] == "매도":
            sell_count += 1
    
    if buy_count >= 2:
        signals['total'] = "🟢 매수 추천"
    elif sell_count >= 2:
        signals['total'] = "🔴 매도 추천"
    else:
        signals['total'] = "🟡 관망 추천"
    
    return signals
