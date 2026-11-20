import json
import os
import re
import time
import feedparser
import requests

HISTORIAL_FILE = "historial.json"


def cargar_historial():
    if os.path.exists(HISTORIAL_FILE):
        with open(HISTORIAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def limpiar_html(texto):
    limpio = re.sub(r"<[^>]+>", " ", texto or "")
    return " ".join(limpio.split())[:350]


def obtener_imagen(entry, enlace):
    if "media_content" in entry and entry.media_content:
        url = entry.media_content[0].get("url")
        if url:
            return url
    if "media_thumbnail" in entry and entry.media_thumbnail:
        url = entry.media_thumbnail[0].get("url")
        if url:
            return url

    for coleccion in (entry.get("enclosures", []), entry.get("links", [])):
        for item in coleccion:
            if item.get("type", "").startswith("image/") and item.get("href"):
                return item.get("href")

    bloques_html = [
        entry.get("summary", ""),
        entry.get("description", ""),
    ]
    if "content" in entry:
        bloques_html.extend(c.get("value", "") for c in entry.content)

    texto_completo = " ".join(bloques_html)
    match = re.search(
        r'<img[^>]+(?:data-src|data-lazy-src|src)=["\']([^"\']+)["\']',
        texto_completo,
        re.IGNORECASE,
    )
    if match and match.group(1).startswith("http"):
        return match.group(1)

    if enlace:
        try:
            resp = requests.get(enlace, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            og_match = re.search(
                r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                resp.text,
                re.IGNORECASE,
            )
            if not og_match:
                og_match = re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\']',
                    resp.text,
                    re.IGNORECASE,
                )
            if og_match and og_match.group(1).startswith("http"):
                return og_match.group(1)
        except Exception:
            pass

    return None


def main():
    bot_token = os.environ["DISCORD_BOT_TOKEN"]
    feeds = json.loads(os.environ["FEEDS_JSON"])
    historial = cargar_historial()
    cambios = False

    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }

    for feed_cfg in feeds:
        parsed = feedparser.parse(feed_cfg["rss_url"])
        entradas = list(reversed(parsed.entries[:5]))

        for entry in entradas:
            uid = entry.get("id") or entry.get("link")
            if not uid or uid in historial:
                continue

            titulo = entry.get("title", "Nueva publicación")[:256]
            enlace = entry.get("link", "")
            resumen = limpiar_html(entry.get("summary") or entry.get("description", ""))
            imagen = obtener_imagen(entry, enlace)

            print("DEBUG TITULO:", titulo)
            print("DEBUG ENLACE:", enlace)
            print("DEBUG RESUMEN:", resumen)
            print("DEBUG IMAGEN:", imagen)

            embed = {
                "title": titulo,
                "url": enlace,
                "description": resumen,
                "color": feed_cfg.get("color", 3447003),
            }
            if imagen:
                embed["image"] = {"url": imagen}

            payload = {
                "content": feed_cfg.get("mencion", ""),
                "embeds": [embed],
            }

            url_api = f"https://discord.com/api/v10/channels/{feed_cfg['channel_id']}/messages"
            resp = requests.post(url_api, headers=headers, json=payload, timeout=15)
            if resp.status_code in (200, 204):
                historial.append(uid)
                cambios = True
                time.sleep(1.5)

    if cambios:
        with open(HISTORIAL_FILE, "w", encoding="utf-8") as f:
            json.dump(historial[-1000:], f, indent=2)


if __name__ == "__main__":
    main()
