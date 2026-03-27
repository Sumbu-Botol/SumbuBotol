"""
News Fetcher
============
Fetch berita kripto & global dari RSS feeds.
Poll setiap 60 detik - begitu ada artikel baru langsung tersedia.
"""
import asyncio
import httpx
import re
import hashlib
from datetime import datetime, timezone
from typing import Optional

# ── RSS Sources ───────────────────────────────────────────────────────────────

CRYPTO_SOURCES = [
    {"name": "CoinDesk",      "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",  "lang": "en"},
    {"name": "CoinTelegraph", "url": "https://cointelegraph.com/rss",                    "lang": "en"},
    {"name": "Decrypt",       "url": "https://decrypt.co/feed",                          "lang": "en"},
    {"name": "The Block",     "url": "https://www.theblock.co/rss.xml",                  "lang": "en"},
]

GLOBAL_SOURCES = [
    {"name": "Bloomberg Markets",   "url": "https://feeds.bloomberg.com/markets/news.rss",                       "lang": "en"},
    {"name": "Bloomberg Economics", "url": "https://feeds.bloomberg.com/economics/news.rss",                     "lang": "en"},
    {"name": "WSJ Markets",         "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",                      "lang": "en"},
    {"name": "WSJ Business",        "url": "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",                    "lang": "en"},
    {"name": "WSJ World",           "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                        "lang": "en"},
    {"name": "Financial Times",     "url": "https://www.ft.com/rss/home",                                        "lang": "en"},
    {"name": "CNBC",                "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",              "lang": "en"},
    {"name": "CNBC Finance",        "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html",               "lang": "en"},
    {"name": "Reuters Finance",     "url": "https://www.reutersagency.com/feed/?best-topics=business-finance",   "lang": "en"},
    {"name": "Reuters Tech",        "url": "https://www.reutersagency.com/feed/?best-topics=tech",               "lang": "en"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"
}


class NewsFetcher:
    def __init__(self):
        # In-memory cache: url_hash → article
        self._crypto_articles: list[dict] = []
        self._global_articles: list[dict] = []
        self._seen_hashes: set  = set()
        self._new_articles: list[dict] = []   # buffer artikel baru sejak last poll
        self._callbacks: list   = []          # WebSocket callbacks

    def on_new_article(self, callback):
        """Register callback untuk artikel baru."""
        self._callbacks.append(callback)

    async def start(self, interval: int = 60):
        """Mulai polling RSS setiap `interval` detik."""
        print(f"[News] Fetcher dimulai, poll setiap {interval}s")
        while True:
            await self._fetch_all()
            await asyncio.sleep(interval)

    async def _fetch_all(self):
        tasks = (
            [self._fetch_source(s, "crypto") for s in CRYPTO_SOURCES] +
            [self._fetch_source(s, "global") for s in GLOBAL_SOURCES]
        )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        new_count = sum(r for r in results if isinstance(r, int))
        if new_count:
            print(f"[News] {new_count} artikel baru ditemukan")

    async def _fetch_source(self, source: dict, category: str) -> int:
        try:
            async with httpx.AsyncClient(timeout=8, headers=HEADERS, follow_redirects=True) as client:
                r = await client.get(source["url"])
                if r.status_code != 200:
                    print(f"[News] HTTP {r.status_code} dari {source['name']}")
                    return 0
                articles = self._parse_rss(r.text, source["name"], category)
                new = 0
                for a in articles:
                    h = _hash(a["url"])
                    if h not in self._seen_hashes:
                        self._seen_hashes.add(h)
                        a["id"] = h
                        if category == "crypto":
                            self._crypto_articles.insert(0, a)
                        else:
                            self._global_articles.insert(0, a)
                        self._new_articles.append(a)
                        new += 1
                        # Broadcast ke semua WebSocket client
                        for cb in self._callbacks:
                            try:
                                await cb(a)
                            except Exception:
                                pass

                # Batasi cache: max 100 artikel per kategori
                if category == "crypto":
                    self._crypto_articles = self._crypto_articles[:100]
                else:
                    self._global_articles = self._global_articles[:100]
                if new:
                    print(f"[News] OK {source['name']}: +{new} artikel")
                return new
        except Exception as e:
            print(f"[News] GAGAL {source['name']}: {type(e).__name__}: {e}")
            return 0

    def _parse_rss(self, xml_text: str, source_name: str, category: str) -> list[dict]:
        """Regex-based RSS parser — handles CDATA, malformed XML, Bloomberg, FT, etc."""
        articles = []
        try:
            _item   = re.compile(r'<item>([\s\S]*?)</item>')
            _title  = re.compile(r'<title[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</title>')
            _link   = re.compile(r'<link[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</link>')
            _guid   = re.compile(r'<guid[^>]*isPermaLink="true"[^>]*>([\s\S]*?)</guid>')
            _desc   = re.compile(r'<description[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</description>')
            _date   = re.compile(r'<pubDate[^>]*>([\s\S]*?)</pubDate>')

            for m in _item.finditer(xml_text):
                item = m.group(1)
                tm = _title.search(item)
                lm = _link.search(item) or _guid.search(item)
                dm = _desc.search(item)
                pm = _date.search(item)

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
                articles.append({
                    "title":        title,
                    "url":          url,
                    "summary":      desc,
                    "source":       source_name,
                    "category":     category,
                    "published":    pub.isoformat() if pub else datetime.now(timezone.utc).isoformat(),
                    "published_ts": pub.timestamp() if pub else datetime.now(timezone.utc).timestamp(),
                })
                if len(articles) >= 20:
                    break
        except Exception as e:
            print(f"[News] Parse error {source_name}: {e}")
        return articles

    def get_crypto(self, limit: int = 50) -> list[dict]:
        return self._crypto_articles[:limit]

    def get_global(self, limit: int = 50) -> list[dict]:
        return self._global_articles[:limit]

    def get_latest(self, limit: int = 20) -> list[dict]:
        all_articles = self._crypto_articles + self._global_articles
        all_articles.sort(key=lambda x: x.get("published_ts", 0), reverse=True)
        return all_articles[:limit]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]
