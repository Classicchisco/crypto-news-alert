import feedparser
import hashlib
import asyncio
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import sqlite3
import telegram
import pytz
import requests

app = FastAPI(title="Crypto Intelligence Engine")

# ========================= CONFIG =========================
TELEGRAM_TOKEN = "YOUR_TELEGRAM_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

HIGH_PROBABILITY_ONLY = True

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cryptoslate.com/feed/",
    "https://decrypt.co/feed",
    "https://thedefiant.io/feed/",
]

HIGH_IMPACT = ["etf", "sec", "regulation", "ban", "hack", "exploit", "lawsuit", "approval", "rejected", "blackrock", "fidelity", "gary gensler"]
MEDIUM_IMPACT = ["listing", "partnership", "upgrade", "mainnet", "adoption", "institutional", "whale", "binance"]

WAT = pytz.timezone("Africa/Lagos")

bot = telegram.Bot(token=TELEGRAM_TOKEN)

# ========================= DB =========================
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS seen_news (
    id TEXT PRIMARY KEY,
    title TEXT,
    link TEXT,
    source TEXT,
    impact TEXT,
    added_at TEXT
)
""")
conn.commit()

# ========================= HELPERS =========================
def hash_id(text):
    return hashlib.md5(text.encode()).hexdigest()

def normalize(t):
    return " ".join(t.lower().split())

def get_btc_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        return float(requests.get(url, timeout=5).json()["bitcoin"]["usd"])
    except:
        return None

# ========================= INTELLIGENCE =========================
def impact_class(title):
    t = title.lower()
    if any(k in t for k in HIGH_IMPACT):
        return "🔴 High Impact", "high"
    if any(k in t for k in MEDIUM_IMPACT):
        return "🟡 Medium Impact", "medium"
    return "🟢 Low Impact", "low"

def impact_score(title, iclass):
    score = 10
    if iclass == "high":
        score += 60
    elif iclass == "medium":
        score += 35
    else:
        score += 10

    boosts = {
        "etf": 20,
        "sec": 15,
        "hack": 25,
        "exploit": 25,
        "approval": 20,
        "ban": 20,
        "blackrock": 20,
        "fidelity": 15,
        "whale": 10,
        "binance": 10
    }

    t = title.lower()
    for k, v in boosts.items():
        if k in t:
            score += v

    return min(score, 100)

def trading_signal(title, iclass):
    t = title.lower()
    score = 50

    bullish = ["etf", "adoption", "approval", "partnership", "upgrade", "institutional"]
    bearish = ["hack", "exploit", "ban", "lawsuit", "sec", "rejection"]

    for b in bullish:
        if b in t:
            score += 15

    for b in bearish:
        if b in t:
            score -= 20

    if iclass == "high":
        score += 20
    elif iclass == "medium":
        score += 10
    else:
        score -= 5

    if score >= 70:
        return "📈 LONG", min(100, score)
    elif score <= 40:
        return "📉 SHORT", max(0, score)
    else:
        return "⚖️ NEUTRAL", score

def win_rate_score(iclass, signal, confidence):
    base = confidence

    if iclass == "high":
        base += 10
    elif iclass == "medium":
        base += 5
    else:
        base -= 5

    if signal == "📈 LONG":
        base += 3
    elif signal == "📉 SHORT":
        base += 3

    return max(0, min(100, base))

def entry_engine(price, signal):
    if not price:
        return "N/A", "N/A", "Low"

    if signal == "📈 LONG":
        return f"${price*0.995:,.0f} - ${price*1.005:,.0f}", f"${price*0.98:,.0f}", "Medium"
    if signal == "📉 SHORT":
        return f"${price*1.005:,.0f} - ${price*0.995:,.0f}", f"${price*1.02:,.0f}", "Medium"

    return "Wait", "N/A", "Low"

def commentary(title, iclass):
    t = title.lower()

    if "etf" in t:
        return "ETF narrative impacting liquidity expectations."
    if "sec" in t:
        return "Regulatory pressure increasing uncertainty."
    if "hack" in t:
        return "Security event → risk-off likely."
    if iclass == "high":
        return "Strong catalyst → volatility expansion."
    return "Low impact → muted reaction."

# ========================= SEND =========================
async def send_to_telegram(title, link, source, impact):
    iclass = impact.split()[1] if len(impact.split()) > 1 else "low"

    btc_before = get_btc_price()

    signal, confidence = trading_signal(title, iclass)
    win_rate = win_rate_score(iclass, signal, confidence)

    # HIGH PROBABILITY FILTER
    if HIGH_PROBABILITY_ONLY and win_rate < 75:
        print(f"Skipped: {title[:40]} (WR {win_rate})")
        return

    entry, invalidation, risk = entry_engine(btc_before, signal)

    msg = f"{impact.split()[0]} {title}\n\n"
    msg += f"🧠 {commentary(title, iclass)}\n"
    msg += f"📊 Impact: {impact_score(title, iclass)}/100\n"
    msg += f"📡 Signal: {signal} ({confidence}/100)\n"
    msg += f"📊 Win Rate: {win_rate}%\n"
    msg += f"\n🎯 Entry: {entry}\n"
    msg += f"🛑 Invalidation: {invalidation}\n"
    msg += f"⚠️ Risk: {risk}\n"
    msg += f"\n🔗 {link}"

    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)

    await asyncio.sleep(30)

    btc_after = get_btc_price()
    if btc_before and btc_after:
        change = ((btc_after - btc_before) / btc_before) * 100
        if abs(change) >= 2:
            direction = "📈" if change > 0 else "📉"
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"{direction} BTC moved {change:.2f}% after news"
            )

# ========================= FETCH =========================
async def fetch_news():
    seen = {}

    for url in RSS_FEEDS:
        feed = feedparser.parse(url)

        for e in feed.entries[:25]:
            title = e.get("title", "")
            link = e.get("link", "")

            if not title or not link:
                continue

            norm = normalize(title)

            if norm in seen:
                continue

            news_id = hash_id(title)

            cursor.execute("SELECT id FROM seen_news WHERE id=?", (news_id,))
            if cursor.fetchone():
                continue

            seen[norm] = True

            impact_text, _ = impact_class(title)

            cursor.execute("""
            INSERT INTO seen_news VALUES (?, ?, ?, ?, ?, ?)
            """, (news_id, title, link, url, impact_text, datetime.now().isoformat()))
            conn.commit()

            await send_to_telegram(title, link, url, impact_text)

# ========================= DASHBOARD =========================
@app.get("/", response_class=HTMLResponse)
async def home():
    cursor.execute("SELECT title, link, impact FROM seen_news ORDER BY added_at DESC LIMIT 50")
    rows = cursor.fetchall()

    html = """
    <html>
    <body style="background:#0b0f14;color:#00ff99;font-family:Arial;padding:20px;">
    <h1>Crypto Intelligence Dashboard</h1>
    <a href="/fetch-now" style="background:#00ff99;color:black;padding:10px;text-decoration:none;">Manual Fetch</a>
    """

    for r in rows:
        html += f"<p>{r[2]} - <a href='{r[1]}' style='color:#4da3ff'>{r[0]}</a></p>"

    html += "</body></html>"
    return HTMLResponse(html)

@app.get("/fetch-now")
async def manual():
    asyncio.create_task(fetch_news())
    return {"status": "running"}

# ========================= SCHEDULER =========================
scheduler = AsyncIOScheduler(timezone=WAT)

times = ["08:00","10:00","12:00","14:00","16:00","18:00","20:00","21:00","23:00"]

for t in times:
    scheduler.add_job(fetch_news, "cron",
                      hour=t.split(":")[0],
                      minute=t.split(":")[1])

scheduler.start()

print("🚀 AI Crypto Signal Engine Running")