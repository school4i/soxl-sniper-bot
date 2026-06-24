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

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] SOXL 스나이퍼 봇 정기 브리핑 시작")
df = yf.download(TICKER, period="3mo", interval="1d")

if df.empty:
    send_telegram_message("❌ [SOXL 봇] 야후 파이낸스 데이터 수집 실패로 인해 오늘 봇 작동이 중단되었습니다.")
    exit(1)

# yfinance 최신 버전의 MultiIndex 열 구조 강제 평탄화 방어
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

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

# ──────────────────────────────────────────────────
# 📊 1. 매일 전송할 기초 지표 브리핑 레이아웃 생성
# ──────────────────────────────────────────────────
msg_lines = [
    "🤖 **[SOXL 스나이퍼 v1]** 일일 매매 가이드",
    f"📅 분석 일시: `{datetime.now().strftime('%Y-%m-%d %H:%M')}`",
    f"📊 SOXL 전일 종가: `${current_price:.2f}`",
    f"📉 볼밴 하한선: `${bb_lower:.2f}` | 상한선: `${bb_upper:.2f}`",
    f"⚡ 단타 RSI(7) 지표: `{rsi_7:.1f}` (매수 기준: 25 이하)",
    "─" * 15,
    "🔍 **[현재 시장 지표 정밀 진단]**"
]

# 볼린저 밴드 위치 진단 코멘트
if current_price < bb_lower:
    msg_lines.append("🚨 **위험 고조**: 현재 주가가 볼밴 하한선 아래로 이탈했습니다! (과매도 국면)")
else:
    msg_lines.append("✨ **안정 상태**: 주가가 볼린저 밴드 내부에서 정상 궤도를 유지 중입니다.")

# RSI 지표 진단 코멘트
if rsi_7 <= 25:
    msg_lines.append(f"🔥 **심리 붕괴**: RSI(7)이 `{rsi_7:.1f}`로 극단적 공포(25 이하) 상태입니다.")
else:
    msg_lines.append(f"💤 **심리 완화**: RSI(7)이 `{rsi_7:.1f}`로 아직은 진바닥 신호가 아닙니다.")

msg_lines.append("─" * 15)
msg_lines.append("📢 **[오늘 밤 최종 매매 지령]**")

# ──────────────────────────────────────────────────
# ⚔️ 2. 포지션별 알고리즘 판단 로직 및 지령 확정
# ──────────────────────────────────────────────────
if status == "CASH":
    # 🌟 매수 조건 충족 여부 검사
    if current_price < bb_lower and rsi_7 <= 25:
        msg_lines.append("🛒 **【 SOXL 1차 LOC 예약 매수 】** 🚨")
        msg_lines.append("➔ **[신호 확증]** 이중 그물망(볼밴하한+RSI 25)이 모두 켜졌습니다. 오늘 밤 키움 부계좌를 열고 **준비한 예산의 50%를 LOC 매수 예약** 하세요!")
        
        today_str = datetime.now().strftime("%Y-%m-%d")
        with open(POSITION_FILE, "w") as f:
            f.write(f"HOLDING,{today_str},{current_price}")
    else:
        msg_lines.append("⏱️ **【 무조건 관망 (달러 현금 유지) 】**")
        msg_lines.append("➔ 진입 조건 미충족. 가짜 반등에 속지 않고 소중한 예수금을 100% 안전하게 보호합니다.")

elif status == "HOLDING":
    trading_days_held = len(df[df.index.strftime('%Y-%m-%d') >= buy_date_str]) - 1
    profit_rate = ((current_price - buy_price) / buy_price) * 100
    
    # 보유 중일 때는 상단 브리핑에 계좌 평단 정보를 실시간 주입
    msg_lines.insert(5, f"🍏 계좌 평균단가: `${buy_price:.2f}` (현재 수익률: `{profit_rate:.1f}%`)")
    msg_lines.insert(6, f"⏱️ 현재 포지션 보유 기간: `{trading_days_held} 영업일`")

    # 🌟 매도 조건 충족 여부 검사
    if profit_rate >= 7.0:
        msg_lines.append("🎉 **【 전량 지정가 매도 예약 (7% 익절 완료) 】** 💰")
        msg_lines.append(f"➔ 목표 수익률 달성! 오늘 밤 키움 앱에서 평단 대비 +7% 가격인 **`${buy_price * 1.07:.2f}`에 지정가 매도 예약**을 걸어두세요.")
        with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
        
    elif current_price >= bb_upper:
        msg_lines.append("🚀 **【 전량 LOC 예약 매도 (볼밴 상한 익절) 】** 💰")
        msg_lines.append("➔ 주가가 볼밴 상한선에 도달하여 꼭대기 과열 신호입니다. 오늘 밤 **전량 LOC 매도 예약**으로 차익 실현하세요!")
        with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
        
    elif trading_days_held >= 3:
        msg_lines.append("💣 **【 전량 LOC 예약 매도 (3일 타임캡 강제 손절) 】** 🚨")
        msg_lines.append("➔ 약속된 3영업일 만기 시점이 도달했습니다. 손익과 무관하게 리스크 통제를 위해 오늘 밤 **전량 LOC 매도 예약**으로 무조건 탈출하세요!")
        with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
    else:
        msg_lines.append("📈 **【 전량 보유 유지 (즐거운 홀딩) 】**")
        msg_lines.append(f"➔ 아직 매도 조건이나 3일 만기 제한에 도달하지 않았습니다. 기술적 반등 폭발을 기다리며 하루 더 포지션을 끌고 갑니다.")

# ──────────────────────────────────────────────────
# 🚀 3. 최종 무조건 발송 파트 (의도된 침묵 해제)
# ──────────────────────────────────────────────────
send_telegram_message("\n".join(msg_lines))
print("➔ 텔레그램 일일 보고서 정기 발송 완료 완료!")
