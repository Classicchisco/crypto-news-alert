import feedparser
import hashlib
import asyncio
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
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

HIGH_IMPACT = ["etf", "sec", "regulation", "ban", "hack", "exploit", "lawsuit", "approval", "blackrock", "fidelity"]
MEDIUM_IMPACT = ["listing", "partnership", "upgrade", "mainnet", "adoption", "whale", "binance"]

WAT = pytz.timezone("Africa/Lagos")

bot = telegram.Bot(token=TELEGRAM_TOKEN)

# ========================= DATABASE =========================
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS seen_news (
    id TEXT PRIMARY KEY,
    title TEXT,
    link TEXT,
    source TEXT,
    impact TEXT,
    signal_text TEXT DEFAULT '',
    added_at TEXT
)
""")
conn.commit()

# safe migration
try:
    cursor.execute("ALTER TABLE seen_news ADD COLUMN signal_text TEXT DEFAULT ''")
    conn.commit()
except:
    pass

# ========================= HELPERS =========================
def hash_id(text):
    return hashlib.md5(text.encode()).hexdigest()

def normalize(t):
    return " ".join(t.lower().split())

# ========================= INTELLIGENCE =========================
def impact_class(title):
    t = title.lower()
    if any(k in t for k in HIGH_IMPACT):
        return "HIGH", "high"
    if any(k in t for k in MEDIUM_IMPACT):
        return "MEDIUM", "medium"
    return "LOW", "low"

def score(title, iclass):
    base = 50
    if iclass == "high":
        base += 30
    elif iclass == "medium":
        base += 15
    else:
        base -= 10
    return min(100, max(0, base))

def signal(title):
    t = title.lower()
    if any(x in t for x in ["etf", "approval", "adoption", "partnership"]):
        return "📈 LONG"
    if any(x in t for x in ["hack", "exploit", "ban", "sec"]):
        return "📉 SHORT"
    return "⚖️ NEUTRAL"

def entry_mock():
    price = 60000
    return f"${price*0.99:,.0f} - ${price*1.01:,.0f}"

# ========================= STORE =========================
async def process(title, link, source):
    impact_text, iclass = impact_class(title)
    sig = signal(title)
    sc = score(title, iclass)

    text = f"""
{impact_text} • {title}

📊 Signal: {sig}
🔥 Strength: {sc}/100
🎯 Entry: {entry_mock()}

🔗 {link}
"""

    cursor.execute("""
    INSERT OR REPLACE INTO seen_news
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        hash_id(title),
        title,
        link,
        source,
        impact_text,
        text,
        datetime.now().isoformat()
    ))
    conn.commit()

    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
    except:
        pass

# ========================= FETCH =========================
async def fetch_news():
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)

        for e in feed.entries[:15]:
            title = e.get("title", "")
            link = e.get("link", "")

            if not title:
                continue

            cursor.execute("SELECT id FROM seen_news WHERE id=?", (hash_id(title),))
            if cursor.fetchone():
                continue

            await process(title, link, url)

# ========================= DASHBOARD DATA API (REALTIME) =========================
@app.get("/api/news")
async def api_news():
    cursor.execute("""
    SELECT signal_text, added_at
    FROM seen_news
    ORDER BY added_at DESC
    LIMIT 30
    """)
    rows = cursor.fetchall()

    return JSONResponse([
        {"signal": r[0], "time": r[1]} for r in rows
    ])

# ========================= TEST ENDPOINT =========================
@app.get("/test")
async def test():
    await fetch_news()
    return {"status": "test fetch triggered"}

# ========================= DASHBOARD (TRADINGVIEW STYLE + LIVE) =========================
@app.get("/", response_class=HTMLResponse)
async def home():

    return HTMLResponse("""
<html>
<head>
<title>Crypto Intelligence Terminal</title>

<style>
body {
    margin:0;
    font-family: Arial;
    background:#0b0f14;
    color:#00ff99;
}

.header {
    padding:15px;
    font-size:20px;
    background:#111;
    border-bottom:1px solid #222;
}

.container {
    padding:20px;
    display:flex;
    flex-direction:column;
    gap:15px;
}

.card {
    background:#111;
    border-left:4px solid #00ff99;
    padding:15px;
    border-radius:10px;
    white-space:pre-wrap;
    box-shadow:0 0 10px rgba(0,255,153,0.1);
}

.time {
    font-size:11px;
    color:#777;
}

</style>
</head>

<body>

<div class="header">
📊 Crypto Intelligence Terminal (Live)
</div>

<div class="container" id="feed">
Loading...
</div>

<script>

async function loadData(){
    const res = await fetch('/api/news');
    const data = await res.json();

    let html = "";

    data.forEach(item => {
        html += `
        <div class="card">
            <div class="time">${item.time}</div>
            ${item.signal}
        </div>
        `;
    });

    document.getElementById("feed").innerHTML = html;
}

loadData();
setInterval(loadData, 5000);

</script>

</body>
</html>
""")

# ========================= SCHEDULER =========================
scheduler = AsyncIOScheduler(timezone=WAT)
scheduler.add_job(fetch_news, "interval", minutes=5)
scheduler.start()

print("🚀 LIVE TRADINGVIEW TERMINAL RUNNING")