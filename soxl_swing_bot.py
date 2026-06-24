import os
import json
import requests
import yfinance as yf
import pandas as pd

# 1. 환경 변수 및 설정 세팅
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
POSITION_FILE = 'soxl_position.txt'

def send_telegram_message(message):
    """텔레그램 채널로 지령 및 브리핑 발송"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("💡 [경고] 텔레그램 토큰 또는 CHAT_ID가 설정되지 않았습니다.")
        print(message)
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ 텔레그램 발송 실패: {e}")

def calculate_indicators(df):
    """핵심 기술적 지표 계산 (MA200, 볼린저밴드, RSI7)"""
    # 장기 추세 필터: 200일 이동평균선
    df['MA200'] = df['Close'].rolling(window=200).mean()
    
    # 볼린저 밴드 (20, 2)
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['STD20'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['MA20'] + (df['STD20'] * 2)
    df['BB_Lower'] = df['MA20'] - (df['STD20'] * 2)
    
    # 웰레스 와일더 rsi(7) 계산 방식
    delta = df['Close'].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ema_up = up.ewm(com=6, adjust=False).mean()
    ema_down = down.ewm(com=6, adjust=False).mean()
    rs = ema_up / ema_down
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df

def load_position():
    """상태 파일 읽기 (JSON 고도화)"""
    default_position = {
        "status": "CASH",       # CASH, HOLDING_1ST, HOLDING_2ND
        "buy_price_1": 0.0,     # 1차 매수가
        "buy_price_2": 0.0,     # 2차 매수가
        "avg_price": 0.0,       # 최종 평단가
        "holding_days": 0       # 보유 영업일수
    }
    
    if not os.path.exists(POSITION_FILE):
        return default_position
        
    with open(POSITION_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return default_position

def save_position(position):
    """상태 파일 저장"""
    with open(POSITION_FILE, 'w', encoding='utf-8') as f:
        json.dump(position, f, indent=4, ensure_ascii=False)

def main():
    # 200일선을 구하기 위해 2년치 데이터 넉넉하게 수집
    ticker = yf.Ticker("SOXL")
    df = ticker.history(period="2y")
    
    if df.empty or len(df) < 200:
        print("❌ 데이터가 부족하여 지표를 계산할 수 없습니다.")
        return
        
    df = calculate_indicators(df)
    
    # 최신 영업일 데이터 추출
    current_data = df.iloc[-1]
    close_price = float(current_data['Close'])
    rsi = float(current_data['RSI'])
    bb_lower = float(current_data['BB_Lower'])
    bb_upper = float(current_data['BB_Upper'])
    ma200 = float(current_data['MA200'])
    
    # 포지션 상태 로드
    pos = load_position()
    status = pos['status']
    
    # 공통 상단 브리핑 메세지 구성
    report_header = (
        f"📊 *[SOXL Sniper Bot 정기 브리핑]*\n"
        f"• 현재가: ${close_price:.2f}\n"
        f"• RSI(7): {rsi:.1f}\n"
        f"• 볼밴 하단: ${bb_lower:.2f} / 상단: ${bb_upper:.2f}\n"
        f"• 200일 이동평균선: ${ma200:.2f}\n"
        f"• 현재 포지션 상태: `{status}`\n"
        f"------------------------------------------\n"
    )
    
    action_msg = ""
    state_changed = False
    
    # ==================== [CASE 1: 현금 100% 상태] ====================
    if status == "CASH":
        # 핵심 보완: 현재가가 무조건 200일선 위에 있을 때만 진입 (장기 상승 추세 필터)
        if close_price > ma200:
            if close_price <= bb_lower and rsi <= 25:
                action_msg = (
                    f"🚨 *【 SOXL 1차 LOC 예약 매수 지령 】*\n"
                    f"• 사유: 200일선 위 상승추세 중 단기 과매도 임박\n"
                    f"• 지령: 별도 계좌 예수금의 *50%* 매수 주문 (LOC)"
                )
                pos['status'] = "HOLDING_1ST"
                pos['buy_price_1'] = close_price
                pos['avg_price'] = close_price
                pos['holding_days'] = 0
                state_changed = True
            else:
                action_msg = "⏱️ *【 무조건 관망 】*\n• 장기 추세는 좋으나 단기 매수 조건(볼밴 하단 및 RSI) 미충족."
        else:
            action_msg = "⚠️ *【 매수 금지 / 하락장 관망 】*\n• 현재가가 200일선 아래에 있습니다. 위험 구역이므로 모든 매수 신호를 차단합니다."

    # ==================== [CASE 2: 1차 매수 완료 상태 (시드 50% 보유)] ====================
    elif status == "HOLDING_1ST":
        pos['holding_days'] += 1
        state_changed = True
        
        profit_pct = ((close_price - pos['avg_price']) / pos['avg_price']) * 100
        
        # A. 매도 조건 검증 (볼밴 상단 터치 OR 익절 목표치 도달 OR 3일 만기 제한)
        if close_price >= bb_upper or profit_pct >= 7.0 or pos['holding_days'] >= 3:
            reason = "볼린저 밴드 상단 터치" if close_price >= bb_upper else ("목표 수익률(+7%) 달성" if profit_pct >= 7.0 else "3일 타임캡 만기 완료")
            action_msg = (
                f"📤 *【 SOXL 1차 포지션 전량 매도 】*\n"
                f"• 사유: {reason}\n"
                f"• 매도가: ${close_price:.2f} (수익률: {profit_pct:+.1f}% / 보유 {pos['holding_days']}일)"
            )
            pos = {"status": "CASH", "buy_price_1": 0.0, "buy_price_2": 0.0, "avg_price": 0.0, "holding_days": 0}
            
        # B. 매도 조건은 아니나, 주가가 더 흘러내려 2차 매수 타이밍이 왔을 때
        # 분석 반영: 2차 매수는 낙폭 과대를 고려하여 RSI 20 이하로 더 엄격하게 제한 + 1차 매수가보다 낮을 때만
        elif close_price <= bb_lower and rsi <= 20 and close_price < pos['buy_price_1']:
            action_msg = (
                f"🚨 *【 SOXL 2차 LOC 추가 매수 지령 】*\n"
                f"• 사유: 1차 진입 후 주가 추가 폭락으로 지하실 도달 (RSI 20 이하)\n"
                f"• 지령: 남은 계좌 예수금 전량(*나머지 50%*) 매수 주문 (LOC)"
            )
            pos['status'] = "HOLDING_2ND"
            pos['buy_price_2'] = close_price
            pos['avg_price'] = (pos['buy_price_1'] + close_price) / 2  # 동일 비중이므로 단순 평균
            pos['holding_days'] = 0  # 2차 매수 시점부터 타임캡 3일 새로 적용
        
        else:
            action_msg = f"⏱️ *【 SOXL 1차 보유 중 관망 】*\n• 현재 수익률: {profit_pct:+.1f}% (보유 {pos['holding_days']}일차)"

    # ==================== [CASE 3: 2차 매수까지 완료 상태 (시드 100% 보유)] ====================
    elif status == "HOLDING_2ND":
        pos['holding_days'] += 1
        state_changed = True
        
        profit_pct = ((close_price - pos['avg_price']) / pos['avg_price']) * 100
        
        # 최종 매도 조건 검증
        if close_price >= bb_upper or profit_pct >= 7.0 or pos['holding_days'] >= 3:
            reason = "볼린저 밴드 상단 터치" if close_price >= bb_upper else ("목표 수익률(+7%) 달성" if profit_pct >= 7.0 else "3일 타임캡 만기 완료")
            action_msg = (
                f"📤 *【 SOXL 최종 포지션 전량 매도 】*\n"
                f"• 사유: {reason}\n"
                f"• 최종 매도가: ${close_price:.2f} (최종 수익률: {profit_pct:+.1f}% / 2차 진입 후 {pos['holding_days']}일)"
            )
            pos = {"status": "CASH", "buy_price_1": 0.0, "buy_price_2": 0.0, "avg_price": 0.0, "holding_days": 0}
        else:
            action_msg = f"⏱️ *【 SOXL 최종 보유 중 관망 】*\n• 현재 평단가: ${pos['avg_price']:.2f}\n• 현재 수익률: {profit_pct:+.1f}% (보유 {pos['holding_days']}일차)"

    # 포지션 변경 사항이 있다면 저장
    if state_changed:
        save_position(pos)
        
    # 최종 메시지 조립 후 발송
    full_message = report_header + action_msg
    send_telegram_message(full_message)

if __name__ == "__main__":
    main()
