import os
import yfinance as yf
import pandas as pd
from datetime import datetime

# 1. 환경 설정 및 데이터 로드 (최근 3달 치 데이터면 지표 계산에 충분)
TICKER = "SOXL"
POSITION_FILE = "soxl_position.txt"

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%Y')}] SOXL 스나이퍼 봇 가동 시작")
df = yf.download(TICKER, period="3mo", interval="1d")

# 2. 기술적 지표 계산
# 볼린저 밴드 (20, 2)
df['Mid'] = df['Close'].rolling(window=20).mean()
df['Std'] = df['Close'].rolling(window=20).std()
df['BB_Lower'] = df['Mid'] - (2 * df['Std'])
df['BB_Upper'] = df['Mid'] + (2 * df['Std'])

# RSI (7)
delta = df['Close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=7).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=7).mean()
df['RSI_7'] = 100 - (100 / (1 + (gain / loss)))

# 어제 자 확정 데이터 추출
latest = df.iloc[-1]
current_price = float(latest['Close'])
bb_lower = float(latest['BB_Lower'])
bb_upper = float(latest['BB_Upper'])
rsi_7 = float(latest['RSI_7'])

print(f"📊 전일 종가 기준 지표 판별 -> 종가: ${current_price:.2f} | 볼밴하한: ${bb_lower:.2f} | 볼밴상한: ${bb_upper:.2f} | RSI(7): {rsi_7:.2f}")

# 3. 포지션 상태 읽기 (파일이 없으면 CASH 상태로 간주)
if not os.path.exists(POSITION_FILE):
    with open(POSITION_FILE, "w") as f:
        f.write("CASH,,0.0")

with open(POSITION_FILE, "r") as f:
    status, buy_date_str, buy_price_str = f.read().strip().split(",")
    buy_price = float(buy_price_str)

# 4. 매매 알고리즘 및 주문 트리거 파트
if status == "CASH":
    # 🌟 매수 조건: 종가가 볼밴 하한선 아래 뚫고 + RSI(7)이 25 이하일 때
    if current_price < bb_lower and rsi_7 <= 25:
        print("🚨 [매수 신호 발생] 볼밴 하한선 이탈 및 RSI 과매도 동시 충족!")
        
        # TODO: 여기에 키움증권 API 연동 코드 삽입 (오늘 밤 체결될 LOC 예약 매수)
        # 예시: kiwoom.send_order_loc_reservation(TICKER, "BUY", 수량)
        
        today_str = datetime.now().strftime("%Y-%m-%d")
        with open(POSITION_FILE, "w") as f:
            f.write(f"HOLDING,{today_str},{current_price}")
        print(f"➔ 오늘 밤 [LOC 예약 매수] 주문 전송 완료 및 상태 저장 (${current_price})")
    else:
        print("➔ 매수 조건 미충족. 예수금을 안전하게 유지합니다.")

elif status == "HOLDING":
    buy_date = datetime.strptime(buy_date_str, "%Y-%m-%d")
    # 매수일 이후 오늘까지 쌓인 영업일 수 계산
    trading_days_held = len(df[df.index >= buy_date]) - 1
    profit_rate = ((current_price - buy_price) / buy_price) * 100
    
    print(f"📈 보유 중 정보 -> 매수일: {buy_date_str} | 보유 영업일: {trading_days_held}일 | 현재 수익률: {profit_rate:.2f}%")

    # 🌟 매도 조건 판별
    if profit_rate >= 7.0:
        print("🎉 [익절] 목표 수익률 +7% 도달! 오늘 장중 지정가 매도 예약")
        # kiwoom.send_order_limit_reservation(TICKER, "SELL", 수량, buy_price * 1.07)
        with open(POSITION_FILE, "w") as f:
            f.write("CASH,,0.0")
            
    elif current_price >= bb_upper:
        print("🚀 [익절] 전일 종가가 볼밴 상한선 터치! 오늘 밤 LOC 예약 매도 돌격")
        # kiwoom.send_order_loc_reservation(TICKER, "SELL", 수량)
        with open(POSITION_FILE, "w") as f:
            f.write("CASH,,0.0")
            
    elif trading_days_held >= 3:
        print("💣 [타임캡 만료] 3영업일 경과. 무조건 기계적 패닉셀! 오늘 밤 LOC 예약 매도")
        # kiwoom.send_order_loc_reservation(TICKER, "SELL", 수량)
        with open(POSITION_FILE, "w") as f:
            f.write("CASH,,0.0")
            
    else:
        print("➔ 매도 조건 미충족. 포지션을 유지합니다.")
