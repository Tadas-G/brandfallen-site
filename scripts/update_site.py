#!/usr/bin/env python3
"""Add new Brandfallen YouTube episodes to the static site.

Reads the channel's public RSS feed, and for every long-form video that is not
yet on the homepage it:
  * downloads the thumbnail to thumbs/<slug>.jpg
  * creates <slug>/index.html (description, chapters, links)
  * adds a card to the "Latest episodes" grid on index.html
  * adds the page to sitemap.xml
  * refreshes the "Next episode" block (from next.json, or "coming soon")

Safe to run any number of times: videos already linked on index.html are skipped.
Stdlib only.
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

CHANNEL_ID = "UC09vQjSwfZYH0H24m8DQTMA"
FEED = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
SUBSCRIBE = "https://www.youtube.com/@Brandfallen?sub_confirmation=1"
ROOT = Path(__file__).resolve().parent.parent
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
UA = {"User-Agent": "Mozilla/5.0 (brandfallen-site updater)"}
CHAPTER_RE = re.compile(r"^\s*((?:\d{1,2}:)?\d{1,2}:\d{2})\s*[-–—|:]?\s*(.+)$")
URL_RE = re.compile(r"https?://\S+")
NEXT_RE = re.compile(r'<section class="next">.*?</section>', re.S)


def fetch(url, binary=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return data if binary else data.decode("utf-8")


def is_short(video_id):
    """Shorts answer 200 on /shorts/ID; normal videos redirect to /watch."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        r = opener.open(urllib.request.Request(
            f"https://www.youtube.com/shorts/{video_id}", headers=UA, method="HEAD"), timeout=30)
        return r.status == 200
    except urllib.error.HTTPError as e:
        return False if e.code in (301, 302, 303, 307, 308) else False
    except Exception:
        return False


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60].rstrip("-") or "episode"


def seconds(ts):
    parts = [int(p) for p in ts.split(":")]
    total = 0
    for p in parts:
        total = total * 60 + p
    return total


def esc(s):
    return html.escape(s, quote=True)


def parse_description(desc):
    chapters, paragraphs, links = [], [], []
    block = []
    for raw in desc.splitlines():
        line = raw.strip()
        m = CHAPTER_RE.match(line)
        if m:
            chapters.append((m.group(1), m.group(2).strip()))
            continue
        urls = URL_RE.findall(line)
        for u in urls:
            if "youtube.com" not in u and "youtu.be" not in u:
                links.append(u.rstrip(").,"))
        text = URL_RE.sub("", line).strip(" :-–—")
        if not line:
            if block:
                paragraphs.append(" ".join(block))
                block = []
            continue
        if urls and len(text) < 40:
            continue  # line that is mostly a link
        if line.startswith("#") or line.lower().startswith(("chapters", "sources", "timestamps")):
            continue
        block.append(text)
    if block:
        paragraphs.append(" ".join(block))
    paragraphs = [p for p in paragraphs if p]
    seen, uniq = set(), []
    for u in links:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return chapters, paragraphs, uniq


def next_block():
    nxt = None
    p = ROOT / "next.json"
    if p.exists():
        try:
            nxt = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            nxt = None
    published = (ROOT / "index.html").read_text(encoding="utf-8").lower()
    if nxt and nxt.get("title") and nxt["title"].lower() not in published:
        title, when = nxt["title"], nxt.get("date", "")
    else:
        title, when = "Coming soon", ""
    date_line = f"\n      <p>{esc(when)}</p>" if when else ""
    return (
        '<section class="next">\n'
        '      <p class="label">Next episode</p>\n'
        f'      <p class="next-title">{esc(title)}</p>{date_line}\n'
        f'      <a class="button" href="{SUBSCRIBE}">Subscribe to get it first</a>\n'
        '    </section>'
    )


def episode_page(v, n, slug, nb):
    vid, title = v["id"], v["title"]
    chapters, paragraphs, links = parse_description(v["description"])
    lead = paragraphs[0] if paragraphs else title
    rest = paragraphs[1:]
    meta_desc = lead[:300]
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "VideoObject", "name": title,
        "description": meta_desc, "thumbnailUrl": f"https://brandfallen.com/thumbs/{slug}.jpg",
        "uploadDate": v["published"], "embedUrl": f"https://www.youtube-nocookie.com/embed/{vid}",
    }, ensure_ascii=False)
    out = [f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)} | Brandfallen</title>
  <meta name="description" content="{esc(meta_desc)}">
  <link rel="canonical" href="https://brandfallen.com/{slug}/">
  <meta property="og:title" content="{esc(title)} | Brandfallen">
  <meta property="og:description" content="{esc(meta_desc)}">
  <meta property="og:url" content="https://brandfallen.com/{slug}/">
  <meta property="og:image" content="https://brandfallen.com/thumbs/{slug}.jpg">
  <link rel="icon" href="/logo.png">
  <link rel="stylesheet" href="/style.css">
  <script type="application/ld+json">{ld}</script>
</head>
<body>
  <header class="top"><div class="wrap"><a href="/"><img src="/logo.png" alt=""><span>BRAND<span class="fallen">FALLEN</span></span></a></div></header>
  <main class="wrap page">
    <p class="label">Episode {n}</p>
    <h1>{esc(title)}</h1>
    <a class="player" href="https://youtu.be/{vid}" aria-label="Watch on YouTube">
      <img src="/thumbs/{slug}.jpg" alt="" width="1280" height="720">
      <span class="play"></span>
    </a>
    <p class="lead">{esc(lead)}</p>
    <p><a class="button" href="{SUBSCRIBE}">Subscribe on YouTube</a></p>"""]
    if chapters:
        out.append("    <h2>Chapters</h2>\n    <ul class=\"chapters\">")
        for ts, name in chapters:
            out.append(f'      <li><a href="https://youtu.be/{vid}?t={seconds(ts)}">{ts}</a> {esc(name)}</li>')
        out.append("    </ul>")
    if rest:
        out.append("    <h2>About this episode</h2>")
        out += [f"    <p>{esc(p)}</p>" for p in rest]
    if links:
        out.append("    <h2>Sources</h2>\n    <ul>")
        for u in links:
            label = re.sub(r"^https?://(www\.)?", "", u).split("/")[0]
            out.append(f'      <li><a href="{esc(u)}" rel="nofollow noopener">{esc(label)}</a></li>')
        out.append("    </ul>")
    out.append('    <p class="note">This video tells a business story. It is not medical, legal or financial advice.</p>')
    if nb:
        out.append("    " + nb)
    out.append("""  </main>
  <footer>
    <div class="wrap">
      <a href="/privacy.html">Privacy Policy</a>
      <a href="/terms.html">Terms of Use</a>
    </div>
  </footer>
</body>
</html>
""")
    return "\n".join(out)


def main():
    feed = ET.fromstring(fetch(FEED))
    videos = []
    for e in feed.findall("a:entry", NS):
        group = e.find("media:group", NS)
        videos.append({
            "id": e.find("yt:videoId", NS).text,
            "title": e.find("a:title", NS).text.strip(),
            "published": e.find("a:published", NS).text,
            "description": (group.find("media:description", NS).text or "") if group is not None else "",
        })
    videos.sort(key=lambda v: v["published"])  # oldest first

    index_path = ROOT / "index.html"
    index = index_path.read_text(encoding="utf-8")
    m = re.search(r'<p class="next-title">(.*?)</p>', index)
    announced = html.unescape(m.group(1)) if m else ""
    n = len(re.findall(r'<span class="episode">', index))
    added = []

    for v in videos:
        if v["id"] in index:
            continue
        if is_short(v["id"]):
            print(f"skip short: {v['title']}")
            continue
        n += 1
        if announced and announced.lower() != "coming soon" and announced.lower() in v["title"].lower():
            slug = slugify(announced)
        else:
            slug = slugify(v["title"])
        if (ROOT / slug).exists():
            slug = f"{slug}-{n}"

        thumb = None
        for q in ("maxresdefault", "sddefault", "hqdefault"):
            try:
                thumb = fetch(f"https://i.ytimg.com/vi/{v['id']}/{q}.jpg", binary=True)
                break
            except urllib.error.HTTPError:
                continue
        if thumb:
            (ROOT / "thumbs").mkdir(exist_ok=True)
            (ROOT / "thumbs" / f"{slug}.jpg").write_bytes(thumb)

        card = f"""
      <article class="card">
        <a href="https://youtu.be/{v['id']}" aria-label="Watch {esc(v['title'])} on YouTube"><img src="/thumbs/{slug}.jpg" alt="" loading="lazy" width="1280" height="720"></a>
        <span class="episode">Episode {n}</span>
        <a class="title" href="/{slug}/">{esc(v['title'])}</a>
      </article>"""
        index = index.replace('<div class="grid">', '<div class="grid">' + card, 1)
        index_path.write_text(index, encoding="utf-8")

        (ROOT / slug).mkdir(exist_ok=True)
        (ROOT / slug / "index.html").write_text(episode_page(v, n, slug, ""), encoding="utf-8")

        sm = ROOT / "sitemap.xml"
        s = sm.read_text(encoding="utf-8")
        loc = f"https://brandfallen.com/{slug}/"
        if loc not in s:
            s = s.replace("</urlset>", f"  <url><loc>{loc}</loc></url>\n</urlset>")
            sm.write_text(s, encoding="utf-8")
        added.append(f"Episode {n}: {v['title']} -> /{slug}/")

    if not added:
        print("No new episodes.")
        return 0

    # refresh "Next episode" block everywhere
    nb = next_block()
    for page in [index_path] + sorted(ROOT.glob("*/index.html")):
        t = page.read_text(encoding="utf-8")
        if NEXT_RE.search(t):
            t = NEXT_RE.sub(lambda _: nb, t, count=1)
        elif "<main" in t and page != index_path:
            t = t.replace("  </main>", "    " + nb + "\n  </main>", 1)
        page.write_text(t, encoding="utf-8")

    print("\n".join(added))
    return 0


if __name__ == "__main__":
    sys.exit(main())
