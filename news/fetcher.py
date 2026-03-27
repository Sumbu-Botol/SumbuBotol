"""
News Fetcher
============
Fetch berita kripto & global dari RSS feeds.
- Regex-based RSS parsing (handles CDATA, Bloomberg, FT)
- Optional Gemini AI: terjemah judul ke Indonesia + 3 bullet Bloomberg-style
- Poll setiap 30 detik, push real-time via WebSocket
"""
import asyncio
import httpx
import re
import json
import hashlib
import os
from datetime import datetime, timezone
from typing import Optional

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── RSS Sources ───────────────────────────────────────────────────────────────

CRYPTO_SOURCES = [
    {"name": "CoinDesk",      "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "CoinTelegraph", "url": "https://cointelegraph.com/rss"},
    {"name": "Decrypt",       "url": "https://decrypt.co/feed"},
    {"name": "The Block",     "url": "https://www.theblock.co/rss.xml"},
]

GLOBAL_SOURCES = [
    {"name": "Bloomberg", "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"name": "Bloomberg", "url": "https://feeds.bloomberg.com/economics/news.rss"},
    {"name": "WSJ",       "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
    {"name": "WSJ",       "url": "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml"},
    {"name": "WSJ",       "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml"},
    {"name": "Financial Times", "url": "https://www.ft.com/rss/home"},
    {"name": "CNBC",      "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"name": "CNBC",      "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html"},
    {"name": "Reuters",   "url": "https://www.reutersagency.com/feed/?best-topics=business-finance"},
    {"name": "Reuters",   "url": "https://www.reutersagency.com/feed/?best-topics=tech"},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}

# ── Category Detection (persis seperti repo asli) ─────────────────────────────

GLOBAL_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Ekonomi AS":    ["federal reserve", "fed rate", "us economy", "us gdp", "us inflation",
                      "treasury yield", "american economy", "united states economy", "wall street",
                      "s&p 500", "nasdaq", "dow jones", "us jobs", "nonfarm payroll"],
    "China":         ["china", "chinese economy", "beijing", "xi jinping", "yuan", "pboc",
                      "hong kong", "shenzhen", "shanghai composite"],
    "Eropa":         ["european central bank", "ecb", "euro zone", "eurozone", "germany gdp",
                      "france economy", "uk economy", "bank of england", "boe", "brexit"],
    "Ekonomi Global":["imf", "world bank", "trade war", "tariff", "geopolitical", "g7", "g20",
                      "global trade", "global growth", "world economy"],
    "Energi":        ["oil price", "crude oil", "opec", "petroleum", "brent crude", "wti crude",
                      "natural gas price", "energy market"],
    "Komoditas":     ["gold price", "copper price", "commodities market", "metals", "iron ore",
                      "wheat price", "agricultural"],
    "Pasar Global":  ["stock market", "equities", "market rally", "market selloff", "bull market",
                      "bear market", "volatility", "risk-off", "risk-on"],
}

CRYPTO_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Bitcoin":        ["bitcoin", "btc", "satoshi", "halving"],
    "Ethereum":       ["ethereum", "eth", "vitalik", "eip", "merge"],
    "DeFi":           ["defi", "decentralized finance", "tvl", "liquidity pool", "yield farming",
                       "amm", "uniswap", "aave", "compound"],
    "NFT":            ["nft", "non-fungible", "opensea", "collectible"],
    "Regulasi Kripto":["sec", "regulation", "lawsuit", "ban", "legal", "congress", "senate",
                       "cftc", "compliance"],
    "Mining":         ["mining", "hashrate", "miner", "asic", "proof of work"],
    "Altcoin":        ["altcoin", "solana", "sol", "bnb", "xrp", "cardano", "ada", "polygon",
                       "matic", "avalanche", "avax", "chainlink", "link"],
}

def detect_global_category(title: str, description: str) -> str:
    text = (title + " " + description).lower()
    for category, keywords in GLOBAL_CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return "Global"

def detect_crypto_category(title: str, description: str) -> str:
    text = (title + " " + description).lower()
    for category, keywords in CRYPTO_CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return "Pasar"


class NewsFetcher:
    def __init__(self):
        self._crypto_articles: list[dict] = []
        self._global_articles: list[dict] = []
        self._seen_hashes: set  = set()
        self._callbacks: list   = []

    def on_new_article(self, callback):
        self._callbacks.append(callback)

    async def start(self, interval: int = 30):
        print(f"[News] Fetcher dimulai, poll setiap {interval}s")
        if GEMINI_API_KEY:
            print("[News] Gemini AI aktif — judul akan diterjemahkan + ringkasan Bloomberg")
        else:
            print("[News] Gemini tidak dikonfigurasi — tampilkan teks RSS mentah")
        while True:
            try:
                await self._fetch_all()
            except Exception as e:
                print(f"[News] _fetch_all error: {e}")
            await asyncio.sleep(interval)

    # ── Fetch cycle ───────────────────────────────────────────────────────────

    async def _fetch_all(self):
        crypto_tasks = [self._fetch_source(s, "crypto") for s in CRYPTO_SOURCES]
        global_tasks = [self._fetch_source(s, "global") for s in GLOBAL_SOURCES]
        results = await asyncio.gather(*(crypto_tasks + global_tasks), return_exceptions=True)

        new_crypto = []
        new_global = []
        for res in results:
            if isinstance(res, list):
                for a in res:
                    if a["category"] == "crypto":
                        new_crypto.append(a)
                    else:
                        new_global.append(a)

        if not new_crypto and not new_global:
            return

        print(f"[News] {len(new_crypto)} kripto baru, {len(new_global)} global baru")

        # AI process jika Gemini tersedia
        if GEMINI_API_KEY:
            if new_crypto:
                new_crypto = await _ai_process(new_crypto, "crypto")
            if new_global:
                new_global = await _ai_process(new_global, "global")

        # Masukkan ke cache, urutkan newest first
        for a in new_crypto:
            self._crypto_articles.insert(0, a)
        for a in new_global:
            self._global_articles.insert(0, a)

        self._crypto_articles.sort(key=lambda x: x["published_ts"], reverse=True)
        self._global_articles.sort(key=lambda x: x["published_ts"], reverse=True)

        self._crypto_articles = self._crypto_articles[:200]
        self._global_articles = self._global_articles[:200]

        # Broadcast ke WebSocket clients
        all_new = sorted(new_crypto + new_global, key=lambda x: x["published_ts"], reverse=True)
        for a in all_new:
            for cb in self._callbacks:
                try:
                    await cb(a)
                except Exception:
                    pass

    async def _fetch_source(self, source: dict, category: str) -> list[dict]:
        """Fetch satu RSS source, return list artikel BARU (belum di cache)."""
        try:
            async with httpx.AsyncClient(timeout=8, headers=HEADERS, follow_redirects=True) as client:
                r = await client.get(source["url"])
                if r.status_code != 200:
                    print(f"[News] HTTP {r.status_code} dari {source['name']}")
                    return []
                articles = _parse_rss(r.text, source["name"], category)
                new = []
                for a in articles:
                    h = _hash(a["url"])
                    if h not in self._seen_hashes:
                        self._seen_hashes.add(h)
                        a["id"] = h
                        new.append(a)
                if new:
                    print(f"[News] OK {source['name']}: +{len(new)} artikel")
                return new
        except Exception as e:
            print(f"[News] GAGAL {source['name']}: {type(e).__name__}: {e}")
            return []

    # ── Public getters ────────────────────────────────────────────────────────

    def get_crypto(self, limit: int = 50) -> list[dict]:
        return self._crypto_articles[:limit]

    def get_global(self, limit: int = 50) -> list[dict]:
        return self._global_articles[:limit]

    def get_latest(self, limit: int = 30) -> list[dict]:
        combined = self._crypto_articles + self._global_articles
        combined.sort(key=lambda x: x["published_ts"], reverse=True)
        return combined[:limit]


# ── AI Processing (Gemini) ────────────────────────────────────────────────────

async def _ai_process(articles: list[dict], category: str) -> list[dict]:
    """Terjemah judul ke Indonesia + buat 3 bullet Bloomberg-style via Gemini."""
    if not articles:
        return articles

    input_text = "\n---\n".join(
        f"[{i}] TITLE: {a['title']}\nDESC: {a['summary'][:400]}"
        for i, a in enumerate(articles)
    )

    if category == "crypto":
        prompt = f"""Kamu adalah EDITOR KEPALA di CoinDesk/The Block versi Indonesia, standar Bloomberg Terminal.

STANDAR JUDUL:
- Wajib ada angka (harga, %, volume) jika tersedia
- Kata kerja spesifik: "melonjak", "anjlok", "memangkas", bukan "mengalami"
- Pertahankan istilah: BTC, ETH, DeFi, NFT, TVL, staking, halving

Proses {len(articles)} berita kripto secara BATCH.
Untuk SETIAP berita:
1. Terjemahkan judul ke Bahasa Indonesia yang INFORMATIF dan PRESISI
2. TEPAT 3 poin ringkasan. Format: • Fakta + angka + dampak (1-2 kalimat)

Output JSON array TANPA teks lain:
[{{"idx":0,"title":"judul","summary":"• Poin 1\\n• Poin 2\\n• Poin 3"}},...]

Berita:
{input_text}"""
    else:
        prompt = f"""Kamu adalah EDITOR KEPALA Bloomberg/Reuters versi Indonesia.

STANDAR JUDUL:
- Wajib ada angka jika tersedia. Subjek + kata kerja aktif spesifik.
- Pertahankan nama: S&P 500, Nasdaq, Fed, ECB, BoJ, FTSE 100

Proses {len(articles)} berita ekonomi global secara BATCH.
Untuk SETIAP berita:
1. Terjemahkan judul ke Bahasa Indonesia yang INFORMATIF dan PRESISI
2. TEPAT 3 poin ringkasan. Format: • Fakta + angka + dampak (1-2 kalimat)

Output JSON array TANPA teks lain:
[{{"idx":0,"title":"judul","summary":"• Poin 1\\n• Poin 2\\n• Poin 3"}},...]

Berita:
{input_text}"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                headers={
                    "Authorization": f"Bearer {GEMINI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gemini-2.5-flash",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 350 * len(articles),
                },
            )
            if r.status_code != 200:
                print(f"[News] Gemini HTTP {r.status_code}: {r.text[:200]}")
                return articles

            data   = r.json()
            raw    = data["choices"][0]["message"]["content"].strip()
            clean  = re.sub(r'```json\n?', '', raw).replace('```', '').strip()
            parsed = json.loads(clean)

            for item in parsed:
                idx = item.get("idx", -1)
                if 0 <= idx < len(articles):
                    articles[idx]["title"]   = item["title"]
                    articles[idx]["summary"] = item["summary"]

            print(f"[News] Gemini OK — {len(articles)} {category} diproses")
    except Exception as e:
        print(f"[News] Gemini error: {e}")

    return articles


# ── RSS Parsing (regex, handles CDATA) ───────────────────────────────────────

def _parse_rss(xml_text: str, source_name: str, category: str) -> list[dict]:
    articles = []
    _item  = re.compile(r'<item>([\s\S]*?)</item>')
    _title = re.compile(r'<title[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</title>')
    _link  = re.compile(r'<link[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</link>')
    _guid  = re.compile(r'<guid[^>]*isPermaLink="true"[^>]*>([\s\S]*?)</guid>')
    _desc  = re.compile(r'<description[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</description>')
    _date  = re.compile(r'<pubDate[^>]*>([\s\S]*?)</pubDate>')

    for m in _item.finditer(xml_text):
        item  = m.group(1)
        tm    = _title.search(item)
        lm    = _link.search(item) or _guid.search(item)
        dm    = _desc.search(item)
        pm    = _date.search(item)

        if not tm or not lm:
            continue

        title = tm.group(1).strip()
        url   = lm.group(1).strip()
        if not url.startswith("http"):
            continue

        desc = ""
        if dm:
            desc = re.sub(r'<[^>]+>', '', dm.group(1)).strip()[:800]

        pub = _parse_date(pm.group(1).strip() if pm else None)
        if category == "global":
            sub_cat = detect_global_category(title, desc)
        else:
            sub_cat = detect_crypto_category(title, desc)
        articles.append({
            "title":        title,
            "url":          url,
            "summary":      desc,
            "source":       source_name,
            "category":     category,
            "sub_category": sub_cat,
            "published":    pub.isoformat() if pub else datetime.now(timezone.utc).isoformat(),
            "published_ts": pub.timestamp() if pub else datetime.now(timezone.utc).timestamp(),
        })
        if len(articles) >= 20:
            break

    return articles


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]
