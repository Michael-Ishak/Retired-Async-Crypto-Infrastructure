import os
import glob
import aiohttp
import asyncio
import logging
import time
import numpy as np
from decouple import config
from strategies.Strategy1 import Strategy1
from kucoin.client import Trade, Market, User
from datetime import datetime, timezone

now = int(time.mktime(datetime.now(timezone.utc).timetuple())*1e3)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    filename=f"Live_logging_{now}.txt"
    )

api_key = config("API_KEY")
api_secret = config("API_SECRET")
api_passphrase = config("API_PASSPHRASE")

user = User(api_key, api_secret, api_passphrase)
market = Market(api_key, api_secret, api_passphrase)
trade = Trade(api_key, api_secret, api_passphrase)

logging.info("Authorisation Successful!")

def weighting(ratio: list[float]) -> tuple[float]:
    total_sum = np.sum(ratio)
    return tuple([i/total_sum for i in ratio])

async def log_remover(directory: str, prefix_of_filename: str, file_size: int):
    while True:
        prefix_of_filename = prefix_of_filename + '*'
        files = glob.glob(os.path.join(directory, prefix_of_filename))
        files.sort(key=os.path.getmtime, reverse=True)

        for file in files:
            if os.path.getsize(file) > file_size:
                # Truncate the log file if its size exceeds the specified limit
                with open(file, "w"):
                    pass
                logging.info(f"The file '{file}' has been truncated.")

        await asyncio.sleep(15)

async def run_lr_thread_2hour_forever(*args, **kwargs) -> None:
    LR_instance = Strategy1(name=kwargs.get('name'))
    while True:
        await LR_instance.LR_Trend_2hour(*args, **kwargs)
        await asyncio.sleep(1)

async def _multi_process_run_lr_trend_2hr(weights_Strategy1: tuple[float], weights_MC_KC: tuple[float]) -> None:
    async with aiohttp.ClientSession() as session:
        coroutines = [
            ### Input your strategy files, I've put activated one stratgy for 4 instruments as an example
            Strategy1(name="Scalper 1").run("ETH", "USDT", weights_MC_KC[0], user, market, trade, session),
            Strategy1(name="Scalper 2").run("SOL", "USDT", weights_MC_KC[1], user, market, trade, session),
            Strategy1(name="Scalper 3").run("BTC", "USDT", weights_MC_KC[2], user, market, trade, session),
            Strategy1(name="Scalper 4").run("XRP", "USDT", weights_MC_KC[2], user, market, trade, session)
        ]

        for completed_coro in asyncio.as_completed(coroutines):
            try:
                await completed_coro
            except Exception as e:
                logging.error(f"Exception occurred: {e}")
                raise e

async def _single_thread_run_lr_thread_2hr(weights_Strategy1: tuple[float], weights_MC_KC: tuple[float]) -> None:
    async with aiohttp.ClientSession() as session:
        args_set = (
            ("SOL", "USDT", weights_Strategy1[0], user, market, trade, session),
            ("SUKU", "USDT", weights_Strategy1[1], user, market, trade, session),
            ("GST", "USDT", weights_Strategy1[2], user, market, trade, session),
            ("AVAX", "USDT", weights_Strategy1[3], user, market, trade, session),
            ("DOGE", "USDT", weights_Strategy1[4], user, market, trade, session)
        )

        LR_instance = Strategy1(name="Single Worker")
        while True:
            for args in args_set:
                await LR_instance.LR_Trend_2hour(*args)

def run_lr_trend_2hour(weights: tuple[float], multiprocess_mode: bool = False):
    if multiprocess_mode:
        fn = _multi_process_run_lr_trend_2hr
    else:
        fn = _single_thread_run_lr_thread_2hr

    # while True:

    loop = asyncio.get_event_loop()
    asyncio.run(fn(weights))

async def main():
    weights_Strategy1 = weighting([2, 2, 1]) # SOL, SUKU, GST, AVAX, DOGE
    weights_MC_KC = weighting([3, 3, 1]) # ETH, SOL, BTC                    PEPE, AIOZ, SHIB, ICP (5, 4, 2, 2)
    log_remover_task = asyncio.create_task(log_remover('.', 'Live_logging', 10239))
    lr_trend_task = asyncio.create_task(_multi_process_run_lr_trend_2hr(weights_Strategy1, weights_MC_KC))

    await asyncio.gather(log_remover_task, lr_trend_task)

def run_with_profiling():
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
    

if __name__ == '__main__':
    # run_with_profiling()
    asyncio.run(main())