import os
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime

# ====================================================
# ⚙️ 깃허브 시크릿 금고에서 텔레그램 열쇠를 읽어옵니다.
# ====================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")  
CHAT_ID = os.environ.get("CHAT_ID")           
TICKER = "SOXL"
POSITION_FILE = "soxl_position.txt"

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("텔레그램 설정이 누락되었습니다.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"메시지 전송 실패: {e}")

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] SOXL 스나이퍼 봇 가동")
df = yf.download(TICKER, period="3mo", interval="1d")

# 휴일 공백 제거
df = df[df['Close'].notna()]

# 지표 계산: 볼린저 밴드 (20, 2) 및 RSI (7)
df['Mid'] = df['Close'].rolling(window=20).mean()
df['Std'] = df['Close'].rolling(window=20).std()
df['BB_Lower'] = df['Mid'] - (2 * df['Std'])
df['BB_Upper'] = df['Mid'] + (2 * df['Std'])

delta = df['Close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=7).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=7).mean()
df['RSI_7'] = 100 - (100 / (1 + (gain / loss)))

# 전일 확정 데이터
latest = df.iloc[-1]
current_price = float(latest['Close'])
bb_lower = float(latest['BB_Lower'])
bb_upper = float(latest['BB_Upper'])
rsi_7 = float(latest['RSI_7'])

# 포지션 상태 불러오기
if not os.path.exists(POSITION_FILE):
    with open(POSITION_FILE, "w") as f:
        f.write("CASH,,0.0")

with open(POSITION_FILE, "r") as f:
    status, buy_date_str, buy_price_str = f.read().strip().split(",")
    buy_price = float(buy_price_str)

# ─── 매매 알고리즘 및 텔레그램 지령 발송 ───
msg_lines = [
    "🤖 **[SOXL 스나이퍼 v1]** 단타 브리핑",
    f"📊 SOXL 전일종가: `${current_price:.2f}`",
    f"📉 볼밴하한: `${bb_lower:.2f}` | 상한: `${bb_upper:.2f}`",
    f"⚡ RSI(7): `{rsi_7:.1f}`",
    "─" * 15
]

if status == "CASH":
    # 🌟 매수 타점 포착
    if current_price < bb_lower and rsi_7 <= 25:
        msg_lines.append("🚨 **[매수 타점 확증]** 볼밴 하한선 이탈 및 RSI 과매도 동시 충족!")
        msg_lines.append("🛒 **[오늘 밤 주문]** 키움 앱을 켜고 부계좌로 **【 SOXL LOC 예약 매수 】**를 걸어두세요! (예산의 50%)")
        
        today_str = datetime.now().strftime("%Y-%m-%d")
        with open(POSITION_FILE, "w") as f:
            f.write(f"HOLDING,{today_str},{current_price}")
        send_telegram_message("\n".join(msg_lines))
    else:
        print("매수 조건 미충족 - 관망 (알림 미발송으로 소음 차단)")

elif status == "HOLDING":
    buy_date = datetime.strptime(buy_date_str, "%Y-%m-%d")
    trading_days_held = len(df[df.index >= buy_date]) - 1
    profit_rate = ((current_price - buy_price) / buy_price) * 100
    
    msg_lines.append(f"📈 현재 보유 중 | 평단: `${buy_price:.2f}` ({profit_rate:.1f}%)")
    msg_lines.append(f"⏱️ 보유 기간: `{trading_days_held}영업일`")
    msg_lines.append("─" * 15)

    # 🌟 매도 타점 포착
    if profit_rate >= 7.0:
        msg_lines.append("🎉 **[목표가 도달 익절]** 평단 대비 +7%를 돌파했습니다.")
        msg_lines.append("💰 **[오늘 밤 주문]** 키움 앱에서 SOXL **【 전량 지정가 매도 예약 】** 하세요!")
        with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
        send_telegram_message("\n".join(msg_lines))
        
    elif current_price >= bb_upper:
        msg_lines.append("🚀 **[볼밴 상한 익절]** 종가가 볼린저 밴드 상한선을 뚫었습니다.")
        msg_lines.append("💰 **[오늘 밤 주문]** 키움 앱에서 SOXL **【 전량 LOC 예약 매도 】** 하세요!")
        with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
        send_telegram_message("\n".join(msg_lines))
        
    elif trading_days_held >= 3:
        msg_lines.append("💣 **[3일 타임캡 만료]** 약속된 3영업일이 지났습니다. 무조건 탈출!")
        msg_lines.append("🚨 **[오늘 밤 주문]** 손익 상관없이 SOXL **【 전량 LOC 예약 매도 】** 던지세요!")
        with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
        send_telegram_message("\n".join(msg_lines))
    else:
        print("보유 중이나 매도 조건 아님 - 관망 (알림 미발송)")
