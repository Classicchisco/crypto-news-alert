import feedparser
import hashlib
import asyncio
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import sqlite3
import telegram
import pytz

app = FastAPI(title="Crypto Intelligence Engine")

# ========================= CONFIG =========================
TELEGRAM_TOKEN = "8794198282:AAHuKZVLsIN1QfAGEdE268Jl8r0nB1h_l4c"
TELEGRAM_CHAT_ID = "424785767"

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cryptoslate.com/feed/",
    "https://decrypt.co/feed",
]

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
    signal_text TEXT,
    added_at TEXT
)
""")
conn.commit()

# ========================= HELPERS =========================
def hash_id(text):
    return hashlib.md5(text.encode()).hexdigest()

# ========================= IMPACT ENGINE =========================
def impact_class(title):
    t = title.lower()

    high = ["etf", "sec", "hack", "exploit", "ban", "lawsuit", "approval"]
    medium = ["listing", "partnership", "upgrade", "adoption", "whale", "binance"]

    if any(x in t for x in high):
        return "🔴 HIGH", "high"
    if any(x in t for x in medium):
        return "🟡 MEDIUM", "medium"
    return "🟢 LOW", "low"

# ========================= SIGNAL ENGINE =========================
def signal_engine(title, iclass):
    t = title.lower()

    bullish = ["etf", "approval", "adoption", "partnership", "upgrade"]
    bearish = ["hack", "exploit", "ban", "sec", "lawsuit"]

    score = 50

    for b in bullish:
        if b in t:
            score += 15

    for b in bearish:
        if b in t:
            score -= 20

    if iclass == "high":
        score += 15

    if score >= 70:
        return "📈 LONG", score
    elif score <= 40:
        return "📉 SHORT", score
    return "⚖️ NEUTRAL", score

# ========================= TELEGRAM =========================
async def send_telegram(message):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except Exception as e:
        print("Telegram error:", e)

# ========================= ALERT ENGINE =========================
async def send_alert(title, link, source):
    impact_text, iclass = impact_class(title)
    signal, strength = signal_engine(title, iclass)

    message = f"""
{impact_text} NEWS ALERT

📰 {title}

📡 Source: {source}
📊 Signal: {signal}
🔥 Strength: {strength}/100

🔗 {link}
"""

    # SAVE SAME DATA FOR DASHBOARD
    cursor.execute("""
    INSERT OR REPLACE INTO seen_news VALUES (?, ?, ?, ?, ?, ?)
    """, (
        hash_id(title),
        title,
        link,
        source,
        message,
        datetime.now().isoformat()
    ))
    conn.commit()

    await send_telegram(message)

# ========================= FETCH NEWS =========================
async def fetch_news():
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)

        for e in feed.entries[:15]:
            title = e.get("title", "")
            link = e.get("link", "")

            if not title:
                continue

            news_id = hash_id(title)

            cursor.execute("SELECT id FROM seen_news WHERE id=?", (news_id,))
            if cursor.fetchone():
                continue

            await send_alert(title, link, url)

# ========================= MANUAL FETCH ENDPOINT =========================
@app.get("/fetch-now")
async def manual_fetch(background_tasks: BackgroundTasks):
    background_tasks.add_task(fetch_news)
    return {"status": "fetch started"}

# ========================= TELEGRAM TEST =========================
@app.get("/test-telegram")
async def test_telegram(background_tasks: BackgroundTasks):

    msg = """
🧪 TEST ALERT

📈 Signal: LONG
🔥 Strength: 85/100
🎯 Entry: $60,000 - $60,500

✅ System working perfectly
"""

    background_tasks.add_task(send_telegram, msg)
    return {"status": "Telegram test sent"}

# ========================= API FOR DASHBOARD =========================
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

# ========================= DASHBOARD =========================
@app.get("/", response_class=HTMLResponse)
async def home():

    return HTMLResponse("""
<html>
<head>
<title>Crypto Intelligence Terminal</title>

<style>
body {
    margin:0;
    font-family:Arial;
    background:#0b0f14;
    color:#00ff99;
}

.header {
    padding:15px;
    background:#111;
}

.card {
    background:#111;
    margin:10px;
    padding:12px;
    border-left:4px solid #00ff99;
    border-radius:8px;
    white-space:pre-wrap;
}

button {
    background:#00ff99;
    border:none;
    padding:10px;
    margin:10px;
    cursor:pointer;
    font-weight:bold;
    border-radius:5px;
}
</style>
</head>

<body>

<div class="header">
📊 Crypto Intelligence Engine
</div>

<button onclick="fetchNews()">⚡ Fetch News Now</button>
<button onclick="testTG()">🧪 Test Telegram</button>

<div id="feed">Loading...</div>

<script>

async function load(){
    const res = await fetch('/api/news');
    const data = await res.json();

    let html = "";

    data.forEach(item => {
        html += `<div class="card">${item.signal}</div>`;
    });

    document.getElementById("feed").innerHTML = html;
}

async function fetchNews(){
    await fetch('/fetch-now');
    alert("Fetching news...");
}

async function testTG(){
    await fetch('/test-telegram');
    alert("Telegram test sent");
}

load();
setInterval(load, 5000);

</script>

</body>
</html>
""")

# ========================= SCHEDULER =========================
scheduler = AsyncIOScheduler(timezone=WAT)
scheduler.add_job(fetch_news, "interval", minutes=5)
scheduler.start()

print("🚀 FULL INTELLIGENCE SYSTEM RUNNING")