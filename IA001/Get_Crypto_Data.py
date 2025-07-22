import requests
import json
from datetime import datetime
import os

PAIRS = [
    "BTC/USDT", "BCH/USDT", "ETH/USDT", "LINK/USDT", "LTC/USDT", "SOL/USDT",
    "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOT/USDT", "ETC/USDT", "ALGO/USDT", "LUNA/USDT"
]

def fetch_crypto(pair: str, cmc_api_key=None):
    symbol = pair.replace('/', '').upper()
    filename = f"{symbol}.json"
    # Remove the old file if it exists
    if os.path.exists(filename):
        os.remove(filename)
    interval = '5m'
    limit = 288  # 24 hours * 12 (5min per hour)
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to fetch OHLCV for {pair}: {e}")
        return False

    # Downsample: take every 4th entry to get 20-minute intervals
    ohlcv = []
    for i, entry in enumerate(data):
        if i % 4 == 0:
            ohlcv.append({
                'open_time': datetime.fromtimestamp(entry[0] / 1000).strftime('%Y-%m-%dT%H:%M:%S'),
                'open': float(entry[1]),
                'high': float(entry[2]),
                'low': float(entry[3]),
                'close': float(entry[4]),
                'volume': float(entry[5])
            })

    # Remove the last data point if it exists
    if ohlcv:
        ohlcv.pop()

    indicator = 'unknown'
    cmc_price = None
    cmc_percent_change_24h = None

    if cmc_api_key:
        # Use CoinMarketCap API if API key is provided
        cmc_url = f'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest'
        base = pair.split('/')[0]
        quote = pair.split('/')[1]
        params = {'symbol': base, 'convert': quote}
        headers = {'X-CMC_PRO_API_KEY': cmc_api_key}
        try:
            cmc_resp = requests.get(cmc_url, params=params, headers=headers, timeout=30)
            cmc_resp.raise_for_status()
            cmc_data = cmc_resp.json()
            cmc_price = cmc_data['data'][base]['quote'][quote]['price']
            cmc_percent_change_24h = cmc_data['data'][base]['quote'][quote]['percent_change_24h']
            indicator = 'buy' if cmc_percent_change_24h > 1 else 'sell' if cmc_percent_change_24h < -1 else 'hold'
        except Exception as e:
            print(f"[ERROR] Could not fetch CoinMarketCap data for {pair}: {e}")
            return False
    else:
        # Use Binance public API for current price and percent change
        ticker_url = f'https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}'
        try:
            ticker_resp = requests.get(ticker_url, timeout=30)
            ticker_resp.raise_for_status()
            ticker_data = ticker_resp.json()
            cmc_price = float(ticker_data['lastPrice'])
            cmc_percent_change_24h = float(ticker_data['priceChangePercent'])
            indicator = 'buy' if cmc_percent_change_24h > 1 else 'sell' if cmc_percent_change_24h < -1 else 'hold'
        except Exception as e:
            print(f"[ERROR] Could not fetch Binance ticker data for {pair}: {e}")
            return False

    output = {
        'pair': pair,
        'indicator': indicator,
        'price': cmc_price,
        'percent_change_24h': cmc_percent_change_24h,
        'ohlcv': ohlcv
    }

    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"Saved {len(ohlcv)} entries to {filename}")
        return True
    except Exception as e:
        print(f"[ERROR] Could not write file {filename}: {e}")
        return False

def fetch_all_cryptos():
    state_file = "fetch_state.json"
    start_time = datetime.now().isoformat()
    # Write initial state
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump({
            "state": "fetching",
            "start_time": start_time,
            "pairs": PAIRS
        }, f, ensure_ascii=False, indent=2)
    fetched_pairs = []
    for pair in PAIRS:
        success = fetch_crypto(pair)
        if success:
            fetched_pairs.append(pair)
        else:
            print(f"[WARN] Skipped {pair} due to error.")
    end_time = datetime.now().isoformat()
    # Write final state
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump({
            "state": "fetched",
            "start_time": start_time,
            "end_time": end_time,
            "pairs": fetched_pairs
        }, f, ensure_ascii=False, indent=2)

# Example usage:
if __name__ == "__main__":
    fetch_all_cryptos()
