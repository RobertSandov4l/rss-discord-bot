from datetime import datetime, timezone
import json
import os
import re
import time
import feedparser
import requests

HISTORIAL_FILE = "historial.json"
LOG_FILE = "log_envios.json"
ROTACION_FILE = "rotacion_imagenes.json"


def cargar_lista_json(ruta):
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read().strip()
                if not contenido:
                    return []
                datos = json.loads(contenido)
                return datos if isinstance(datos, list) else []
        except Exception as e:
            print(f"Aviso al leer {ruta}: {e}. Se iniciara lista vacia.")
            return []
    return []


def guardar_lista_json(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)


def cargar_dict_json(ruta):
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read().strip()
                if not contenido:
                    return {}
                datos = json.loads(contenido)
                return datos if isinstance(datos, dict) else {}
        except Exception:
            return {}
    return {}


def guardar_dict_json(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)


def parsear_color(valor_color, defecto=7225568):
    if isinstance(valor_color, int):
        return valor_color
    if isinstance(valor_color, str):
        limpio = valor_color.strip().lstrip("#")
        if re.fullmatch(r"[0-9a-fA-F]{6}", limpio):
            return int(limpio, 16)
        if limpio.isdigit():
            return int(limpio)
    return defecto


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
    return (titulo or "Nueva publicacion")[:256]


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

    match_autor = re.search(
        r"\b(?:Por|Autor|By)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ0-9_.-]{2,30})",
        texto_plano,
    )
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


def buscar_og_image_en_url(url_objetivo):
    if not url_objetivo or not url_objetivo.startswith("http"):
        return None
    try:
        resp = requests.get(
            url_objetivo,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
            allow_redirects=True,
        )
        if not resp.ok:
            return None
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
            return og_match.group(1).strip()
    except Exception:
        pass
    return None


def obtener_imagen_rotativa(feed_cfg, rotacion_state):
    lista_imgs = feed_cfg.get("imagenes")
    if not isinstance(lista_imgs, list) or not lista_imgs:
        return None
    urls_validas = [str(u).strip() for u in lista_imgs if str(u).strip().startswith("http")]
    if not urls_validas:
        return None

    clave_feed = str(feed_cfg.get("nombre") or feed_cfg.get("rss_url") or "default")
    idx_actual = int(rotacion_state.get(clave_feed, 0)) % len(urls_validas)
    imagen_elegida = urls_validas[idx_actual]
    rotacion_state[clave_feed] = (idx_actual + 1) % len(urls_validas)
    return imagen_elegida


def obtener_imagen(entry, enlace, feed_cfg, rotacion_state, cambios_rotacion_ref):
    # 1. Si el feed tiene lista de imagenes rotativas y esta activada (por defecto True si existe la lista)
    usar_rotacion = feed_cfg.get("rotar_imagenes", True)
    if usar_rotacion and isinstance(feed_cfg.get("imagenes"), list) and feed_cfg["imagenes"]:
        img_rot = obtener_imagen_rotativa(feed_cfg, rotacion_state)
        if img_rot:
            cambios_rotacion_ref[0] = True
            return img_rot

    # 2. Imagen directa en campos multimedia del RSS
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
    match_img = re.search(
        r'<img[^>]+(?:data-src|data-lazy-src|src)=["\']([^"\']+)["\']',
        texto_completo,
        re.IGNORECASE,
    )
    if match_img and match_img.group(1).startswith("http"):
        return match_img.group(1)

    # 3. Intentar obtener og:image de enlaces externos dentro del texto del anuncio
    urls_en_texto = re.findall(r"https?://[^\s\"'<>)\]]+", texto_completo)
    for u in urls_en_texto:
        if "steamcommunity.com" in u or "steampowered.com" in u:
            continue
        og = buscar_og_image_en_url(u)
        if og:
            return og

    # 4. Respaldo final en el enlace principal de la entrada
    if enlace:
        og_principal = buscar_og_image_en_url(enlace)
        if og_principal:
            return og_principal

    return None


def main():
    bot_token = os.environ["DISCORD_BOT_TOKEN"]
    feeds = json.loads(os.environ["FEEDS_JSON"])
    solo_semilla = os.environ.get("SEMILLA_SIN_ENVIAR", "false").lower() == "true"

    historial = cargar_lista_json(HISTORIAL_FILE)
    log_envios = cargar_lista_json(LOG_FILE)
    rotacion_state = cargar_dict_json(ROTACION_FILE)

    cambios_historial = False
    cambios_log = False
    cambios_rotacion = [False]

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

            if solo_semilla:
                historial.append(uid)
                cambios_historial = True
                print(f"[SEMILLA] Registrado sin enviar: {uid}")
                continue

            bloque_raw = " ".join([
                entry.get("summary", ""),
                entry.get("description", ""),
                " ".join(c.get("value", "") for c in entry.get("content", [])),
            ])

            enlace = extraer_enlace_juego(entry, bloque_raw)
            titulo = extraer_titulo_limpio(entry.get("title"), enlace)
            resumen = limpiar_html(bloque_raw)
            imagen = obtener_imagen(entry, enlace, feed_cfg, rotacion_state, cambios_rotacion)
            autor = obtener_autor(entry, feed_cfg, bloque_raw)
            fecha_texto = obtener_fecha_texto(entry)
            base_pie = str(feed_cfg.get("pie_pagina") or "Publicado en Juego Hispano").strip()
            pie_texto = f"{base_pie} • {fecha_texto}"[:2048]
            color_embed = parsear_color(feed_cfg.get("color"), defecto=7225568)
            pie_icono = (feed_cfg.get("pie_icono") or "https://i.imgur.com/2osEkLR.png").strip()

            footer_obj = {"text": pie_texto}
            if pie_icono:
                footer_obj["icon_url"] = pie_icono

            embed = {
                "title": titulo,
                "url": enlace,
                "description": resumen,
                "color": color_embed,
                "footer": footer_obj,
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
                cambios_historial = True

                log_envios.append({
                    "fecha_envio_utc": datetime.now(timezone.utc).isoformat(),
                    "feed": feed_cfg.get("nombre", ""),
                    "channel_id": str(feed_cfg.get("channel_id", "")),
                    "titulo": titulo,
                    "enlace": enlace,
                    "uid": uid,
                })
                cambios_log = True
                print(f"Publicado: {titulo}")
            else:
                print(f"Error al publicar ({resp.status_code}): {resp.text}")

    if cambios_historial:
        guardar_lista_json(HISTORIAL_FILE, historial[-1000:])
    if cambios_log:
        guardar_lista_json(LOG_FILE, log_envios[-2000:])
    if cambios_rotacion[0]:
        guardar_dict_json(ROTACION_FILE, rotacion_state)


if __name__ == "__main__":
    main()
