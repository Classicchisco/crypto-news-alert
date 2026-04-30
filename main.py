import feedparser
import hashlib
import asyncio
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
def signal_engine(title, iclass):
    t = title.lower()
    score = 50

    if any(x in t for x in ["etf","approval","adoption","partnership"]):
        score += 15
    if any(x in t for x in ["hack","exploit","ban","sec","lawsuit"]):
        score -= 20

    if iclass == "high":
        score += 15

    if score >= 70:
        return "📈 LONG", score
    elif score <= 40:
        return "📉 SHORT", score
    return "⚖️ NEUTRAL", score

# ========================= TELEGRAM =========================
async def send_to_telegram(title, link, source, impact):
    impact_text, iclass = impact
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
    cursor.execute('''
    INSERT OR REPLACE INTO seen_news VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        get_hash(title),
        title,
        link,
        source,
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

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source = feed.feed.get('title', 'Unknown')

            entries = feed.entries[:30]

            high_medium = []
            low = []

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

                if impact[1] in ["high","medium"]:
                    high_medium.append((title,link,impact))
                else:
                    low.append((entry,title,link,impact))

            low = sorted(low, key=lambda x: x[0].get("published_parsed",(0,)), reverse=True)

            if scheduled:
                low = low[:MAX_LOW]

            final = high_medium + [(t,l,i) for _,t,l,i in low]

            for title, link, impact in final:
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

# ========================= TEST TELEGRAM =========================
@app.get("/test-telegram")
async def test():
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🧪 Telegram working perfectly")
    return {"status":"sent"}

# ========================= DASHBOARD =========================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):

    return HTMLResponse("""
<html>
<head>
<title>Crypto Intelligence</title>
<style>
body{background:#0b0f14;color:#00ff99;font-family:Arial;margin:0}
.header{padding:15px;background:#111}
.card{background:#111;margin:10px;padding:12px;border-left:4px solid #00ff99;border-radius:8px;white-space:pre-wrap}
button{background:#00ff99;border:none;padding:10px;margin:10px;cursor:pointer;font-weight:bold}
</style>
</head>
<body>

<div class="header">📊 Crypto Intelligence Engine</div>

<button onclick="fetchNow()">⚡ Fetch News</button>
<button onclick="testTG()">🧪 Test Telegram</button>

<div id="feed">Loading...</div>

<script>
async function load(){
    const res = await fetch('/api/news');
    const data = await res.json();

    let html="";
    data.forEach(item=>{
        html+=`<div class="card">${item.signal}</div>`;
    });

    document.getElementById("feed").innerHTML=html;
}

async function fetchNow(){
    await fetch('/fetch-now');
    alert("Fetching...");
}

async function testTG(){
    await fetch('/test-telegram');
    alert("Telegram sent");
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
    asyncio.create_task(fetch_news(False))
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

print("🚀 FULL SYSTEM LIVE")