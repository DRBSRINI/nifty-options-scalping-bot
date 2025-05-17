import time
import datetime
import requests
from alice_blue import *
import pandas as pd
import numpy as np

# === CONFIG ===
USERNAME = '445901'  # Your AliceBlue Client ID
ACCESS_TOKEN_URL = "https://software.myriadtechnology.in/backend/aliceblue/access_token?email=drbsrini@gmail.com"
MAX_TRADES_PER_DAY = 5
MAX_CAPITAL = 70000
LOT_SIZE = 50
STOP_LOSS = 50
TARGET_PROFIT = 25
TRAILING_STOP = 5
ENTRY_START = datetime.time(9, 26)
ENTRY_END = datetime.time(15, 0)

# === GET SESSION ID ===
response = requests.get(ACCESS_TOKEN_URL)
if response.status_code != 200 or not response.text:
    raise Exception("❌ Failed to fetch session ID from access_token URL")
session_id = response.text.strip()
print("✅ Session ID:", session_id)

# === CONNECT TO ALICEBLUE ===
alice = AliceBlue(username=USERNAME, session_id=session_id)
profile = alice.get_profile()
print("🧾 Connected as:", profile["name"])

# === SYMBOL FETCH ===
def get_option_symbol(index='NIFTY', strike_diff=-1, option_type='CE'):
    ltp = float(alice.get_ltp(alice.get_instrument_by_symbol("NSE", index))['ltp'])
    atm_strike = round(ltp / 50) * 50 + (strike_diff * 50)
    expiry = alice.get_next_expiry("NSE", index_type="OPTIDX")
    symbol = f"{index}{expiry}{atm_strike}{option_type}"
    return alice.get_instrument_by_symbol("NFO", symbol)

# === MTF DATA ===
def fetch_mtf_data(symbol, intervals=['3minute', '15minute', '60minute']):
    df_dict = {}
    for interval in intervals:
        df = alice.get_historical_data(
            instrument=symbol,
            from_datetime=datetime.datetime.now() - datetime.timedelta(days=3),
            to_datetime=datetime.datetime.now(),
            interval=interval
        )
        df_dict[interval] = pd.DataFrame(df)
    return df_dict

# === SIGNAL LOGIC ===
def check_entry_signal(df_dict):
    try:
        c3 = df_dict['3minute']['close'].iloc[-1]
        c3_prev = df_dict['3minute']['close'].iloc[-2]
        c15 = df_dict['15minute']['close'].iloc[-1]
        c15_prev = df_dict['15minute']['close'].iloc[-2]
        c60 = df_dict['60minute']['close'].iloc[-1]
        c60_prev = df_dict['60minute']['close'].iloc[-2]

        rsi_series = pd.Series(df_dict['3minute']['close'])
        delta = rsi_series.diff().dropna()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        rsi_last = rsi.iloc[-1] if not rsi.empty else 50

        def price_up(x, y):
            return (x - y) / y * 100 >= 1

        if all([
            c3 > c3_prev,
            c15 > c15_prev,
            c60 > c60_prev,
            price_up(c3, c3_prev),
            price_up(c15, c15_prev),
            price_up(c60, c60_prev),
            35 < rsi_last < 65
        ]):
            return True
        return False
    except Exception as e:
        print("Signal check error:", e)
        return False

# === ORDER MANAGER ===
class TradeManager:
    def __init__(self):
        self.trades_taken = {'CE': 0, 'PE': 0}

    def can_trade(self, side):
        return self.trades_taken[side] < MAX_TRADES_PER_DAY

    def record_trade(self, side):
        self.trades_taken[side] += 1

    def place_order(self, instrument, side):
        if not self.can_trade(side):
            return

        price = alice.get_ltp(instrument)['ltp'] + 0.05
        qty = int(MAX_CAPITAL / price / LOT_SIZE) * LOT_SIZE
        qty = min(qty, LOT_SIZE)

        order = alice.place_order(
            transaction_type=TransactionType.Buy,
            instrument=instrument,
            quantity=qty,
            order_type=OrderType.Limit,
            product_type=ProductType.MIS,
            price=price,
            trigger_price=None,
            stop_loss=STOP_LOSS,
            square_off=TARGET_PROFIT,
            trailing_sl=TRAILING_STOP,
            is_amo=False
        )
        print(f"✅ Order placed for {side}: {order}")
        self.record_trade(side)

# === MAIN LOOP ===
manager = TradeManager()

while True:
    now = datetime.datetime.now().time()
    if ENTRY_START <= now <= ENTRY_END:
        for option_type in ['CE', 'PE']:
            instrument = get_option_symbol(option_type=option_type)
            df_dict = fetch_mtf_data(instrument)
            if check_entry_signal(df_dict):
                manager.place_order(instrument, option_type)

    elif now > ENTRY_END:
        print("⏹ Trading window closed.")
        break

    time.sleep(60)
