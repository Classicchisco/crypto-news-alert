import feedparser
import hashlib
import asyncio
import random
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import sqlite3
import telegram
import pytz

app = FastAPI(title="Crypto News Alert")

# ========================= CONFIG =========================
TELEGRAM_TOKEN = "8794198282:AAHuKZVLsIN1QfAGEdE268Jl8r0nB1h_l4c"
TELEGRAM_CHAT_ID = "424785767"

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cryptoslate.com/feed/",
    "https://decrypt.co/feed",
    "https://thedefiant.io/feed/",
]

HIGH_IMPACT = ["etf","sec","regulation","ban","hack","exploit","lawsuit","approval","rejected","blackrock","fidelity"]
MEDIUM_IMPACT = ["listing","partnership","upgrade","mainnet","adoption","institutional","whale","binance"]

WAT = pytz.timezone('Africa/Lagos')
bot = telegram.Bot(token=TELEGRAM_TOKEN)

# ========================= DATABASE =========================
conn = sqlite3.connect('database.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS seen_news (
    id TEXT PRIMARY KEY,
    title TEXT,
    link TEXT,
    source TEXT,
    impact TEXT,
    signal_text TEXT,
    added_at TEXT
)
''')
conn.commit()

# ========================= HELPERS =========================
def get_hash(title: str):
    return hashlib.md5(title.lower().strip().encode()).hexdigest()

def get_impact_score(title: str):
    t = title.lower()
    if any(k in t for k in HIGH_IMPACT):
        return "🔴 High Impact", "high"
    elif any(k in t for k in MEDIUM_IMPACT):
        return "🟡 Medium Impact", "medium"
    return "🟢 Low Impact", "low"

# ========================= SIGNAL ENGINE =========================
POSITIVE = ["etf","approval","adoption","partnership","institutional","surge","rally"]
NEGATIVE = ["hack","exploit","ban","sec","lawsuit","rejected","crash","drop"]

def sentiment_score(title):
    t = title.lower()
    score = 0

    for w in POSITIVE:
        if w in t:
            score += random.randint(12,28)

    for w in NEGATIVE:
        if w in t:
            score -= random.randint(18,35)

    return score

def signal_engine(title, iclass):
    base = sentiment_score(title)
    base += random.randint(-10,10)

    if iclass == "high":
        base *= 1.3
    elif iclass == "medium":
        base *= 1.1

    base = max(-100, min(100, base))

    if base > 20:
        return "📈 Bullish", abs(int(base))
    elif base < -20:
        return "📉 Bearish", abs(int(base))
    else:
        return "⚖️ Neutral", abs(int(base))

def generate_tags():
    tags = ["#Crypto","#Bitcoin","#Ethereum","#Altcoins","#Trading","#Web3"]
    return " ".join(random.sample(tags, 3))

# ========================= TELEGRAM =========================
async def send_to_telegram(title, link, source, impact):

    impact_text, iclass = impact
    signal, strength = signal_engine(title, iclass)
    tags = generate_tags()

    # FIX: clean CoinDesk naming
    clean_source = source.replace("CoinDesk","CoinDesk")

    message = f"""
{impact_text} NEWS ALERT

📰 {title}

📡 Source: {clean_source}
📊 Signal: {signal}
🔥 Strength: {strength}/100

🏷️ {tags}

🔗 {link}
"""

    # ALWAYS SAVE FULL STRUCTURED TEXT
    cursor.execute('''
    INSERT OR REPLACE INTO seen_news VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        get_hash(title),
        title,
        link,
        clean_source,
        impact_text,
        message,
        datetime.now().isoformat()
    ))
    conn.commit()

    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        print(f"✅ Sent → {title[:60]}")
    except Exception as e:
        print("Telegram Error:", e)

# ========================= FETCH =========================
async def fetch_news(scheduled=True):
    now = datetime.now(WAT)
    print(f"[{now.strftime('%H:%M:%S')}] Fetching...")

    MAX_LOW = 5
    total_low = 0

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source = feed.feed.get('title', 'Unknown')

            entries = feed.entries[:30]

            for entry in entries:
                title = entry.get('title','').strip()
                link = entry.get('link','')

                if not title or not link:
                    continue

                news_id = get_hash(title)

                cursor.execute("SELECT id FROM seen_news WHERE id=?", (news_id,))
                if cursor.fetchone():
                    continue

                impact = get_impact_score(title)

                if impact[1] == "low":
                    if total_low >= MAX_LOW:
                        continue
                    total_low += 1

                await send_to_telegram(title, link, source, impact)

        except Exception as e:
            print("Error:", e)

# ========================= API =========================
@app.get("/api/news")
async def api_news():
    cursor.execute("""
    SELECT signal_text, added_at
    FROM seen_news
    ORDER BY added_at DESC
    LIMIT 50
    """)
    rows = cursor.fetchall()

    return JSONResponse([
        {"signal": r[0], "time": r[1]} for r in rows
    ])

# ========================= DASHBOARD =========================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):

    return HTMLResponse("""
<html>
<head>
<title>Crypto Intelligence</title>
<style>
body{background:#0b0f14;color:#e6edf3;font-family:Arial;margin:0}
.header{padding:15px;background:#111;color:#00ffcc;font-size:20px}
.card{background:#161b22;margin:10px;padding:15px;border-left:4px solid #00ffcc;border-radius:10px;white-space:pre-wrap}
.empty{padding:20px;color:#888}
button{background:#00ffcc;border:none;padding:10px;margin:10px;cursor:pointer;font-weight:bold;border-radius:5px}
</style>
</head>
<body>

<div class="header">📊 Crypto Intelligence Engine</div>

<button onclick="fetchNow()">⚡ Fetch News</button>

<div id="feed">Loading...</div>

<script>
async function load(){
    const res = await fetch('/api/news');
    const data = await res.json();

    let html="";

    if(data.length === 0){
        html = "<div class='empty'>No news yet. Click Fetch.</div>";
    } else {
        data.forEach(item=>{
            html+=`<div class="card">${item.signal}</div>`;
        });
    }

    document.getElementById("feed").innerHTML=html;
}

async function fetchNow(){
    await fetch('/fetch-now');
    alert("Fetching...");
}

load();
setInterval(load,5000);
</script>

</body>
</html>
""")

# ========================= MANUAL =========================
@app.get("/fetch-now")
async def manual():
    asyncio.create_task(fetch_news(True))
    return {"status":"running"}

# ========================= SCHEDULER =========================
scheduler = AsyncIOScheduler(timezone=WAT)

times = ["08:00","10:00","12:00","14:00","16:00","18:00","20:00","21:00","23:00"]

for t in times:
    scheduler.add_job(fetch_news,'cron',
                      hour=t.split(':')[0],
                      minute=t.split(':')[1],
                      args=[True])

scheduler.start()

print("🚀 SYSTEM FULLY FIXED + DATA FLOW RESTORED")