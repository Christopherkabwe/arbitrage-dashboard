import ccxt
import time
import requests
from datetime import datetime
import json
import asyncio
import threading
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000)


from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from dotenv import load_dotenv
import os

load_dotenv(override=True)  # Loads .env into environment variables

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- Configuration ---
trading_pairs = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT',
    'BNB/USDT', 'XRP/USDT', 'ADA/USDT',
    'DOGE/USDT', 'DOT/USDT', 'AVAX/USDT',
    'MATIC/USDT', 'LTC/USDT', 'TRX/USDT',
    'UNI/USDT','ATOM/USDT','ALGO/USDT', 'VET/USDT'  
]

profit_threshold_percent = 0.0
LOG_FILE = "arbitrage_log.txt"
SENT_ALERTS = set()

# --- Initialize exchanges ---
exchanges = {
    'binance': ccxt.binance(),
    'bybit': ccxt.bybit(),
    'kucoin': ccxt.kucoin(),
    'mexc': ccxt.mexc(),
    'bitget': ccxt.bitget(),
    'okx': ccxt.okx({'options': {'defaultType': 'spot'}}),
}

# --- Utility Functions ---
def send_telegram_message(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
    try:
        response = requests.post(url, data=data)
        if response.status_code != 200:
            print(f"Telegram error: {response.text}")
    except Exception as e:
        print(f"Telegram exception: {e}")

def log_message(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")

def get_prices(symbol):
    prices = {}
    for name, exchange in exchanges.items():
        try:
            ticker = exchange.fetch_ticker(symbol)
            price = ticker['ask'] if ticker.get('ask') else ticker['last']
            prices[name] = price
        except Exception as e:
            print(f"{symbol} - {name} error: {e}")
    return prices

def find_arbitrage(symbol):
    prices = get_prices(symbol)
    if len(prices) < 2:
        return None

    sorted_prices = sorted(prices.items(), key=lambda x: x[1])
    low_ex, low_price = sorted_prices[0]
    high_ex, high_price = sorted_prices[-1]
    profit_percent = ((high_price - low_price) / low_price) * 100

    if profit_percent >= profit_threshold_percent:
        key = f"{symbol}-{low_ex}-{high_ex}-{round(low_price, 2)}-{round(high_price, 2)}"
        if key not in SENT_ALERTS:
            message = (f"🚀 [ARBITRAGE] {symbol} → BUY on {low_ex} @ {low_price:.2f} → "
                       f"SELL on {high_ex} @ {high_price:.2f} | Profit: {profit_percent:.2f}%")
            print(message)
            send_telegram_message(message)
            log_message(message)
            SENT_ALERTS.add(key)
        opportunity = {
            "symbol": symbol,
            "buy_exchange": low_ex,
            "sell_exchange": high_ex,
            "buy_price": round(low_price, 2),
            "sell_price": round(high_price, 2),
            "profit_percent": round(profit_percent, 2),
        }
        return opportunity
    return None

def save_opportunities_to_file(new_opportunities):
    # Load old data
    try:
        with open("arbitrage_data.json", "r", encoding="utf-8") as f:
            old_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        old_data = []

    # Add timestamp to each new opportunity
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    for opp in new_opportunities:
        opp["timestamp"] = timestamp

    # Append new opportunities to old data
    combined = old_data + new_opportunities

    # Limit history size (last 100 entries)
    combined = combined[-100:]

    # Save back
    with open("arbitrage_data.json", "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)

# --- FastAPI app setup ---
app = FastAPI()

# Mount static directory (for favicon or css)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

@app.get("/favicon.ico")
async def favicon():
    file_path = os.path.join("static", "favicon.ico")
    return FileResponse(file_path)

from datetime import datetime, timezone, timedelta

@app.get("/")
async def home(request: Request):
    opportunities = []
    try:
        with open("arbitrage_data.json", "r") as f:
            opportunities = json.load(f)

        # Convert timestamps to datetime objects for sorting
        for opp in opportunities:
            try:
                opp['timestamp_dt'] = datetime.strptime(opp['timestamp'], "%Y-%m-%d %H:%M:%S UTC")
            except Exception:
                opp['timestamp_dt'] = datetime.min  # fallback if parsing fails

        # Sort by timestamp descending, then profit descending
        opportunities.sort(
            key=lambda x: (x['timestamp_dt'], x.get('profit_percent', 0)),
            reverse=True
        )

        # Convert UTC timestamps to Zambia local time strings (CAT, UTC+2)
        for opp in opportunities:
            try:
                utc_time = opp['timestamp_dt'].replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=2)))
                opp['timestamp_zambia'] = utc_time.strftime("%Y-%m-%d %I:%M %p")
            except Exception:
                opp['timestamp_zambia'] = opp['timestamp']  # fallback

    except Exception as e:
        print(f"Error loading arbitrage data: {e}")

    last_updated = opportunities[0]['timestamp_zambia'] if opportunities else "No data"

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "opportunities": opportunities,
        "last_updated": last_updated
    })


# --- Scanner running in a separate thread ---
def scanner_loop():
    while True:
        print("\n--- Scanning for Arbitrage Opportunities ---")
        opportunities = []
        for pair in trading_pairs:
            arb = find_arbitrage(pair)
            if arb:
                opportunities.append(arb)
        if opportunities:
            save_opportunities_to_file(opportunities)
        time.sleep(60)

def start_scanner_thread():
    thread = threading.Thread(target=scanner_loop, daemon=True)
    thread.start()

# Start scanner on FastAPI startup
@app.on_event("startup")
async def startup_event():
    start_scanner_thread()

from fastapi.responses import JSONResponse

@app.get("/api/opportunities")
async def get_opportunities():
    try:
        with open("arbitrage_data.json", "r", encoding="utf-8") as f:
            opportunities = json.load(f)
        return JSONResponse(content={"opportunities": opportunities})
    except Exception as e:
        print(f"Error reading arbitrage data for API: {e}")
        return JSONResponse(content={"opportunities": []})
