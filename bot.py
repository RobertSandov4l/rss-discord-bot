from datetime import datetime, timezone
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


def extraer_enlace_juego(entry, texto_html):
    enlace = (entry.get("link") or "").strip()
    if "store.steampowered.com/app/" in enlace:
        return enlace

    match_app = re.search(
        r"https?://store\.steampowered\.com/(?:app|curator)/[^\s\"'<>]+",
        texto_html or "",
    )
    if match_app:
        return match_app.group(0)

    return enlace


def extraer_titulo_limpio(titulo_raw, enlace):
    titulo = (titulo_raw or "").strip()
    if not titulo or titulo.lower() == "featured":
        match_slug = re.search(r"store\.steampowered\.com/app/\d+/([^/?#]+)", enlace or "")
        if match_slug:
            return match_slug.group(1).replace("_", " ").replace("-", " ")[:256]
    return (titulo or "Nueva publicación")[:256]


def limpiar_html(texto):
    limpio = re.sub(r"<[^>]+>", " ", texto or "")
    limpio = re.sub(
        r"\b(?:Live)?\d+[.,]\d{2}\s*€|\$\s*\d+[.,]\d{2}",
        " ",
        limpio,
        flags=re.IGNORECASE,
    )
    return " ".join(limpio.split())[:350]


def obtener_autor(entry, feed_cfg, texto_plano=""):
    if feed_cfg.get("autor"):
        return str(feed_cfg["autor"]).strip()[:256]
    if entry.get("author"):
        return str(entry.get("author")).strip()[:256]
    if entry.get("dc_creator"):
        return str(entry.get("dc_creator")).strip()[:256]
    if entry.get("authors") and isinstance(entry.get("authors"), list):
        nombre = entry["authors"][0].get("name")
        if nombre:
            return str(nombre).strip()[:256]

    match_autor = re.search(r"\b(?:Por|Autor|By)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ0-9_.-]{2,30})", texto_plano)
    if match_autor:
        return match_autor.group(1).strip()[:256]

    return ""


def obtener_fecha_texto(entry):
    tiempo = entry.get("published_parsed") or entry.get("updated_parsed")
    if tiempo:
        try:
            dt = datetime(*tiempo[:6], tzinfo=timezone.utc)
            return dt.strftime("%d/%m/%Y %H:%M UTC")
        except Exception:
            pass
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


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
        if not feed_cfg.get("activo", True):
            print(f"Feed desactivado (activo=false): {feed_cfg.get('nombre', 'Sin nombre')}")
            continue

        parsed = feedparser.parse(feed_cfg["rss_url"])
        if not parsed.entries:
            print(f"Sin entradas en el feed: {feed_cfg.get('nombre', 'Sin nombre')}")
            continue

        entradas_nuevas = [
            e
            for e in reversed(parsed.entries[:8])
            if (e.get("id") or e.get("link"))
            and (e.get("id") or e.get("link")) not in historial
        ]

        if not entradas_nuevas:
            print(f"Sin novedades en {feed_cfg.get('nombre', 'Feed')}.")
            continue

        for entry in entradas_nuevas:
            uid = entry.get("id") or entry.get("link")

            bloque_raw = " ".join([
                entry.get("summary", ""),
                entry.get("description", ""),
                " ".join(c.get("value", "") for c in entry.get("content", [])),
            ])

            enlace = extraer_enlace_juego(entry, bloque_raw)
            titulo = extraer_titulo_limpio(entry.get("title"), enlace)
            resumen = limpiar_html(bloque_raw)
            imagen = obtener_imagen(entry, enlace)
            autor = obtener_autor(entry, feed_cfg, bloque_raw)
            fecha_texto = obtener_fecha_texto(entry)
            base_pie = str(feed_cfg.get("pie_pagina") or "Publicado en Juego Hispano").strip()
            pie_texto = f"{base_pie} • {fecha_texto}"[:2048]

            embed = {
                "title": titulo,
                "url": enlace,
                "description": resumen,
                "color": feed_cfg.get("color", 3447003),
                "footer": {"text": pie_texto},
            }
            if autor:
                embed["author"] = {"name": autor}
            if imagen:
                embed["image"] = {"url": imagen}

            payload = {
                "content": feed_cfg.get("mencion", ""),
                "embeds": [embed],
            }

            time.sleep(2)
            url_api = f"https://discord.com/api/v10/channels/{feed_cfg['channel_id']}/messages"
            resp = requests.post(url_api, headers=headers, json=payload, timeout=15)
            if resp.status_code in (200, 204):
                historial.append(uid)
                cambios = True
                print(f"Publicado: {titulo}")
            else:
                print(f"Error al publicar ({resp.status_code}): {resp.text}")

    if cambios:
        with open(HISTORIAL_FILE, "w", encoding="utf-8") as f:
            json.dump(historial[-1000:], f, indent=2)


if __name__ == "__main__":
    main()
