import feedparser
import hashlib
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import sqlite3
import telegram
import pytz

app = FastAPI(title="Crypto News Alert")

# ========================= CONFIG =========================
TELEGRAM_TOKEN = "8794198282:AAHuKZVLsIN1QfAGEdE268Jl8r0nB1h_l4c"           # ← Put your token
TELEGRAM_CHAT_ID = "424785767"       # ← Put your chat ID

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cryptoslate.com/feed/",
    "https://decrypt.co/feed",
    "https://thedefiant.io/feed/",
]

# Impact Keywords
HIGH_IMPACT = ["etf", "sec", "regulation", "ban", "hack", "exploit", "lawsuit", "approval", "rejected", "blackrock", "fidelity", "gary gensler"]
MEDIUM_IMPACT = ["listing", "partnership", "upgrade", "mainnet", "adoption", "institutional", "whale", "binance"]

WAT = pytz.timezone('Africa/Lagos')

def get_impact_score(title: str):
    title_lower = title.lower()
    if any(k in title_lower for k in HIGH_IMPACT):
        return "🔴 High Impact", "high"
    elif any(k in title_lower for k in MEDIUM_IMPACT):
        return "🟡 Medium Impact", "medium"
    else:
        return "🟢 Low Impact", "low"

def extract_coins(title: str):
    coins = []
    t = title.upper()
    if "BTC" in t or "BITCOIN" in t: coins.append("BTC")
    if "ETH" in t or "ETHEREUM" in t: coins.append("ETH")
    if "SOL" in t or "SOLANA" in t: coins.append("SOL")
    if "XRP" in t: coins.append("XRP")
    return " | ".join(coins) if coins else ""

# Database
conn = sqlite3.connect('database.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS seen_news (
        id TEXT PRIMARY KEY,
        title TEXT,
        link TEXT,
        source TEXT,
        impact TEXT,
        added_at TEXT
    )
''')
conn.commit()

bot = telegram.Bot(token=TELEGRAM_TOKEN)

def get_hash(title: str):
    return hashlib.md5(title.lower().strip().encode()).hexdigest()

async def send_to_telegram(title, link, source, impact):
    coins = extract_coins(title)
    impact_emoji = impact.split()[0]
    
    message = f"{impact_emoji} **{title}**\n\n"
    if coins:
        message += f"🪙 {coins}\n"
    message += f"Source: {source}\n🔗 {link}"

    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')
        print(f"✅ Sent {impact} → {title[:65]}...")
    except Exception as e:
        print(f"Telegram Error: {e}")

async def fetch_news(scheduled=True):
    now = datetime.now(WAT)
    print(f"[{now.strftime('%H:%M:%S')} WAT] Fetching news... (Scheduled: {scheduled})")
    
    new_count = 0
    low_impact_sent = 0
    MAX_LOW_IMPACT = 5

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source = feed.feed.get('title', 'Unknown').strip()

            # ====== UPDATED LOGIC START (only change made) ======
            entries = feed.entries[:30]

            high_medium_news = []
            low_news = []

            for entry in entries:
                title = entry.get('title', '').strip()
                link = entry.get('link', '')
                if not title or not link:
                    continue

                news_id = get_hash(title)

                cursor.execute("SELECT id FROM seen_news WHERE id=?", (news_id,))
                if cursor.fetchone():
                    continue

                impact_text, impact_class = get_impact_score(title)

                item = (entry, title, link, news_id, impact_text, impact_class)

                if impact_class in ["high", "medium"]:
                    high_medium_news.append(item)
                else:
                    low_news.append(item)

            # Sort low-impact by recency
            low_news = sorted(
                low_news,
                key=lambda x: x[0].get("published_parsed", (0,)),
                reverse=True
            )

            # Limit low-impact ONLY during scheduled runs
            if scheduled:
                low_news = low_news[:MAX_LOW_IMPACT]

            final_news = high_medium_news + low_news

            for entry, title, link, news_id, impact_text, impact_class in final_news:

                cursor.execute('''
                    INSERT INTO seen_news (id, title, link, source, impact, added_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (news_id, title, link, source, impact_text, datetime.now().isoformat()))
                conn.commit()

                await send_to_telegram(title, link, source, impact_text)
                new_count += 1
            # ====== UPDATED LOGIC END ======

        except Exception as e:
            print(f"Error fetching {feed_url}: {e}")

    print(f"✅ Finished. Sent {new_count} new articles.")

# ====================== ROUTES ======================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    cursor.execute("SELECT title, link, source, impact, added_at FROM seen_news ORDER BY added_at DESC LIMIT 50")
    rows = cursor.fetchall()

    html = """
    <html>
    <head>
        <title>Crypto News Monitor</title>
        <style>
            body { font-family: Arial, sans-serif; background: #0a0a0a; color: #00ff99; padding: 20px; }
            h1 { color: #00ff00; }
            .news { background: #1f1f1f; padding: 15px; margin: 12px 0; border-radius: 8px; }
            .high { border-left: 6px solid #ff4444; }
            .medium { border-left: 6px solid #ffaa00; }
            .low { border-left: 6px solid #44ff88; }
            a { color: #44ddff; }
            .source { color: #bbb; font-size: 0.9em; }
        </style>
    </head>
    <body>
        <h1>📰 Crypto News Aggregator</h1>
        <p><a href="/fetch-now" style="color:yellow; font-weight:bold; font-size:18px;">🔄 Manual Fetch Now</a></p>
        <h2>Latest News</h2>
    """

    if not rows:
        html += "<p>No news yet.</p>"
    else:
        for title, link, source, impact, added_at in rows:
            impact_class = "high" if "High" in impact else "medium" if "Medium" in impact else "low"
            html += f'''
            <div class="news {impact_class}">
                <div class="source">{source} • {added_at[:16]} • {impact}</div>
                <a href="{link}" target="_blank">{title}</a>
            </div>
            '''

    html += "</body></html>"
    return HTMLResponse(content=html)

@app.get("/fetch-now")
async def manual_fetch():
    asyncio.create_task(fetch_news(scheduled=False))
    return {"status": "Manual fetch started..."}

# ====================== SCHEDULER ======================
scheduler = AsyncIOScheduler(timezone=WAT)

# Scheduled times (WAT)
fetch_times = ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00", "21:00", "23:00"]

for t in fetch_times:
    scheduler.add_job(fetch_news, 'cron', hour=t.split(':')[0], minute=t.split(':')[1], 
                      id=f'fetch_{t}', args=[True])

scheduler.start()

print("🚀 Advanced Crypto News System Running with Scheduled Fetch!")
print("Scheduled times (WAT): 8am, 10am, 12pm, 2pm, 4pm, 6pm, 8pm, 9pm, 11pm")
print("Open Dashboard → http://127.0.0.1:8000")