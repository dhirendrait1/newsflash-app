import json, os, re, sys, time, html, difflib, urllib.request, datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news")
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
KEY = os.environ.get("GEMINI_API_KEY", "")
MAX_AGE_H = 36

SECTIONS = [
    {"id": "breaking", "k": 10, "name": "Breaking world news", "feeds": [
        ("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("DW", "https://rss.dw.com/rdf/rss-en-all"),
        ("NPR", "https://feeds.npr.org/1004/rss.xml")]},
    {"id": "india", "k": 5, "name": "India: politics, tech, startups, major updates", "feeds": [
        ("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
        ("Indian Express", "https://indianexpress.com/section/india/feed/"),
        ("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories"),
        ("Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
        ("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml")]},
    {"id": "finance", "k": 10, "name": "Global financial news: markets, economy, business, policy", "feeds": [
        ("BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/business/rss"),
        ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms")]},
    {"id": "crypto", "k": 10, "name": "Crypto and coin news: Bitcoin, Ethereum, altcoins, regulation, market movers", "feeds": [
        ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
        ("Cointelegraph", "https://cointelegraph.com/rss"),
        ("Decrypt", "https://decrypt.co/feed"),
        ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/")]},
]

def http(url, data=None, headers=None, timeout=25):
    h = {"User-Agent": "Mozilla/5.0 (compatible; NewsFlashBot/1.0)"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()

def parse_date(f):
    for k in ("pubDate", "published", "updated", "date"):
        if k in f and f[k].text:
            t = f[k].text.strip()
            try:
                d = parsedate_to_datetime(t)
            except Exception:
                try:
                    d = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
                except Exception:
                    continue
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d
    return None

def parse(data, source):
    root = ET.fromstring(data)
    out = []
    for el in root.iter():
        if el.tag.split("}")[-1] not in ("item", "entry"):
            continue
        f = {c.tag.split("}")[-1]: c for c in el}
        title = clean(f["title"].text) if "title" in f else ""
        link = ""
        if "link" in f:
            link = (f["link"].text or f["link"].attrib.get("href", "")).strip()
        desc = ""
        for k in ("description", "summary", "content"):
            if k in f and f[k].text:
                desc = clean(f[k].text)[:240]
                break
        if title and link.startswith("http"):
            out.append({"title": title, "link": link, "date": parse_date(f), "source": source, "desc": desc})
    return out

def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower())

def collect(sec):
    now = dt.datetime.now(dt.timezone.utc)
    items = []
    for name, url in sec["feeds"]:
        try:
            got = parse(http(url), name)
            items += got
            print("ok", name, len(got))
        except Exception as e:
            print("skip", name, e)
    items = [i for i in items if not i["date"] or (now - i["date"]).total_seconds() < MAX_AGE_H * 3600]
    items.sort(key=lambda i: i["date"] or now, reverse=True)
    clusters = []
    for it in items:
        n = norm(it["title"])
        for c in clusters:
            if difflib.SequenceMatcher(None, n, c["n"]).ratio() > 0.6:
                c["items"].append(it)
                break
        else:
            clusters.append({"n": n, "items": [it]})
    for c in clusters:
        c["sources"] = sorted({i["source"] for i in c["items"]})
    clusters.sort(key=lambda c: (-len(c["sources"]), -(c["items"][0]["date"] or now).timestamp()))
    return clusters

def gemini(prompt):
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % MODEL
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}).encode()
    for attempt in range(3):
        try:
            raw = http(url, body, {"Content-Type": "application/json", "x-goog-api-key": KEY}, 120)
            return json.loads(json.loads(raw)["candidates"][0]["content"]["parts"][0]["text"])
        except Exception as e:
            print("gemini retry", attempt, e)
            time.sleep(8 * (attempt + 1))
    return None

def edit(sec, clusters):
    cands = clusters[: sec["k"] * 2 + 4]
    lines = []
    for i, c in enumerate(cands):
        it = c["items"][0]
        lines.append("%d. [%s] %s | %s" % (i, ", ".join(c["sources"]), it["title"], it["desc"]))
    prompt = (
        "You are the editor of News Flash, a verified short-news app.\n"
        "Below are candidate stories for the section: %s. Each shows the outlets that carried it.\n"
        "Pick the %d most important DIFFERENT stories (skip duplicates, gossip and opinion). Order by importance.\n"
        "For each write: en_headline (max 12 words), en_summary (max 25 words, plain words, no hype), "
        "hi_headline and hi_summary (natural Hindi in Devanagari, same meaning), and en_points and hi_points: "
        "exactly 3 short bullet points each (max 18 words per bullet) with the key facts.\n"
        "Use ONLY facts present in the candidate text. Never add facts, names or numbers that are not given. "
        "Rewrite in your own words; do not copy sentences.\n"
        'Return a JSON array: [{"i": 0, "en_headline": "", "en_summary": "", "hi_headline": "", "hi_summary": "", "en_points": [], "hi_points": []}]\n\n'
        "Candidates:\n%s" % (sec["name"], sec["k"], "\n".join(lines)))
    res = gemini(prompt) if KEY else None
    picks = []
    if isinstance(res, list):
        seen = set()
        for r in res:
            try:
                i = int(r["i"])
                if 0 <= i < len(cands) and i not in seen and r.get("en_headline"):
                    seen.add(i)
                    picks.append((cands[i], r))
            except Exception:
                pass
    if not picks:
        print("fallback headlines only for", sec["id"])
        for c in cands[: sec["k"]]:
            t = c["items"][0]["title"]
            picks.append((c, {"en_headline": t, "en_summary": "", "hi_headline": t, "hi_summary": ""}))
    return picks[: sec["k"]]

def bl(x):
    return [str(i) for i in x if i][:4] if isinstance(x, list) else []

def main():
    now = dt.datetime.now(IST)
    edition = "morning" if now.hour < 12 else "evening"
    data = {"en": [], "hi": []}
    total = 0
    for sec in SECTIONS:
        picks = edit(sec, collect(sec))
        for lang in ("en", "hi"):
            pts = []
            for n, (c, r) in enumerate(picks, 1):
                it = c["items"][0]
                pts.append({
                    "rank": n,
                    "headline": r.get(lang + "_headline") or r.get("en_headline", ""),
                    "summary": r.get(lang + "_summary") or r.get("en_summary", ""),
                    "source": ", ".join(c["sources"][:2]),
                    "link": it["link"],
                    "published": it["date"].astimezone(IST).isoformat() if it["date"] else now.isoformat(),
                    "confirmed": len(c["sources"]),
                    "bullets": bl(r.get(lang + "_points")),
                })
            data[lang].append({"id": sec["id"], "points": pts})
        total += len(picks)
    if total == 0:
        print("No news collected; keeping the previous deployment.")
        sys.exit(1)
    os.makedirs(OUT, exist_ok=True)
    for lang in ("en", "hi"):
        doc = {"edition": edition, "generated": now.isoformat(), "lang": lang, "sections": data[lang]}
        with open(os.path.join(OUT, lang + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
    print("done", total, "points,", edition)

if __name__ == "__main__":
    main()
