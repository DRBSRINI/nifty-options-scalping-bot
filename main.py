import time
import datetime
from alice_blue import *
import pandas as pd
import numpy as np

# === USER CONFIG ===
import os

USERNAME = os.getenv('USERNAME')
PASSWORD = os.getenv('PASSWORD')
TOTP_SECRET = os.getenv('TOTP_SECRET')
API_KEY = os.getenv('API_KEY')

MAX_TRADES_PER_DAY = 5
MAX_CAPITAL = 70000
LOT_SIZE = 50
STOP_LOSS = 50
TARGET_PROFIT = 25
TRAILING_STOP = 5
ENTRY_START = datetime.time(9, 26)
ENTRY_END = datetime.time(15, 0)

# === INIT SESSION ===
socket_opened = False

def event_handler_quote_update(message):
    pass

def open_callback():
    global socket_opened
    socket_opened = True

alice = Aliceblue(user_id=USERNAME, api_key=API_KEY, session_id=None)
alice.get_session_id(password=PASSWORD, twoFA=TOTP_SECRET)

# === SYMBOL SELECTION ===
def get_option_symbol(index='NIFTY', strike_diff=-1, option_type='CE'):
    # This will fetch the ATM strike and adjust as needed
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

        rsi = ta.RSI(df_dict['3minute']['close'], timeperiod=14).iloc[-1]

        price_up = lambda x, y: (x - y) / y * 100 >= 1

        if all([
            c3 > c3_prev,
            c15 > c15_prev,
            c60 > c60_prev,
            price_up(c3, c3_prev),
            price_up(c15, c15_prev),
            price_up(c60, c60_prev),
            35 < rsi < 65
        ]):
            return True
        return False
    except:
        return False

# === ORDER MANAGEMENT ===
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
        if qty > LOT_SIZE:
            qty = LOT_SIZE

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
        print(f"Order placed for {side}: {order}")
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
        print("Trading window closed.")
        break

    time.sleep(60)
