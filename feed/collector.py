#!/usr/bin/env python3
import argparse
import hashlib
import html
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "iAlexeyRu").lstrip("@")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/home/deploy/ialexey-feed/data"))
SITE_INDEX = Path(os.environ.get("SITE_INDEX", "/home/deploy/ialexey-web/index.html"))
SOURCE_INDEX = Path(os.environ.get("SOURCE_INDEX", "/home/deploy/repos/ialexey-web/index.html"))
SITE_ROOT = Path(os.environ.get("SITE_ROOT", str(SITE_INDEX.parent)))
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/tg-feed/webhook")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://ialexey.ru").rstrip("/")
PORT = int(os.environ.get("PORT", "8788"))
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "12"))

FEED_JSON = DATA_DIR / "feed.json"
METRICS_JSON = DATA_DIR / "metrics.json"
INDEXNOW_STATE_JSON = DATA_DIR / "indexnow.json"
INDEXNOW_KEY_FILE = DATA_DIR / "indexnow.key"
PUBLIC_FEED_JSON = SITE_ROOT / "feed.json"
PUBLIC_RSS = SITE_ROOT / "feed.xml"
PUBLIC_SITEMAP = SITE_ROOT / "sitemap.xml"
PUBLIC_ROBOTS = SITE_ROOT / "robots.txt"
PUBLIC_LLMS = SITE_ROOT / "llms.txt"
PUBLIC_POSTS_DIR = SITE_ROOT / "posts"
SOURCE_MEDIA_DIR = Path("/home/deploy/repos/ialexey-web/media")
PUBLIC_MEDIA_DIR = Path("/home/deploy/ialexey-web/media")
METRICS_PATH = "/stats/pageview"
STATS_DASHBOARD_PATH = "/stats"
METRICS_LOCK = threading.Lock()
SITE_TITLE = "Алексей Гетманец | Сливы и новости ИИ"
SITE_DESCRIPTION = "Сливы и новости ИИ от Алексея Гетманца: короткая Telegram-лента, RSS и статические страницы постов."
SITE_AUTHOR = "Алексей Гетманец"
X_PROFILE_URL = "https://x.com/iAlexeyRu"
TELEGRAM_URL = f"https://t.me/{CHANNEL_USERNAME}"

CSS_START = "        /* TG_FEED_CSS_START */"
CSS_END = "        /* TG_FEED_CSS_END */"
META_START = "    <!-- GENERATED_META_START -->"
META_END = "    <!-- GENERATED_META_END -->"
SECTION_START = "    <!-- TELEGRAM_FEED_SECTION_START -->"
SECTION_END = "    <!-- TELEGRAM_FEED_SECTION_END -->"
ITEMS_START = "        <!-- TG_FEED_ITEMS_START -->"
ITEMS_END = "        <!-- TG_FEED_ITEMS_END -->"


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def log(message):
    print(message, flush=True)


def require_env(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Не задана переменная окружения {name}")
    return value


def atomic_write(path, content, permissions=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if permissions is None and path.exists():
        permissions = path.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    if permissions is not None:
        os.chmod(path, permissions)


def site_url(path="/"):
    path = str(path or "/")
    if not path.startswith("/"):
        path = "/" + path
    return PUBLIC_BASE_URL + path


def public_url_host():
    return urlparse(PUBLIC_BASE_URL).netloc or "ialexey.ru"


def parse_date(value):
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def xml_escape(value):
    return html.escape(str(value or ""), quote=True)


def json_ld(data):
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c")


def cdata(value):
    return "<![CDATA[" + str(value or "").replace("]]>", "]]]]><![CDATA[>") + "]]>"


def compact_text(value):
    return re.sub(r"\s+", " ", clean_text(value)).strip()


def truncate_text(value, limit):
    value = compact_text(value)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def post_path(item):
    return f"/posts/{int(item.get('message_id') or 0)}/"


def post_title(item):
    return truncate_text(item.get("text", ""), 86) or f"Пост Telegram {item.get('message_id')}"


def post_description(item):
    return truncate_text(item.get("text", ""), 220) or SITE_DESCRIPTION


def load_feed():
    if not FEED_JSON.exists():
        return []
    with FEED_JSON.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("items", [])


def save_feed(items):
    deduped = {}
    for item in items:
        deduped[str(item["id"])] = item
    ordered = sorted(deduped.values(), key=lambda x: (x.get("date") or "", int(x.get("message_id") or 0)), reverse=True)
    ordered = ordered[:MAX_ITEMS]
    payload = {"updated_at": now_iso(), "channel": CHANNEL_USERNAME, "items": ordered}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    atomic_write(FEED_JSON, text, permissions=0o600)
    publish_public_feed(text)
    return ordered


def load_metrics():
    if not METRICS_JSON.exists():
        return {"updated_at": None, "total": 0, "days": {}}
    with METRICS_JSON.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data.get("days"), dict):
        data["days"] = {}
    data["total"] = int(data.get("total") or 0)
    return data


def save_metrics(data):
    data["updated_at"] = now_iso()
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write(METRICS_JSON, text, permissions=0o600)


def metrics_day():
    return datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")


def normalize_metric_path(value):
    path = str(value or "/").strip()
    path = path.split("#", 1)[0].split("?", 1)[0]
    if not path.startswith("/") or path.startswith("//"):
        path = "/"
    if len(path) > 180:
        path = path[:180]
    if not re.fullmatch(r"/[A-Za-z0-9А-Яа-яЁё._~!$&'()*+,;=:@%/-]*", path):
        path = "/"
    return path or "/"


def record_pageview(path):
    path = normalize_metric_path(path)
    day = metrics_day()
    with METRICS_LOCK:
        data = load_metrics()
        data["total"] = int(data.get("total") or 0) + 1
        day_bucket = data.setdefault("days", {}).setdefault(day, {"total": 0, "paths": {}})
        day_bucket["total"] = int(day_bucket.get("total") or 0) + 1
        paths = day_bucket.setdefault("paths", {})
        paths[path] = int(paths.get(path) or 0) + 1
        save_metrics(data)
    return path


def metrics_dashboard():
    data = load_metrics()
    days = data.get("days", {})
    ordered_days = sorted(days.keys(), reverse=True)
    today = metrics_day()
    today_total = int(days.get(today, {}).get("total") or 0)
    last_7_total = sum(int(days.get(day, {}).get("total") or 0) for day in ordered_days[:7])
    all_paths = {}
    for day_data in days.values():
        for path, count in day_data.get("paths", {}).items():
            all_paths[path] = all_paths.get(path, 0) + int(count or 0)
    top_paths = sorted(all_paths.items(), key=lambda item: item[1], reverse=True)[:20]

    day_rows = "\n".join(
        f"<tr><td>{html.escape(day)}</td><td>{int(days[day].get('total') or 0)}</td></tr>"
        for day in ordered_days[:30]
    )
    path_rows = "\n".join(
        f"<tr><td>{html.escape(path)}</td><td>{count}</td></tr>"
        for path, count in top_paths
    )
    updated = html.escape(data.get("updated_at") or "нет данных")
    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>iAlexey metrics</title>
    <style>
        body {{ margin: 0; padding: 32px; background: #0d1117; color: #c9d1d9; font: 16px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
        main {{ max-width: 920px; margin: 0 auto; }}
        h1, h2 {{ color: #fff; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 24px 0; }}
        .stat, table {{ border: 1px solid #30363d; background: #161b22; border-radius: 8px; }}
        .stat {{ padding: 16px; }}
        .value {{ display: block; margin-top: 8px; color: #58a6ff; font-size: 28px; font-weight: 700; }}
        table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
        th, td {{ padding: 10px 12px; border-bottom: 1px solid #30363d; text-align: left; }}
        th {{ color: #8b949e; font-weight: 600; }}
        tr:last-child td {{ border-bottom: 0; }}
        .note {{ color: #8b949e; margin-top: 24px; }}
    </style>
</head>
<body>
<main>
    <h1>iAlexey metrics</h1>
    <div class="grid">
        <div class="stat">Всего просмотров<span class="value">{int(data.get("total") or 0)}</span></div>
        <div class="stat">Сегодня<span class="value">{today_total}</span></div>
        <div class="stat">Последние 7 дней<span class="value">{last_7_total}</span></div>
    </div>
    <h2>Дни</h2>
    <table><thead><tr><th>Дата MSK</th><th>Pageviews</th></tr></thead><tbody>{day_rows}</tbody></table>
    <h2>Страницы</h2>
    <table><thead><tr><th>Path</th><th>Pageviews</th></tr></thead><tbody>{path_rows}</tbody></table>
    <p class="note">Обновлено: {updated}. Хранятся только агрегированные счетчики по дню и path. IP, user-agent, cookies, referrer, fingerprint и visitor ID не сохраняются.</p>
</main>
</body>
</html>
"""


def publish_public_feed(text=None):
    if text is None:
        if not FEED_JSON.exists():
            return
        text = FEED_JSON.read_text(encoding="utf-8")
    atomic_write(PUBLIC_FEED_JSON, text, permissions=0o664)


def iso_from_unix(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).replace(microsecond=0).isoformat()


def format_date(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        dt = dt.astimezone(ZoneInfo("Europe/Moscow"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return value


def clean_text(text):
    return re.sub(r"\n{3,}", "\n\n", (text or "").strip())


def download_image(url, message_id):
    if not url:
        return None
    try:
        SOURCE_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        PUBLIC_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        
        target_name = f"{message_id}.jpg"
        source_path = SOURCE_MEDIA_DIR / target_name
        public_path = PUBLIC_MEDIA_DIR / target_name
        
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            data = response.read()
            
        source_path.write_bytes(data)
        public_path.write_bytes(data)
        log(f"Изображение сохранено для поста {message_id}: media/{target_name}")
        return f"media/{target_name}"
    except Exception as exc:
        log(f"Ошибка скачивания изображения {url}: {exc}")
    return None


def get_telegram_file_url(file_id):
    try:
        file_info = telegram_api("getFile", {"file_id": file_id})
        if file_info.get("ok"):
            file_path = file_info["result"]["file_path"]
            token = require_env("TELEGRAM_BOT_TOKEN")
            return f"https://api.telegram.org/file/bot{token}/{file_path}"
    except Exception as exc:
        log(f"Ошибка getFile: {exc}")
    return None


def apply_entities(text, entities):
    if not text:
        return ""
    if not entities:
        return text_to_html(text)
        
    try:
        sorted_entities = sorted(entities, key=lambda x: x.get("offset", 0), reverse=True)
        encoded = text.encode("utf-16-le")
        
        for ent in sorted_entities:
            ent_type = ent.get("type")
            if ent_type not in ("url", "text_link"):
                continue
                
            offset = ent.get("offset", 0)
            length = ent.get("length", 0)
            
            start = offset * 2
            end = (offset + length) * 2
            
            ent_text = encoded[start:end].decode("utf-16-le")
            
            if ent_type == "text_link":
                url = ent.get("url", "")
            else:
                url = ent_text
                
            if not url:
                continue
                
            markdown_str = f"[{ent_text}]({url})"
            encoded = encoded[:start] + markdown_str.encode("utf-16-le") + encoded[end:]
            
        text = encoded.decode("utf-16-le")
    except Exception as exc:
        log(f"Ошибка apply_entities: {exc}")
        
    return text_to_html(text)


def linkify(escaped):
    placeholders = []
    def save_link(match):
        placeholders.append(match.group(0))
        return f"___LINK_PLACEHOLDER_{len(placeholders)-1}___"
        
    temp_text = re.sub(r'<a\s+[^>]*>.*?</a>', save_link, escaped, flags=re.S)
    
    pattern = re.compile(r"(https?://[^\s<]+)")
    temp_text = pattern.sub(r'<a href="\1" target="_blank" rel="noopener">\1</a>', temp_text)
    
    for i, placeholder_content in enumerate(placeholders):
        temp_text = temp_text.replace(f"___LINK_PLACEHOLDER_{i}___", placeholder_content)
        
    return temp_text


def text_to_html(text):
    escaped = html.escape(clean_text(text))
    markdown_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)")
    html_text = markdown_pattern.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', escaped)
    return linkify(html_text).replace("\n", "<br>")


def message_to_item(message, edited=False):
    message_id = message.get("message_id")
    text = clean_text(message.get("text") or message.get("caption") or "")
    if not message_id:
        return None
        
    photo = message.get("photo")
    if not text and not photo:
        return None

    image_path = None
    if photo:
        file_id = photo[-1]["file_id"]
        file_url = get_telegram_file_url(file_id)
        if file_url:
            image_path = download_image(file_url, message_id)

    entities = message.get("entities") or message.get("caption_entities") or []

    return {
        "id": f"telegram:{CHANNEL_USERNAME}:{message_id}",
        "source": "telegram",
        "message_id": message_id,
        "date": iso_from_unix(message.get("date", datetime.now(timezone.utc).timestamp())),
        "url": f"https://t.me/{CHANNEL_USERNAME}/{message_id}",
        "text": text,
        "html": apply_entities(text, entities),
        "image": image_path,
        "edited": bool(edited),
        "received_at": now_iso(),
    }


def upsert_item(item):
    items = [x for x in load_feed() if x.get("id") != item["id"]]
    items.append(item)
    items = save_feed(items)
    render_site(items)
    return item


def strip_public_html(fragment):
    fragment = re.sub(
        r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        r'[\2](\1)',
        fragment,
        flags=re.S
    )
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"</p\s*>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return clean_text(html.unescape(fragment))


def extract_public_posts(page_html):
    posts = []
    blocks = page_html.split('<div class="tgme_widget_message_wrap')
    for block in blocks:
        post_match = re.search(r'data-post="' + re.escape(CHANNEL_USERNAME) + r"/(\d+)", block)
        if not post_match:
            continue
        message_id = int(post_match.group(1))
        
        texts = re.findall(
            r'<div class="tgme_widget_message_text js-message_text"[^>]*>(.*?)</div>',
            block,
            re.S,
        )
        text = strip_public_html(texts[-1]) if texts else ""
        
        image_match = re.search(r'tgme_widget_message_photo_wrap[^>]*style="background-image:url\(\'([^\'\)]+)\'\)"', block)
        if not image_match:
            image_match = re.search(r'background-image:url\(\'([^\'\)]+)\'\)', block)
            
        image_path = None
        if image_match:
            image_url = image_match.group(1)
            if "/emoji/" not in image_url:
                image_path = download_image(image_url, message_id)
            
        if not text and not image_path:
            continue

        date_match = re.search(r'<time datetime="([^"]+)"', block)
        date = date_match.group(1) if date_match else now_iso()

        posts.append(
            {
                "id": f"telegram:{CHANNEL_USERNAME}:{message_id}",
                "source": "telegram",
                "message_id": message_id,
                "date": date,
                "url": f"https://t.me/{CHANNEL_USERNAME}/{message_id}",
                "text": text,
                "html": text_to_html(text),
                "image": image_path,
                "edited": False,
                "received_at": now_iso(),
            }
        )
    return posts


def seed_public():
    url = f"https://t.me/s/{CHANNEL_USERNAME}"
    with urllib.request.urlopen(url, timeout=20) as response:
        page = response.read().decode("utf-8", errors="replace")
    seeded = extract_public_posts(page)
    if not seeded:
        raise SystemExit("Не удалось получить публичные посты Telegram")
    items = save_feed(load_feed() + seeded)
    render_site(items)
    log(f"Импортировано публичных постов: {len(seeded)}; в ленте: {len(items)}")


def generated_head_meta(items):
    graph = [
        {
            "@type": "Person",
            "@id": site_url("/#person"),
            "name": SITE_AUTHOR,
            "url": site_url("/"),
            "image": site_url("/avatar.png"),
            "sameAs": [TELEGRAM_URL, X_PROFILE_URL],
        },
        {
            "@type": "WebSite",
            "@id": site_url("/#website"),
            "url": site_url("/"),
            "name": SITE_TITLE,
            "description": SITE_DESCRIPTION,
            "inLanguage": "ru-RU",
            "publisher": {"@id": site_url("/#person")},
        },
    ]
    if items:
        graph.append(
            {
                "@type": "ItemList",
                "@id": site_url("/#telegram-feed"),
                "name": "Последние посты Telegram",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": idx,
                        "url": site_url(post_path(item)),
                        "name": post_title(item),
                    }
                    for idx, item in enumerate(items, start=1)
                ],
            }
        )
    schema = {"@context": "https://schema.org", "@graph": graph}
    return f"""{META_START}
    <meta name="description" content="{html.escape(SITE_DESCRIPTION, quote=True)}">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="{site_url("/")}">
    <link rel="alternate" type="application/rss+xml" title="{html.escape(SITE_TITLE, quote=True)}" href="{site_url("/feed.xml")}">
    <meta property="og:type" content="website">
    <meta property="og:site_name" content="{html.escape(SITE_AUTHOR, quote=True)}">
    <meta property="og:title" content="{html.escape(SITE_TITLE, quote=True)}">
    <meta property="og:description" content="{html.escape(SITE_DESCRIPTION, quote=True)}">
    <meta property="og:url" content="{site_url("/")}">
    <meta property="og:image" content="{site_url("/avatar.png")}">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="{html.escape(SITE_TITLE, quote=True)}">
    <meta name="twitter:description" content="{html.escape(SITE_DESCRIPTION, quote=True)}">
    <meta name="twitter:image" content="{site_url("/avatar.png")}">
    <script type="application/ld+json">{json_ld(schema)}</script>
{META_END}"""


def ensure_head_meta(document, items):
    meta = generated_head_meta(items)
    if META_START in document and META_END in document:
        return re.sub(
            re.escape(META_START) + r".*?" + re.escape(META_END),
            meta,
            document,
            flags=re.S,
        )
    return document.replace("    <style>", meta + "\n    <style>", 1)


def render_rss(items):
    updated = format_datetime(parse_date(items[0].get("date")) if items else datetime.now(timezone.utc))
    rss_items = []
    for item in items:
        local_url = site_url(post_path(item))
        rss_items.append(
            f"""        <item>
            <title>{xml_escape(post_title(item))}</title>
            <link>{xml_escape(local_url)}</link>
            <guid isPermaLink="false">{xml_escape(item.get("id"))}</guid>
            <pubDate>{format_datetime(parse_date(item.get("date")))}</pubDate>
            <description>{cdata(item.get("html") or text_to_html(item.get("text", "")))}</description>
            <source url="{xml_escape(item.get("url", TELEGRAM_URL))}">Telegram / @{xml_escape(CHANNEL_USERNAME)}</source>
        </item>"""
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
    <channel>
        <title>{xml_escape(SITE_TITLE)}</title>
        <link>{xml_escape(site_url("/"))}</link>
        <description>{xml_escape(SITE_DESCRIPTION)}</description>
        <language>ru</language>
        <lastBuildDate>{updated}</lastBuildDate>
{chr(10).join(rss_items)}
    </channel>
</rss>
"""


def render_sitemap(items):
    urls = [(site_url("/"), parse_date(items[0].get("date")) if items else datetime.now(timezone.utc), "daily")]
    for item in items:
        urls.append((site_url(post_path(item)), parse_date(item.get("date")), "weekly"))
    entries = "\n".join(
        f"""    <url>
        <loc>{xml_escape(url)}</loc>
        <lastmod>{dt.date().isoformat()}</lastmod>
        <changefreq>{changefreq}</changefreq>
    </url>"""
        for url, dt, changefreq in urls
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{entries}
</urlset>
"""


def render_robots():
    return f"""User-agent: *
Allow: /
Disallow: {STATS_DASHBOARD_PATH}
Disallow: {METRICS_PATH}

Sitemap: {site_url("/sitemap.xml")}
Host: {public_url_host()}
"""


def render_llms(items):
    lines = [
        f"# {SITE_AUTHOR}",
        "",
        f"> {SITE_DESCRIPTION}",
        "",
        "## Основное",
        "",
        f"- Сайт: {site_url('/')}",
        f"- Telegram: {TELEGRAM_URL}",
        f"- X / Twitter: {X_PROFILE_URL}",
        f"- RSS: {site_url('/feed.xml')}",
        f"- Sitemap: {site_url('/sitemap.xml')}",
        "",
        "## Последние посты",
        "",
    ]
    if not items:
        lines.append("- Постов пока нет.")
    for item in items:
        date = format_date(item.get("date"))
        lines.append(f"- [{post_title(item)}]({site_url(post_path(item))}) — {date} MSK")
    return "\n".join(lines).rstrip() + "\n"


def metric_beacon_script():
    return """<script>
(() => {
    const payload = JSON.stringify({ path: window.location.pathname || "/" });
    try {
        if (navigator.sendBeacon) {
            navigator.sendBeacon("/stats/pageview", new Blob([payload], { type: "application/json" }));
            return;
        }
        fetch("/stats/pageview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: payload,
            keepalive: true,
            credentials: "omit",
            cache: "no-store"
        });
    } catch (_) {}
})();
</script>"""


def render_post_page(item):
    title = post_title(item)
    description = post_description(item)
    local_url = site_url(post_path(item))
    telegram_url = item.get("url", TELEGRAM_URL)
    date_iso = html.escape(item.get("date", ""))
    date_label = html.escape(format_date(item.get("date")))
    body = item.get("html") or text_to_html(item.get("text", ""))
    
    image_html = ""
    if item.get("image"):
        image_url = "/" + html.escape(item["image"])
        image_html = f'<div class="telegram-post__image-wrap" style="margin-bottom: 1.5rem; border-radius: 8px; overflow: hidden; border: 1px solid var(--border); max-width: 100%; background: #000; display: flex; justify-content: center;"><img src="{image_url}" class="telegram-post__image" alt="Изображение" style="max-width: 100%; max-height: 600px; height: auto; display: block; object-fit: contain;"></div>'
        
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description,
        "url": local_url,
        "datePublished": item.get("date"),
        "dateModified": item.get("date"),
        "inLanguage": "ru-RU",
        "author": {"@type": "Person", "name": SITE_AUTHOR, "url": site_url("/")},
        "publisher": {"@type": "Person", "name": SITE_AUTHOR, "url": site_url("/")},
        "mainEntityOfPage": local_url,
        "isBasedOn": telegram_url,
    }
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)} | {html.escape(SITE_AUTHOR)}</title>
    <meta name="description" content="{html.escape(description, quote=True)}">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="{local_url}">
    <link rel="alternate" type="application/rss+xml" title="{html.escape(SITE_TITLE, quote=True)}" href="{site_url("/feed.xml")}">
    <meta property="og:type" content="article">
    <meta property="og:site_name" content="{html.escape(SITE_AUTHOR, quote=True)}">
    <meta property="og:title" content="{html.escape(title, quote=True)}">
    <meta property="og:description" content="{html.escape(description, quote=True)}">
    <meta property="og:url" content="{local_url}">
    <meta property="og:image" content="{site_url("/avatar.png")}">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="{html.escape(title, quote=True)}">
    <meta name="twitter:description" content="{html.escape(description, quote=True)}">
    <meta name="twitter:image" content="{site_url("/avatar.png")}">
    <script type="application/ld+json">{json_ld(schema)}</script>
    <style>
        :root {{ --bg-color: #0d1117; --card-bg: #161b22; --text-main: #c9d1d9; --text-header: #ffffff; --accent: #58a6ff; --accent-green: #3fb950; --border: #30363d; --font-mono: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }}
        body {{ margin: 0; background: var(--bg-color); color: var(--text-main); font: 18px/1.65 var(--font-sans); }}
        a {{ color: var(--accent); text-decoration: none; border-bottom: 1px solid transparent; }}
        a:hover {{ border-bottom-color: var(--accent); }}
        main {{ max-width: 900px; margin: 0 auto; padding: 3rem 1.5rem; }}
        .top {{ display: flex; align-items: center; gap: 1rem; margin-bottom: 2rem; }}
        .avatar {{ width: 58px; height: 58px; border-radius: 50%; border: 1px solid var(--border); object-fit: cover; }}
        .name {{ color: var(--text-header); font: 700 1.2rem var(--font-mono); }}
        .tagline, .meta {{ color: #8b949e; font-family: var(--font-mono); font-size: 0.88rem; }}
        article {{ border: 1px solid var(--border); border-radius: 8px; background: var(--card-bg); padding: 1.25rem; }}
        .meta {{ display: flex; justify-content: space-between; gap: 1rem; margin-bottom: 1rem; }}
        h1 {{ margin: 0 0 1rem; color: var(--text-header); font: 700 1.8rem/1.25 var(--font-mono); }}
        .body {{ margin: 0; }}
        .back {{ display: inline-block; margin-top: 1.5rem; font-family: var(--font-mono); }}
        @media (max-width: 720px) {{ main {{ padding: 1.25rem 1rem; }} body {{ font-size: 16px; }} .meta {{ display: block; }} h1 {{ font-size: 1.35rem; }} }}
    </style>
</head>
<body>
<main>
    <div class="top">
        <a href="/"><img class="avatar" src="/avatar.png" alt="{html.escape(SITE_AUTHOR)}"></a>
        <div>
            <div class="name">{html.escape(SITE_AUTHOR)}</div>
            <div class="tagline">Сливы и новости ИИ</div>
        </div>
    </div>
    <article>
        <div class="meta">
            <span><a href="{html.escape(telegram_url)}" target="_blank" rel="noopener">Telegram</a> / @{html.escape(CHANNEL_USERNAME)}</span>
            <time datetime="{date_iso}">{date_label} MSK</time>
        </div>
        <h1>{html.escape(title)}</h1>
        {image_html}
        <p class="body">{body}</p>
    </article>
    <a class="back" href="/">← На главную</a>
</main>
{metric_beacon_script()}
</body>
</html>
"""


def render_post_pages(items):
    if PUBLIC_POSTS_DIR.exists():
        shutil.rmtree(PUBLIC_POSTS_DIR)
    for item in items:
        path = PUBLIC_POSTS_DIR / str(int(item.get("message_id") or 0)) / "index.html"
        atomic_write(path, render_post_page(item), permissions=0o664)


def indexnow_key():
    if INDEXNOW_KEY_FILE.exists():
        key = INDEXNOW_KEY_FILE.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[A-Fa-f0-9-]{8,128}", key):
            return key
    key = secrets.token_hex(16)
    atomic_write(INDEXNOW_KEY_FILE, key + "\n", permissions=0o600)
    return key


def ping_indexnow(urls):
    if os.environ.get("INDEXNOW_ENABLED", "1").lower() in {"0", "false", "no"}:
        return
    key = indexnow_key()
    atomic_write(SITE_ROOT / f"{key}.txt", key + "\n", permissions=0o664)
    urls = sorted(dict.fromkeys(urls))
    digest = hashlib.sha256("\n".join(urls).encode("utf-8")).hexdigest()
    state = {}
    if INDEXNOW_STATE_JSON.exists():
        try:
            state = json.loads(INDEXNOW_STATE_JSON.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    if state.get("last_digest") == digest:
        return
    state = {"last_digest": digest, "last_attempt_at": now_iso(), "url_count": len(urls)}
    atomic_write(INDEXNOW_STATE_JSON, json.dumps(state, ensure_ascii=False, indent=2) + "\n", permissions=0o600)
    payload = {
        "host": public_url_host(),
        "key": key,
        "keyLocation": site_url(f"/{key}.txt"),
        "urlList": urls[:100],
    }
    req = urllib.request.Request(
        "https://api.indexnow.org/indexnow",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            state["last_status"] = response.status
            state["last_success_at"] = now_iso()
            atomic_write(INDEXNOW_STATE_JSON, json.dumps(state, ensure_ascii=False, indent=2) + "\n", permissions=0o600)
            log(f"IndexNow ping: {response.status}, urls: {len(payload['urlList'])}")
    except Exception as exc:
        log(f"IndexNow пропущен после ошибки: {exc}")


def render_static_outputs(items):
    publish_public_feed()
    render_post_pages(items)
    atomic_write(PUBLIC_RSS, render_rss(items), permissions=0o664)
    atomic_write(PUBLIC_SITEMAP, render_sitemap(items), permissions=0o664)
    atomic_write(PUBLIC_ROBOTS, render_robots(), permissions=0o664)
    atomic_write(PUBLIC_LLMS, render_llms(items), permissions=0o664)
    urls = [site_url("/"), site_url("/feed.xml"), site_url("/llms.txt"), *[site_url(post_path(item)) for item in items]]
    ping_indexnow(urls)


def feed_css():
    return f"""{CSS_START}
        #news {{
            padding-top: 0;
            padding-bottom: 1rem;
            border-bottom: none;
        }}

        .telegram-feed {{
            margin-top: 0;
            display: grid;
            gap: 1rem;
        }}

        .telegram-post {{
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--card-bg);
            padding: 1rem;
        }}

        .telegram-post__meta {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            color: #8b949e;
            font-family: var(--font-mono);
            font-size: 0.78rem;
            margin-bottom: 0.75rem;
        }}

        .telegram-post__body {{
            margin: 0;
            color: var(--text-main);
        }}

        .telegram-post__image-wrap {{
            margin-top: 1rem;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--border);
            max-width: 420px;
            display: inline-block;
            vertical-align: top;
        }}

        .telegram-post__image {{
            max-width: 420px;
            width: 100%;
            height: auto;
            display: block;
            object-fit: cover;
            transition: transform 0.3s ease;
        }}

        .telegram-post__image:hover {{
            transform: scale(1.02);
        }}

        .telegram-feed__empty {{
            border: 1px dashed var(--border);
            border-radius: 8px;
            padding: 1rem;
            color: #8b949e;
            background: rgba(22, 27, 34, 0.55);
        }}

        @media (max-width: 720px) {{
            .telegram-post__meta {{
                display: block;
            }}
        }}
{CSS_END}"""


def render_items(items):
    if not items:
        return '            <div class="telegram-feed__empty">Лента подключена. Новые посты из Telegram появятся здесь автоматически.</div>'
    chunks = []
    for item in items:
        date = html.escape(format_date(item.get("date")))
        body = item.get("html") or text_to_html(item.get("text", ""))
        url = html.escape(item.get("url", f"https://t.me/{CHANNEL_USERNAME}"))
        
        image_html = ""
        if item.get("image"):
            image_url = html.escape(item["image"])
            image_html = (
                "\n            <div class=\"telegram-post__image-wrap\"><img src=\"" + image_url
                + "\" class=\"telegram-post__image\" alt=\"Изображение поста\" loading=\"lazy\"></div>"
            )
        chunks.append(
            f"""            <article class="telegram-post">
                <div class="telegram-post__meta">
                    <span><a href="{url}" target="_blank" rel="noopener">Telegram</a> / @{html.escape(CHANNEL_USERNAME)}</span>
                    <time datetime="{html.escape(item.get("date", ""))}">{date} MSK</time>
                </div>
                <p class="telegram-post__body">{body}</p>{image_html}
            </article>"""
        )
    return "\n".join(chunks)


def feed_section(items):
    return f"""{SECTION_START}
    <section id="news">
        <div class="telegram-feed">
{ITEMS_START}
{render_items(items)}
{ITEMS_END}
        </div>
    </section>
{SECTION_END}"""


def ensure_css(document):
    css = feed_css()
    if CSS_START in document and CSS_END in document:
        return re.sub(
            re.escape(CSS_START) + r".*?" + re.escape(CSS_END),
            css,
            document,
            flags=re.S,
        )
    return document.replace("    </style>", css + "\n    </style>")


def run_astro_build():
    import subprocess
    import sys
    project_root = Path(os.environ.get("SOURCE_INDEX", "/home/deploy/repos/ialexey-web/index.html")).parent
    
    log(f"Запуск сборки Astro в директории: {project_root}")
    env = os.environ.copy()
    if sys.platform != "win32":
        env["PATH"] = "/usr/bin:/usr/local/bin:/opt/homebrew/bin:" + env.get("PATH", "")
        
    try:
        res = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            env=env
        )
        if res.returncode != 0:
            log(f"Ошибка сборки Astro: {res.stderr}")
            return False
            
        log("Сборка Astro успешно завершена.")
        
        dist_dir = project_root / "dist"
        site_root = Path(os.environ.get("SITE_ROOT", "/home/deploy/ialexey-web"))
        
        if dist_dir.exists() and site_root.exists() and dist_dir.resolve() != site_root.resolve():
            log(f"Синхронизация собранных файлов из {dist_dir} в {site_root}...")
            sync_res = subprocess.run(
                ["rsync", "-a", "--delete", "--exclude", "media", "--exclude", "stats", f"{dist_dir}/", f"{site_root}/"],
                capture_output=True,
                text=True
            )
            if sync_res.returncode == 0:
                log("Синхронизация завершена успешно.")
            else:
                log(f"Ошибка синхронизации: {sync_res.stderr}")
        return True
    except Exception as exc:
        log(f"Исключение при сборке Astro: {exc}")
        return False


def render_site(items=None):
    items = items if items is not None else load_feed()
    publish_public_feed()
    run_astro_build()
    
    # Пинг поисковых систем через IndexNow
    try:
        urls = [site_url("/"), site_url("/feed.xml"), site_url("/llms.txt"), *[site_url(post_path(item)) for item in items]]
        ping_indexnow(urls)
    except Exception as exc:
        log(f"Ошибка IndexNow: {exc}")



def telegram_api(method, payload=None):
    token = require_env("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def set_webhook():
    secret = require_env("TELEGRAM_WEBHOOK_SECRET")
    payload = {
        "url": PUBLIC_BASE_URL + WEBHOOK_PATH,
        "allowed_updates": ["channel_post", "edited_channel_post"],
        "secret_token": secret,
        "drop_pending_updates": False,
    }
    result = telegram_api("setWebhook", payload)
    if not result.get("ok"):
        raise SystemExit(f"Telegram setWebhook failed: {result}")
    log("Telegram webhook установлен")


def webhook_info():
    result = telegram_api("getWebhookInfo")
    safe = result.copy()
    if isinstance(safe.get("result"), dict) and safe["result"].get("url"):
        safe["result"]["url"] = safe["result"]["url"].replace(PUBLIC_BASE_URL, PUBLIC_BASE_URL)
    print(json.dumps(safe, ensure_ascii=False, indent=2))


class Handler(BaseHTTPRequestHandler):
    server_version = "ialexey-feed/1.0"

    def log_message(self, fmt, *args):
        log("%s - %s" % (self.address_string(), fmt % args))

    def send_text(self, status, text):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, status, text):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_no_content(self):
        self.send_response(204)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        if self.path == "/tg-feed/healthz":
            self.send_text(200, "ok\n")
            return
        if self.path.split("?", 1)[0] == STATS_DASHBOARD_PATH:
            self.send_html(200, metrics_dashboard())
            return
        self.send_text(404, "not found\n")

    def do_POST(self):
        if self.path.split("?", 1)[0] == METRICS_PATH:
            length = min(int(self.headers.get("Content-Length", "0") or "0"), 1024)
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                record_pageview(payload.get("path", "/"))
            except Exception as exc:
                log(f"Ошибка metrics: {exc}")
            self.send_no_content()
            return
        if self.path.split("?", 1)[0] != WEBHOOK_PATH:
            self.send_text(404, "not found\n")
            return
        expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        received = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not expected or received != expected:
            self.send_text(403, "forbidden\n")
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            update = json.loads(raw.decode("utf-8"))
            message = update.get("channel_post") or update.get("edited_channel_post")
            if message:
                item = message_to_item(message, edited="edited_channel_post" in update)
                if item:
                    upsert_item(item)
                    log(f"Принят Telegram post {item['message_id']}")
            self.send_text(200, "ok\n")
        except Exception as exc:
            log(f"Ошибка webhook: {exc}")
            self.send_text(200, "ok\n")


def serve():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    render_site(load_feed())
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log(f"Слушаю 127.0.0.1:{PORT}{WEBHOOK_PATH}")
    httpd.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Лента Telegram для ialexey.ru")
    parser.add_argument("command", choices=["serve", "render", "seed-public", "set-webhook", "webhook-info"])
    args = parser.parse_args()

    if args.command == "serve":
        serve()
    elif args.command == "render":
        render_site()
    elif args.command == "seed-public":
        seed_public()
    elif args.command == "set-webhook":
        set_webhook()
    elif args.command == "webhook-info":
        webhook_info()


if __name__ == "__main__":
    main()
