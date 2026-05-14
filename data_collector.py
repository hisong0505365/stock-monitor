import yfinance as yf          
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ===== 종목 리스트 =====

KOREA_STOCKS = [
    ("005930.KS", "삼성전자"),
    ("000660.KS", "SK하이닉스"),
    ("373220.KS", "LG에너지솔루션"),
    ("207940.KS", "삼성바이오로직스"),
    ("006400.KS", "삼성SDI"),
    ("051910.KS", "LG화학"),
    ("005380.KS", "현대자동차"),
    ("000270.KS", "기아"),
    ("068270.KS", "셀트리온"),
    ("035420.KS", "NAVER"),
    ("035720.KS", "카카오"),
    ("105560.KS", "KB금융"),
    ("055550.KS", "신한지주"),
    ("012330.KS", "현대모비스"),
    ("066570.KS", "LG전자"),
    ("003550.KS", "LG"),
    ("032830.KS", "삼성생명"),
    ("015760.KS", "한국전력"),
    ("034730.KS", "SK"),
    ("028260.KS", "삼성물산"),
    ("009150.KS", "삼성전기"),
    ("086790.KS", "하나금융지주"),
    ("018260.KS", "삼성SDS"),
    ("033780.KS", "KT&G"),
    ("017670.KS", "SK텔레콤"),
    ("030200.KS", "KT"),
    ("316140.KS", "우리금융지주"),
    ("003490.KS", "대한항공"),
    ("010130.KS", "고려아연"),
    ("011200.KS", "HMM"),
]

US_STOCKS = [
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("NVDA", "NVIDIA"),
    ("GOOGL", "Alphabet"),
    ("AMZN", "Amazon"),
    ("META", "Meta"),
    ("TSLA", "Tesla"),
    ("BRK-B", "Berkshire"),
    ("JPM", "JPMorgan"),
    ("V", "Visa"),
    ("JNJ", "J&J"),
    ("WMT", "Walmart"),
    ("UNH", "UnitedHealth"),
    ("MA", "Mastercard"),
    ("PG", "P&G"),
    ("XOM", "ExxonMobil"),
    ("HD", "Home Depot"),
    ("CVX", "Chevron"),
    ("LLY", "Eli Lilly"),
    ("MRK", "Merck"),
    ("ABBV", "AbbVie"),
    ("PEP", "PepsiCo"),
    ("KO", "Coca-Cola"),
    ("COST", "Costco"),
    ("AVGO", "Broadcom"),
    ("MCD", "McDonald's"),
    ("CRM", "Salesforce"),
    ("AMD", "AMD"),
    ("NFLX", "Netflix"),
    ("INTC", "Intel"),
]

def get_stock_list(market):
    """국내/국외 종목 리스트 반환"""
    if market == "국내":
        return KOREA_STOCKS
    else:
        return US_STOCKS


def get_stock_info(ticker_symbol):
    """
    Args:
        ticker_symbol (str):
    Returns:
        dict 종복 정보 딕셔너리 또는 오류 시 None
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info

        result = {
            'name':           info.get('shortName', ticker_symbol),
            'current_price':  info.get('currentPrice', 0),
            'prev_close':     info.get('previousClose', 0),
            'currency':       info.get('currency', 'USD'),
        }

        if result['current_price'] == 0:
            print(f"[경고] {ticker_symbol}: 가격 데이터를 찾을 수 없습니다.")
            return None
    
        return result

    except Exception as e:
        print(f"[오류] {ticker_symbol}: {e}")
        return None
    
def get_top_by_market_cap(market, count):
    """시가총액 상위 종목 반환 (실시간 / 멀티 조회)"""
    stocks = get_stock_list(market)
    tickers = [s[0] for s in stocks]
    names = {s[0]: s[1] for s in stocks}
    
    results = []
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            market_cap = stock.info.get('marketCap', 0)
            
            if market_cap > 0:
                results.append((ticker, names[ticker], market_cap))
        except:
            continue
    
    # 시가총액 기준 내림차순 정렬
    results.sort(key=lambda x: x[2], reverse=True)
    
    return results[:count]

def get_top_by_change(market, count):
    """최근 상승률 상위 종목 반환"""
    stocks = get_stock_list(market)
    tickers = [s[0] for s in stocks]
    names = {s[0]: s[1] for s in stocks}

    try:
        data = yf.download(tickers, period="5d", progress=False)

        results = []
        for ticker in tickers:
            try:
                close = data['Close'][ticker].dropna()
                current = close.iloc[-1]
                prev = close.iloc[-2]
                change_pct = ((current - prev) / prev) * 100
                results.append((ticker, names[ticker], round(change_pct, 2)))
            except:
                continue

        results.sort(key=lambda x: x[2], reverse=True)
        return results[:count]

    except:
        return stocks[:count]
    
# if __name__ == '__main__':

#     # 테스트 1: 정상 종목
#     print("=" * 50)
#     print("테스트 1: AAPL (애플)")
#     print("=" * 50)
#     result = get_stock_info("AAPL")
#     print(result)

#     # 테스트 2: 한국 종목
#     print("\n" + "=" * 50)
#     print("테스트 2: 005930.KS (삼성전자)")
#     print("=" * 50)
#     result2 = get_stock_info("005930.KS")
#     print(result2)

#     # 테스트 3: 잘못된 종목
#     print("\n" + "=" * 50)
#     print("테스트 3: INVALID (존재하지 않는 종목)")
#     print("=" * 50)
#     result3 = get_stock_info("INVALID")
#     print(result3)

def get_stock_history(ticker_symbol, period="1달"):
    
    period_map = {
        "1주": "1wk",
        "1달": "1mo",
        "3달": "3mo",
        "6달": "6mo",
        "1년": "1y"
    }

    yf_period = period_map.get(period, "1mo")

    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period=yf_period)

        if df.empty:
            print(f"[경고] {ticker.symbol}: 히스토리 데이터가 없습니다.")
            return None

        return df

    except Exception as e:
        print(f"[오류] {ticker_symbol} 히스토리 조회 실패: {e}")
        return None
        

#     # ====== 함수 2 테스트 ======
# print("\n" + "=" * 50)
# print("함수 2 테스트: AAPL 기간별 히스토리")
# print("=" * 50)
    
# for p in ['1주', '1달', '3달', '1년']:
#     df = get_stock_history("AAPL", p)
#     if df is not None:
#         print(f"  기간={p} → {len(df)}행")

def calculate_change(current_price, prev_close):

    if prev_close == 0:
        return 0, 0
    
    change = current_price - prev_close
    change_pct = change / prev_close * 100

    return round(change, 2), round(change_pct, 2)

#     # ====== 함수 3 테스트 ======
# print("\n" + "=" * 50)
# print("함수 3 테스트: 등락가/등락률 계산")
# print("=" * 50)
    
#     # 아까 함수 1에서 받은 실제 데이터로 테스트!
# info = get_stock_info("AAPL")
# if info:
#     change, pct = calculate_change(info['current_price'], info['prev_close'])
#     print(f"  {info['name']}")
#     print(f"  현재가: {info['current_price']}")
#     print(f"  전일종가: {info['prev_close']}")
#     print(f"  등락가: {change}")
#     print(f"  등락률: {pct}%")


def calculate_moving_average(df, periods=[5, 20]):
    result = df.copy()

    for period in periods:
        col_name = f"MA{period}"
        result[col_name] = (result["Close"].rolling(window=period).mean())

    return result

    # ====== 함수 4 테스트 ======
# print("\n" + "=" * 50)
# print("함수 4 테스트: 이동평균 계산")
# print("=" * 50)

# df = get_stock_history("AAPL", "1달")
# if df is not None:
#     df_ma = calculate_moving_average(df, [5, 20])
#     print(f"  컬럼 목록: {df_ma.columns.tolist()}")
#     print(f"\n  최근 5일 데이터:")
#     print(df_ma[['Close', 'MA5', 'MA20']].tail())