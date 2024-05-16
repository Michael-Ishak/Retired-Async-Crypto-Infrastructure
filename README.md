KuCoin Trading Infrastructure (Retired)

Note: This is a retired version of the trading infrastructure. A new, more advanced version is in operation, which is more readable, efficient, and uses multiple languages (mainly Python and C++), databases, and live monitoring. Please message me if you would like to discuss my new codebase.
This repository contains an asynchronous, multithreaded infrastructure designed for trading multiple strategies simultaneously on the KuCoin cryptocurrency exchange. The infrastructure utilises Python's asyncio and aiohttp libraries to handle asynchronous tasks and HTTP requests efficiently.

Features

1. Asynchronous Execution: The infrastructure leverages asyncio to execute multiple trading strategies concurrently, maximizing resource utilization and improving overall performance.
2. Multithreading: Dedicated threads are used for specific tasks, such as logging, data processing, and strategy execution, ensuring smooth operation and preventing bottlenecks.
3. KuCoin Integration: Seamless integration with the KuCoin API, allowing for real-time market data retrieval, order placement, and account management.
4. Strategy Implementation: Includes implementations of various trading strategies, such as momentum based, trend-following and statistical/mathematical strategies.

This is the remnants of my old code, please feel free to use any part of the code as you'd like!


P.S. Some files are missing, such as the send_failed_order file which would send an email about what went wrong to the host if something went wrong. I didn't include this because there was sensitive data within those files. However, templates for these files can be found elsewhere on my github.

If there is anything else you have questions about, feel free to message me!
