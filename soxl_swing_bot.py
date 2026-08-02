import os
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime

# ====================================================
# ⚙️ 시스템 기본 세팅 및 시크릿 로드
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

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] SOXL 스나이퍼 봇(v2.5 강세장 분할형) 가동")

# 🌟 200일 이평선 계산 시 에러 방지를 위해 넉넉하게 2년치 데이터 수집 (안정성 강화)
df = yf.download(TICKER, period="2y", interval="1d")

if df.empty or len(df) < 200:
    print("❌ 200일 이평선 계산을 위한 데이터가 부족합니다.")
    exit(1)

# yfinance 최신 버전의 MultiIndex 열 구조 강제 평탄화
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

# 휴일 공백 제거
df = df[df['Close'].notna()]

# ──────────────────────────────────────────────────
# 📊 핵심 기술적 지표 계산 엔진 (200MA / 20MA / 볼밴 / 정밀RSI)
# ──────────────────────────────────────────────────
# 1. 200일 장기 대추세 이평선
df['MA200'] = df['Close'].rolling(window=200).mean()

# 2. 볼린저 밴드 및 20일 기준선
df['Mid'] = df['Close'].rolling(window=20).mean() # 이 값이 곧 MA20선입니다.
df['Std'] = df['Close'].rolling(window=20).std()
df['BB_Lower'] = df['Mid'] - (2 * df['Std'])
df['BB_Upper'] = df['Mid'] + (2 * df['Std'])

# 3. 🌟 증권사 표준 웰레스 와일더(Welles Wilder) 정밀 RSI(7)
delta = df['Close'].diff()
gain = delta.clip(lower=0)
loss = -delta.clip(upper=0)
wilder_gain = gain.ewm(com=6, adjust=False).mean()  # period-1 = 6
wilder_loss = loss.ewm(com=6, adjust=False).mean()
rs = wilder_gain / wilder_loss
df['RSI_7'] = 100 - (100 / (1 + rs))

# 전일 최종 확정 데이터 추출
latest = df.iloc[-1]
current_price = float(latest['Close'])
bb_lower = float(latest['BB_Lower'])
bb_upper = float(latest['BB_Upper'])
rsi_7 = float(latest['RSI_7'])
ma200 = float(latest['MA200'])
ma20 = float(latest['Mid']) # 20일선 가격 추출

# 포지션 상태 불러오기 (기존의 심플 쉼표 분리 포맷 유지)
if not os.path.exists(POSITION_FILE):
    with open(POSITION_FILE, "w") as f:
        f.write("CASH,,0.0")

with open(POSITION_FILE, "r") as f:
    status, buy_date_str, buy_price_str = f.read().strip().split(",")
    buy_price = float(buy_price_str)

# ──────────────────────────────────────────────────
# 📱 텔레그램 일일 사령탑 보고서 기본 구성
# ──────────────────────────────────────────────────
msg_lines = [
    "🤖 **[SOXL 스나이퍼 v2.5]** 일일 매매 가이드",
    f"📅 분석 일시: `{datetime.now().strftime('%Y-%m-%d %H:%M')}`",
    f"📊 SOXL 전일 종가: `${current_price:.2f}`",
    f"📉 볼밴 하한선: `${bb_lower:.2f}` | 상한선: `${bb_upper:.2f}`",
    f"⚡ 정밀 RSI(7) 지표: `{rsi_7:.1f}`",
    f"📈 장기선(200MA): `${ma200:.2f}` | 📊 단기선(20MA): `${ma20:.2f}`",
    "─" * 15,
    "📢 **[오늘 밤 최종 매매 지령]**"
]

# ──────────────────────────────────────────────────
# ⚔️ 매매 알고리즘 제어 로직 (이원화 분할 진입 반영)
# ──────────────────────────────────────────────────
if status == "CASH":
    # 🛑 [최상위 방화벽] 주가가 200일선 위에 있을 때만 진입 허용
    if current_price > ma200:
        # 조건 A: 오리지널 스나이퍼 (진바닥 타점) -> 100% 진입
        if current_price <= bb_lower and rsi_7 <= 25:
            msg_lines.append("🛒 **【 SOXL 100% 전량 LOC 예약 매수 】** 🚨")
            msg_lines.append("➔ **[추세 안전지대 진입]** 200일선 위 장기 우상향 궤도 안에서 아주 매력적인 단기 과매도 진바닥 신호가 켜졌습니다. 오늘 밤 부계좌의 **80달러 전액(100%)을 LOC 매수 예약** 하세요!")
            
            today_str = datetime.now().strftime("%Y-%m-%d")
            with open(POSITION_FILE, "w") as f:
                f.write(f"HOLDING,{today_str},{current_price}")
                
        # 조건 B: 강세장 정찰대 (완만한 조정 타점) -> 20% 진입 (FOMO 방지)
        elif current_price <= ma20 and rsi_7 <= 35:
            msg_lines.append("🛒 **【 SOXL 20% 정찰대 LOC 예약 매수 】** 🦊")
            msg_lines.append("➔ **[강세장 소외 방지 정찰대]** 200일선 위 대세 상승장 속에서 건강한 숨고르기 조정이 포착되었습니다. 상승 랠리 소외를 막기 위해 오늘 밤 **총 시드의 20% (약 16달러)만큼만 LOC 매수 예약**을 진행합니다!")
            
            today_str = datetime.now().strftime("%Y-%m-%d")
            with open(POSITION_FILE, "w") as f:
                f.write(f"SCOUT,{today_str},{current_price}")
                
        else:
            msg_lines.append("⏱️ **【 무조건 관망 (달러 현금 유지) 】**")
            msg_lines.append("➔ 대세 상승 추세는 아주 건강하나, 오늘 밤은 과매도 및 정찰대 진입 조건이 아닙니다. 예수금을 안전하게 쥐고 대기합니다.")
    else:
        # 200일선 아래 하락장일 때는 무조건 신호 차단
        msg_lines.append("⚠️ **【 매수 금지 / 폭락 하락장 관망 】**")
        msg_lines.append("➔ 현재 주가가 200일선 아래에 머물러 있습니다. 리스크가 매우 높은 칼날 구역이므로 모든 매수 엔진을 끄고 안전하게 지켜봅니다.")

elif status == "SCOUT":
    # 정찰대가 나가 있는 상태에서 추가 폭락(진바닥)이 왔을 경우 ➔ 본대 80% 추가 투입 로직
    if current_price > ma200 and current_price <= bb_lower and rsi_7 <= 25:
        msg_lines.insert(6, f"🦊 기존 정찰대 평균단가: `${buy_price:.2f}`")
        msg_lines.append("🔥 **【 SOXL 남은 80% 추가 LOC 예약 매수 (본대 격전환) 】** 🚨")
        msg_lines.append("➔ **[정찰대에서 본대로 전환]** 정찰대 진입 후 주가가 볼밴 하단까지 기습 폭락했습니다! 완벽한 진바닥 찬스이므로, 오늘 밤 **남은 예수금 80% 전액을 추가 LOC 매수 예약**하여 풀 포지션으로 대응합니다.")
        
        # 평단가 조정 (정찰대 20% + 본대 80% 혼합 평단 계산식)
        blended_price = (buy_price * 0.2) + (current_price * 0.8)
        today_str = datetime.now().strftime("%Y-%m-%d")
        with open(POSITION_FILE, "w") as f:
            f.write(f"HOLDING,{today_str},{blended_price}")
            
    else:
        # 정찰대 상태에서의 일반 청산 로직 검사
        trading_days_held = len(df[df.index.strftime('%Y-%m-%d') >= buy_date_str]) - 1
        profit_rate = ((current_price - buy_price) / buy_price) * 100
        
        msg_lines.insert(6, f"🦊 정찰대 평균단가: `${buy_price:.2f}` (현재 수익률: `{profit_rate:.1f}%`)")
        msg_lines.insert(7, f"⏱️ 정찰대 포지션 보유 기간: `{trading_days_held} 영업일`")

        if profit_rate >= 7.0:
            msg_lines.append("🎉 **【 정찰대 전량 지정가 매도 예약 (7% 익절 완료) 】** 💰")
            msg_lines.append(f"➔ 목표 수익률 도달! 오늘 밤 +7% 가격인 **`${buy_price * 1.07:.2f}`에 지정가 매도 예약**을 걸어두세요.")
            with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
        elif current_price >= bb_upper:
            msg_lines.append("🚀 **【 정찰대 전량 LOC 예약 매도 (볼밴 상한 익절) 】** 💰")
            msg_lines.append("➔ 볼밴 상한선 터치로 단기 과열입니다. 오늘 밤 **전량 LOC 매도 예약**으로 차익 실현하세요!")
            with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
        elif trading_days_held >= 3:
            msg_lines.append("💣 **【 정찰대 전량 LOC 예약 매도 (3일 타임캡 탈출) 】** 🚨")
            msg_lines.append("➔ 3영업일 만기 제한에 도달했습니다. 오늘 밤 **손익 상관없이 전량 LOC 매도 예약**으로 탈출하세요!")
            with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
        else:
            msg_lines.append("📈 **【 정찰대 보유 유지 (추가 조정 대기) 】**")
            msg_lines.append("➔ 아직 청산 조건이나 본대 추가 매수 조건에 도달하지 않았습니다. 정찰대 포지션을 하루 더 유지합니다.")

elif status == "HOLDING":
    # 본대(100%)가 가동 중일 때의 기존 청산 로직
    trading_days_held = len(df[df.index.strftime('%Y-%m-%d') >= buy_date_str]) - 1
    profit_rate = ((current_price - buy_price) / buy_price) * 100
    
    msg_lines.insert(6, f"🍏 계좌 평균단가: `${buy_price:.2f}` (현재 수익률: `{profit_rate:.1f}%`)")
    msg_lines.insert(7, f"⏱️ 현재 포지션 보유 기간: `{trading_days_held} 영업일`")

    if profit_rate >= 7.0:
        msg_lines.append("🎉 **【 전량 지정가 매도 예약 (7% 익절 완료) 】** 💰")
        msg_lines.append(f"➔ 목표 수익률 깔끔하게 도달! 오늘 밤 키움 앱에서 평단 대비 +7% 가격인 **`${buy_price * 1.07:.2f}`에 지정가 매도 예약**을 걸어두세요.")
        with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
        
    elif current_price >= bb_upper:
        msg_lines.append("🚀 **【 전량 LOC 예약 매도 (볼밴 상한 익절) 】** 💰")
        msg_lines.append("➔ 종가가 볼밴 상한선을 뚫어 단기 꼭대기 과열 신호입니다. 오늘 밤 키움 앱에서 **전량 LOC 매도 예약**으로 차익 실현하세요!")
        with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
        
    elif trading_days_held >= 3:
        msg_lines.append("💣 **【 전량 LOC 예약 매도 (3일 타임캡 강제 탈출) 】** 🚨")
        msg_lines.append("➔ 약속된 3영업일 만기 제한에 도달했습니다. 추가적인 변동성 노출 위험을 막기 위해 오늘 밤 **손익 상관없이 전량 LOC 매도 예약**으로 탈출하세요!")
        with open(POSITION_FILE, "w") as f: f.write("CASH,,0.0")
    else:
        msg_lines.append("📈 **【 전량 보유 유지 (즐거운 홀딩) 】**")
        msg_lines.append("➔ 아직 목표가 도달이나 3일 기한이 되지 않았습니다. 기술적 반등 폭발을 기다리며 하루 더 포지션을 유지합니다.")

# 최종 텔레그램 무조건 쏘기
send_telegram_message("\n".join(msg_lines))
print("➔ 텔레그램 일일 보고서 정기 발송 완료!")
