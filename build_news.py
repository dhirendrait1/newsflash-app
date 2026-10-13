import json, os, re, sys, time, html, difflib, urllib.request, urllib.error, datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "news")
KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MAX_AGE_H = 36
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36 NewsFlashBot/1.0"
STOP = set("the and for with from that this after over amid about into new says said will has have had not but his her their they you your who what when why how more than out off its was were are been".split())

SECTIONS = [
    {"id": "breaking", "k": 10, "name": "Breaking world news", "feeds": [
        ("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("DW", "https://rss.dw.com/rdf/rss-en-all"),
        ("NPR", "https://feeds.npr.org/1004/rss.xml"),
        ("Sky News", "https://feeds.skynews.com/feeds/rss/world.xml"),
        ("CBS News", "https://www.cbsnews.com/latest/rss/world")]},
    {"id": "india", "k": 5, "name": "India: politics, tech, startups, major updates", "feeds": [
        ("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
        ("Indian Express", "https://indianexpress.com/section/india/feed/"),
        ("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories"),
        ("Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
        ("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"),
        ("Mint", "https://www.livemint.com/rss/news")]},
    {"id": "finance", "k": 10, "name": "Global financial news: markets, economy, business, policy", "feeds": [
        ("BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/business/rss"),
        ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("NPR", "https://feeds.npr.org/1006/rss.xml"),
        ("Mint", "https://www.livemint.com/rss/markets")]},
    {"id": "crypto", "k": 10, "name": "Crypto and coin news: Bitcoin, Ethereum, altcoins, regulation, market movers", "feeds": [
        ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
        ("Cointelegraph", "https://cointelegraph.com/rss"),
        ("Decrypt", "https://decrypt.co/feed"),
        ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/"),
        ("Bitcoinist", "https://bitcoinist.com/feed/"),
        ("CryptoSlate", "https://cryptoslate.com/feed/"),
        ("NewsBTC", "https://www.newsbtc.com/feed/")]},
]


def http(url, data=None, headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, application/json, */*"}
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
                desc = clean(f[k].text)[:300]
                break
        if title and link.startswith("http"):
            out.append({"title": title, "link": link, "date": parse_date(f), "source": source, "desc": desc})
    return out


def words(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) >= 4 and w not in STOP}


def same_story(a, b):
    wa, wb = words(a), words(b)
    inter = len(wa & wb)
    if inter >= 3 and inter / max(1, len(wa | wb)) >= 0.4:
        return True
    na, nb = re.sub(r"[^a-z0-9 ]", "", a.lower()), re.sub(r"[^a-z0-9 ]", "", b.lower())
    return difflib.SequenceMatcher(None, na, nb).ratio() > 0.68


def collect(sec):
    now = dt.datetime.now(dt.timezone.utc)
    items, feeds = [], {}
    for name, url in sec["feeds"]:
        try:
            got = parse(http(url), name)
            items += got
            feeds[name] = len(got)
            print("ok", sec["id"], name, len(got))
        except Exception as e:
            feeds[name] = "error: %s" % str(e)[:80]
            print("skip", sec["id"], name, e)
    items = [i for i in items if not i["date"] or (now - i["date"]).total_seconds() < MAX_AGE_H * 3600]
    items.sort(key=lambda i: i["date"] or now, reverse=True)
    clusters = []
    for it in items:
        for c in clusters:
            if same_story(it["title"], c["items"][0]["title"]):
                c["items"].append(it)
                break
        else:
            clusters.append({"items": [it]})
    for c in clusters:
        c["sources"] = sorted({i["source"] for i in c["items"]})
    clusters.sort(key=lambda c: (-len(c["sources"]), -(c["items"][0]["date"] or now).timestamp()))
    return clusters, feeds


_MODELS = None


def model_list():
    global _MODELS
    if _MODELS is not None:
        return _MODELS
    names = [m for m in [os.environ.get("GEMINI_MODEL"), "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash"] if m]
    try:
        raw = http("https://generativelanguage.googleapis.com/v1beta/models?pageSize=100", None, {"x-goog-api-key": KEY}, 30)
        for m in json.loads(raw).get("models", []):
            n = m.get("name", "").replace("models/", "")
            if "flash" in n and "generateContent" in m.get("supportedGenerationMethods", []) \
                    and not re.search(r"lite|image|tts|live|audio|thinking|exp|preview", n) and n not in names:
                names.append(n)
    except Exception as e:
        print("could not list models:", e)
    _MODELS = names
    print("models to try:", names[:8])
    return names


def salvage(text):
    out, dec = {}, json.JSONDecoder()
    for sec in SECTIONS:
        m = re.search(r'"%s"\s*:\s*\[' % sec["id"], text)
        if not m:
            continue
        pos, items = m.end(), []
        while True:
            while pos < len(text) and text[pos] in " \n\r\t,":
                pos += 1
            if pos >= len(text) or text[pos] != "{":
                break
            try:
                obj, pos = dec.raw_decode(text, pos)
            except Exception:
                break
            items.append(obj)
        if items:
            out[sec["id"]] = items
    return out or None


def parse_result(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
    try:
        res = json.loads(text)
        if isinstance(res, dict) and any(isinstance(res.get(s["id"]), list) for s in SECTIONS):
            return res
    except Exception:
        pass
    return salvage(text)


def retry_delay(msg):
    m = re.search(r'retryDelay"?\s*:\s*"?(\d+)', msg)
    return int(m.group(1)) + 2 if m else 0


def ask(prompt):
    if not KEY:
        return None, "GEMINI_API_KEY is empty. Add it in Settings > Secrets and variables > Actions."
    last = "no model answered"
    for name in model_list()[:5]:
        url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % name
        variants = [{"thinkingConfig": {"thinkingBudget": 0}, "maxOutputTokens": 32768},
                    {"maxOutputTokens": 32768}, {"maxOutputTokens": 8192}]
        vi, tries = 0, 0
        while vi < len(variants) and tries < 6:
            tries += 1
            gc = {"responseMimeType": "application/json", "temperature": 0.2}
            gc.update(variants[vi])
            body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gc}).encode()
            try:
                raw = http(url, body, {"Content-Type": "application/json", "x-goog-api-key": KEY}, 300)
                text = json.loads(raw)["candidates"][0]["content"]["parts"][0]["text"]
                res = parse_result(text)
                if res:
                    print("gemini ok with", name)
                    return res, "ok with " + name
                last = "%s: unusable answer" % name
                print("gemini", last)
                break
            except urllib.error.HTTPError as e:
                msg = e.read()[:600].decode("utf-8", "ignore")
                last = "%s HTTP %s %s" % (name, e.code, re.sub(r"\s+", " ", msg)[:180])
                print("gemini", last)
                if e.code == 400:
                    vi += 1
                    continue
                if e.code in (429, 500, 502, 503, 504):
                    if "PerDay" in msg or "per day" in msg.lower():
                        break
                    time.sleep(min(retry_delay(msg) or 20 * tries, 70))
                    continue
                break
            except Exception as e:
                last = "%s error %s" % (name, e)
                print("gemini", last)
                break
    return None, last


def short(desc, n=170):
    desc = desc.strip()
    if len(desc) <= n:
        return desc
    return desc[:n].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def bl(x):
    return [str(i) for i in x if i][:4] if isinstance(x, list) else []


def build_prompt(cands, secs=None):
    parts = []
    for sec in (secs or SECTIONS):
        lines = []
        for i, c in enumerate(cands[sec["id"]]):
            it = c["items"][0]
            lines.append("%d. [%s] %s | %s" % (i, ", ".join(c["sources"]), it["title"], it["desc"][:200]))
        parts.append('SECTION "%s" (%s). Pick the %d most important DIFFERENT stories (skip gossip and opinion):\n%s'
                     % (sec["id"], sec["name"], sec["k"], "\n".join(lines)))
    head = (
        "You are the editor of News Flash, a verified short-news app for readers in India.\n"
        "Below are candidate stories grouped in sections. Each shows the outlets that carried it.\n"
        "For every story you pick write: en_headline (max 12 words), en_summary (max 25 words, plain words, no hype), "
        "hi_headline and hi_summary (natural Hindi in Devanagari, same meaning), and en_points and hi_points: "
        "exactly 3 short bullet points each (max 14 words per bullet) with the key facts.\n"
        "Use ONLY facts present in the candidate text. Never add facts, names or numbers that are not given. "
        "Rewrite in your own words; do not copy sentences. Order by importance.\n"
        'Return ONE JSON object with a key for each section id given below. '
        'Each value is an array of objects: {"i": 0, "en_headline": "", "en_summary": "", "hi_headline": "", '
        '"hi_summary": "", "en_points": [], "hi_points": []}. "i" is the candidate number.\n\n')
    return head + "\n\n".join(parts)


def main():
    now = dt.datetime.now(IST)
    edition = "morning" if now.hour < 14 else "evening"
    cands, status = {}, {"generated": now.isoformat(), "sections": {}}
    for sec in SECTIONS:
        clusters, feeds = collect(sec)
        cands[sec["id"]] = clusters[: sec["k"] * 2 + 2]
        status["sections"][sec["id"]] = {"feeds": feeds, "stories_found": len(clusters)}
    res, gstatus = ask(build_prompt(cands)) if any(cands.values()) else (None, "no news collected")
    status["gemini"] = gstatus
    print("Gemini status:", gstatus)
    res = res or {}
    if gstatus.startswith("ok"):
        miss = [s for s in SECTIONS if cands[s["id"]] and len(res.get(s["id"]) or []) < s["k"]]
        if miss:
            print("second request for incomplete sections:", [s["id"] for s in miss])
            res2, st2 = ask(build_prompt(cands, miss))
            status["gemini_second"] = st2
            for s in miss:
                got = (res2 or {}).get(s["id"])
                if isinstance(got, list) and len(got) > len(res.get(s["id"]) or []):
                    res[s["id"]] = got
    data = {"en": [], "hi": []}
    total = 0
    for sec in SECTIONS:
        cl, picks, used = cands[sec["id"]], [], set()
        for r in res.get(sec["id"], []) if isinstance(res.get(sec["id"]), list) else []:
            try:
                i = int(r["i"])
            except Exception:
                continue
            if 0 <= i < len(cl) and i not in used and r.get("en_headline"):
                used.add(i)
                picks.append((cl[i], r))
        ai = len(picks)
        for i, c in enumerate(cl):
            if len(picks) >= sec["k"]:
                break
            if i not in used:
                it = c["items"][0]
                picks.append((c, {"en_headline": it["title"], "en_summary": short(it["desc"])}))
        picks = picks[: sec["k"]]
        status["sections"][sec["id"]].update({"ai_items": min(ai, sec["k"]), "plain_items": len(picks) - min(ai, sec["k"])})
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
    with open(os.path.join(OUT, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    print("done", total, "points,", edition)


if __name__ == "__main__":
    main()
