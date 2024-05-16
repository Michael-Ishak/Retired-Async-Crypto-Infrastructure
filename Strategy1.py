import numpy as np
import pandas as pd
import time
import aiohttp
import logging
import asyncio
import base64
import hmac
import hashlib
from decouple import config
from decimal import Decimal
from debugging.mailer import send_failed_order_email
from datetime import datetime, timezone
from math import floor, log10
from typing import Optional

logger = logging.getLogger()

api_key = config("API_KEY")
api_secret = config("API_SECRET")
api_passphrase = config("API_PASSPHRASE")

timeout_settings = aiohttp.ClientTimeout(total=1, connect=1, sock_read=1)

########################
### Helper Functions ###
########################

def get_headers(resource: str):
    ### FIGURE OUT A WAY TO CHANGE "now" SO THAT UPDATE_KC_TIMESTAMP ALWAYS WORKS AND "now" GIVES THE RIGHT ANSWER
    now = int(round(time.time(), 0)) * 1000
    str_to_sign = str(now) + 'GET' + resource
    signature = base64.b64encode(
        hmac.new(api_secret.encode('utf-8'), str_to_sign.encode('utf-8'), hashlib.sha256).digest())

    passphrase = base64.b64encode(hmac.new(api_secret.encode('utf-8'), api_passphrase.encode('utf-8'), hashlib.sha256).digest())
    return {
        "KC-API-SIGN": signature.decode('utf-8'),
        "KC-API-TIMESTAMP": str(now),
        "KC-API-KEY": api_key,
        "KC-API-PASSPHRASE": passphrase.decode('utf-8'),
        "KC-API-KEY-VERSION": "2"
    }

async def update_KC_timestamp(session: aiohttp.ClientSession):
    async with session.get("https://api.kucoin.com/api/v1/timestamp") as response:
        timestamp = await response.json()
        current_time = timestamp['data']
    session.headers["KC-API-TIMESTAMP"] = str(current_time)

def get_bid_range(bids_listed: list[str], close_price):
    bid_prices_calc = []
    diff_prices_calc = []
    bid = []
    for bid_price in range(10):
        bid.append(bids_listed)
        bid_prices_calc.append(float(bids_listed[bid_price][0].replace('.', '')))
        diff_prices_calc.append(float(bids_listed[bid_price][0].replace('.', '')) - float(str(close_price).replace('.', '')))

    ptr = 0
    diff_prices_calc_len = len(diff_prices_calc)
    while ptr < diff_prices_calc_len and diff_prices_calc[ptr] < 5:
        ptr += 1

    return str(bid[ptr])

def truncate(n: int, min_truncate: float) -> str:
    return str(floor(float(n)*10**min_truncate)/10**min_truncate)


# @profile(stream=mems_logs)
def weighting(ratio: list[float]) -> tuple[float]:
    total_sum = np.sum(ratio)
    return tuple([i/total_sum for i in ratio])

async def fetch_data(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url, timeout=10) as response:
        if response.status == 200:
            data = await response.json()
            if 'msg' not in data.keys():
                return data
        if response.status == 429:
            logger.info("Rate limit exceeded. Retrying after delay.")
            await asyncio.sleep(10)  # Adjust delay as needed
            return await fetch_data(session, url)
        else:
            logger.info(f"Request failed with status {response.status}")
    return None

async def get_accounts(session: aiohttp.ClientSession, currency=None, account_type=None) -> list:
    await update_KC_timestamp(session)
    url = 'https://api.kucoin.com/api/v1/accounts'
    params = {}
    if currency:
        params['currency'] = currency
    if account_type:
        params['type'] = account_type

    async with session.get(url, headers=get_headers('/api/v1/accounts'), params=params) as response:
        response_data = await response.json()
        if response.status == 200:
            return response_data['data']
        else:
            raise Exception(f"Error getting accounts: {response_data['msg']}")

################
### Strategy ###
################


class Strategy:
    def __init__(self, name) -> None:
        self.open_long = False
        self.name = name
        self.session = None

    async def run(self, *args, **kwargs) -> None:
        self.session = aiohttp.ClientSession(timeout=timeout_settings)
        await self.schedule_lr_trend_2hour(*args, **kwargs)

    def wrapped_log(self, log: str):
        logger.info(f"{self.name} {log}")
    
    async def bid_ask(self, session, symbol_base, symbol_quote, amount, price):
        ### Bid-Ask Spread
        try:
            resource = "/api/v1/market/orderbook/level2_20"
            await update_KC_timestamp(session)
            async with session.get(f'https://api.kucoin.com{resource}?symbol={symbol_base}-{symbol_quote}', headers=get_headers(resource)) as req:
                # Minimum I can buy/sell at a time
                bid_ask_data = await req.json()
                self.wrapped_log(f"ba {bid_ask_data}")
                bids = bid_ask_data['data']['bids'] # Correctly access the 'bids' list
                self.wrapped_log(f"bids {bids}")
        except Exception as e:
            send_failed_order_email(symbol_base, symbol_quote, "Bid-Ask", e)
            return # Return early if an exception occurs

        total_vol = 0
        ptr = 0

        upper = get_bid_range(bids, price)

        price = 0
        while (bids[ptr][0] <= upper) or (total_vol >= amount):
            total_vol += float(bids[ptr][1])
            ptr += 1
            if ptr >= len(bids):
                break

        self.wrapped_log(f"volume: {total_vol}")
        return total_vol


    async def place_order(self, trade, symbol_base, symbol_quote, side, amount, session, price, min_truncate, retries=100):
        if side == 'buy':
            for attempt in range(retries):
                try:
                    adjusted_amount = await self.bid_ask(session, symbol_base, symbol_quote, amount, price)
                    adjusted_amount = truncate(adjusted_amount, min_truncate)
                    self.wrapped_log(f"Volume :{adjusted_amount}")
                    trade.create_market_order(f'{symbol_base}-{symbol_quote}', side, size=adjusted_amount)
                    break
                except Exception as e:
                    logger.error("Error placing order", extra={'attempt_num': attempt + 1, 'error': str(e)}, exc_info=True)
                    if attempt < retries - 1:
                        await asyncio.sleep(10)
                    else:
                        logger.error("Failed to place order after multiple attempts.", exc_info=True)
                        send_failed_order_email(symbol_base, e, side, adjusted_amount)
        else:
            for attempt in range(retries):
                try:
                    amount = truncate(amount, min_truncate)
                    trade.create_market_order(f'{symbol_base}-{symbol_quote}', side, size=amount)
                    break # Success, break out of the loop
                except Exception as e:
                    logger.error("Error placing order", extra={'attempt_num': attempt + 1, 'error': str(e)}, exc_info=True)
                    if attempt < retries - 1: # Don't sleep on the last attempt
                        await asyncio.sleep(10) # Wait before retrying
                    else:
                        logger.error("Failed to place order after multiple attempts.", exc_info=True)
                        send_failed_order_email(symbol_base, symbol_quote, side, amount)


    async def schedule_lr_trend_2hour(self, symbol_base: str, symbol_quote: str, weight: float, user, market, trade, *args, **kwargs):
        while True:
            await self.LR_Trend_2hour(symbol_base, symbol_quote, weight, user, market, trade, *args, **kwargs)
            await asyncio.sleep(3)  # Run every 3secs

    async def LR_Trend_2hour(self, symbol_base: str, symbol_quote: str, weight: float, user, market, trade, session: Optional[aiohttp.ClientSession] = None) -> None:
        starting_date = float(round(time.time())) - 2 * 365 * 24 * 3600
        timeframe = "XXX"

        if not session:
            session = aiohttp.ClientSession()

        url = f'https://api.kucoin.com/api/v1/market/candles?type={timeframe}&symbol={symbol_base}-{symbol_quote}&startAt={int(starting_date)}'

        try:
            data = await fetch_data(session, url)
            if data:
                data = pd.DataFrame(data['data'], columns = ['timestamp', 'open', 'close', 'high', 'low', 'amount', 'volume'])
                data['close'] = pd.to_numeric(data['close'], downcast='float')
                data['open'] = pd.to_numeric(data['open'], downcast='float')
                data['high'] = pd.to_numeric(data['high'], downcast='float')
                data['low'] = pd.to_numeric(data['low'], downcast='float')
                data['timestamp'] = pd.to_datetime(data['timestamp'].apply(int), unit='s')
                data = data.iloc[::-1]
            else:
                self.wrapped_log("Failed to fetch data.")
        except Exception as e:
            send_failed_order_email(symbol_base, symbol_quote, "Fetching Data", e)

        ################
        ### Strategy ###
        ################

        ### INPUT YOUR STRATEGY ENTRY AND EXITS

        #######################
        ### Risk Management ###
        #######################

        ### INPUT YOUR RISK MANAGEMENT STRUCTURE

        ############
        ### Prep ###
        ############

        ### Balances
        account_lists = await get_accounts(session)  

        balance_quote = 0
        balance_base = 0
        for item in account_lists:
            if item['type'] == 'trade' and item['currency'] == symbol_quote:
                balance_quote = float(item["balance"])
            if item['type'] == 'trade' and item['currency'] == symbol_base:
                balance_base = float(item["balance"])
            #     print(f"Balance_base: {balance_base}")
            # print(f'Currencies: {float(item["balance"])} {item["currency"]}')

        logged_quote = False # Flag to track if balance_quote has been logged
        logged_base = False # Flag to track if balance_base has been logged
        for account in account_lists:
            if account['currency'] == symbol_quote and account['type'] == 'trade' and not logged_quote:
                self.wrapped_log(f"symbol_quote balance before weight {float(account['available'])}")
                self.wrapped_log(f"symbol_base balance before weight {balance_base} {symbol_base}")
                # balance_quote = (float(account['available']) * 0.5) * weight
                balance_quote = float(account['available']) * 0.33
                logged_quote = True # Set the flag to True to prevent further logging
            elif account['currency'] == symbol_base and account['type'] == 'trade' and not logged_base:
                balance_base = float(account['available'])
                logged_base = True # Set the flag to True to prevent further logging           
        ### Price
        price = self.get_price(market, symbol_base, symbol_quote)

        ### Minimum requirements
        try:
            async with session.get(f'https://api.kucoin.com/api/v1/symbols/{symbol_base}-{symbol_quote}') as response:  # Minimum I can buy/sell at a time
                info = await response.json()
                info = info['data']
        except Exception as e:
            send_failed_order_email(symbol_base, symbol_quote, "Min_Reqs", e)

        # Truncation
        min_truncate = int(abs(log10(float(info['baseIncrement']))))

        # Min amounts
        min_quote_for_buy = float(info['minFunds'])
        min_base_for_sell = float(truncate(float(min_quote_for_buy)/price, min_truncate))

        ##############
        ### Orders ###
        ##############

        now = datetime.now(timezone.utc)
        current_time = now.strftime("%d/%m/%Y %H:%M:%S")

        if entry_long and balance_quote > min_quote_for_buy and not self.open_long:
            self.wrapped_log("Attempting to go long...")
            self.wrapped_log(f"Amount without trunc is: {balance_quote/price}")
            amount = balance_quote / price
            await self.place_order(trade, symbol_base, symbol_quote, 'buy', amount, session, price, min_truncate)
            self.open_long = True
            self.wrapped_log(f"{current_time}: bought {amount} {symbol_base} at {price}")
            self.wrapped_log(f'I have {balance_base} {symbol_base}!!')
            self.wrapped_log(f'I have {balance_quote} {symbol_quote} for trading {symbol_base}!!')

        if (close_long or cover or cover_curr) and balance_base > min_base_for_sell and self.open_long:
            self.wrapped_log("Attempting to close long...")
            amount = balance_base
            await self.place_order(trade, symbol_base, symbol_quote, 'sell', amount, session, price, min_truncate)
            self.open_long = False
            self.wrapped_log(f"{current_time}: sold {amount} {symbol_base} at {price}")
            self.wrapped_log(f'I have {balance_quote} {symbol_quote} for trading {symbol_base}!!')

        # self.wrapped_log(f'open long is {self.open_long} for symbol {symbol_base}-{symbol_quote}.')
    
        self.wrapped_log(f"{data.iloc[-2]['timestamp']} symbol_base: {symbol_base}, symbol_quote: {symbol_quote}, weight: {weight}, entry_long: {entry_long}, close_long: {close_long}.")

    def get_price(self, market, symbol_base, symbol_quote):
        try:
            price = float(market.get_ticker(f'{symbol_base}-{symbol_quote}')['price'])
        except Exception as e:
            logger.error(f"Error getting price: {e}")
            price = None
            send_failed_order_email(symbol_base, symbol_quote, "get_price", e)
            
        return price
    

def calculate_range(number):
    # Convert the number to a string and split at the decimal point
    parts = str(number).split('.')
    
    # Determine the highest precision
    if len(parts) == 2:
        highest_precision = len(parts[1])
    else:
        highest_precision = 0
    
    # Calculate 10 raised to the power of the highest precision
    base = 10 ** highest_precision
    
    # Calculate the range
    lower_bound = Decimal(number) - Decimal(3 / base)
    upper_bound = Decimal(number) + Decimal(3 / base)
    
    return lower_bound, upper_bound