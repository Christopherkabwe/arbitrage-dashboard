import ccxt
import time
import requests
from datetime import datetime, timezone, timedelta
import json
import threading
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import os
import asyncio

# --- Configuration ---
trading_pairs = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
profit_threshold_percent = 0.0
TELEGRAM_BOT_TOKEN = '8147123901***'
TELEGRAM_CHAT_ID = '7779****8'
LOG_FILE = "arbitrage_log.txt"
SENT_ALERTS = set()
DATA_FILE = "arbitrage_data.json"

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
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            old_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        old_data = []

    # Add timestamp to each new opportunity (in UTC)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    for opp in new_opportunities:
        opp["timestamp"] = timestamp

    # Append new opportunities to old data
    combined = old_data + new_opportunities

    # Limit history size (last 100 entries)
    combined = combined[-100:]

    # Save back
    with open(DATA_FILE, "w", encoding="utf-8") as f:
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

def convert_utc_to_zambia_time(utc_str):
    try:
        utc_time = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S UTC")
        gmt2_time = utc_time.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=2)))
        return gmt2_time.strftime("%d %B %Y, %I:%M %p (Zambia Time)").replace("pm", "PM").replace("am", "AM")
    except Exception as e:
        print(f"Time conversion error: {e}")
        return utc_str

@app.get("/")
async def home(request: Request):
    opportunities = []
    try:
        with open(DATA_FILE, "r") as f:
            opportunities = json.load(f)
        opportunities.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    except Exception as e:
        print(f"Error loading arbitrage data: {e}")

    if opportunities:
        last_updated = convert_utc_to_zambia_time(opportunities[0]['timestamp'])
        for opp in opportunities:
            opp["timestamp_zambia"] = convert_utc_to_zambia_time(opp.get("timestamp", ""))
    else:
        last_updated = "No data"

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "opportunities": opportunities,
        "last_updated": last_updated
    })

# --- SSE endpoint to stream live arbitrage data ---
@app.get("/stream")
async def stream():
    async def event_generator():
        while True:
            # Load current data
            try:
                with open(DATA_FILE, "r") as f:
                    data = json.load(f)
            except Exception:
                data = []

            # Yield data as SSE event
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(10)  # update every 10 seconds

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- Scanner running in background thread ---
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

@app.on_event("startup")
async def startup_event():
    start_scanner_thread()
