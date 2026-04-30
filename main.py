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
import requests

app = FastAPI(title="Crypto Intelligence Engine")

# ========================= CONFIG =========================
TELEGRAM_TOKEN = "YOUR_TELEGRAM_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cryptoslate.com/feed/",
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

# ========================= TELEGRAM SENDER =========================
async def send_telegram(text):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
    except Exception as e:
        print("Telegram error:", e)

# ========================= TEST TELEGRAM =========================
@app.get("/test-telegram")
async def test_telegram(background_tasks: BackgroundTasks):

    msg = """
🧪 TEST ALERT

📊 Signal: 📈 LONG
🔥 Strength: 87/100
🎯 Entry: $60,000 - $60,500
🛑 Invalidation: $59,200

✅ Telegram system working perfectly
"""

    background_tasks.add_task(send_telegram, msg)

    return {"status": "Telegram test triggered"}

# ========================= FETCH NEWS =========================
async def fetch_news():
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)

        for e in feed.entries[:10]:
            title = e.get("title", "")
            link = e.get("link", "")

            if not title:
                continue

            news_id = hash_id(title)

            cursor.execute("SELECT id FROM seen_news WHERE id=?", (news_id,))
            if cursor.fetchone():
                continue

            signal_text = f"""
📰 {title}

📡 Source: {url}
🔗 {link}
"""

            cursor.execute("""
            INSERT INTO seen_news VALUES (?, ?, ?, ?, ?, ?)
            """, (
                news_id,
                title,
                link,
                url,
                signal_text,
                datetime.now().isoformat()
            ))
            conn.commit()

            await send_telegram(signal_text)

# ========================= DASHBOARD API =========================
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
    font-size:18px;
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
    cursor:pointer;
    margin:10px;
    font-weight:bold;
}
</style>
</head>

<body>

<div class="header">
📊 Crypto Intelligence Live Terminal
</div>

<button onclick="testTG()">🧪 Test Telegram Alert</button>

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

async function testTG(){
    await fetch('/test-telegram');
    alert("Telegram test sent 🚀");
}

load();
setInterval(load, 5000);

</script>

</body>
</html>
""")

# ========================= MANUAL FETCH =========================
@app.get("/fetch-now")
async def manual():
    asyncio.create_task(fetch_news())
    return {"status": "fetch started"}

# ========================= SCHEDULER =========================
scheduler = AsyncIOScheduler(timezone=WAT)
scheduler.add_job(fetch_news, "interval", minutes=5)
scheduler.start()

print("🚀 TEMP SYSTEM RUNNING")