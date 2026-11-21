from datetime import datetime, timezone
import json
import os
import random
import re
import time
import unicodedata
import urllib.parse
import feedparser
import requests

HISTORIAL_FILE = "historial.json"
LOG_FILE = "log_envios.json"
LOGS_DIR = "logs"
ROTACION_FILE = "rotacion_imagenes.json"
IMAGEN_ULTIMO_RECURSO = "https://i.imgur.com/bBgeQQs.jpeg"

HEADERS_WEB = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


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
    carpeta = os.path.dirname(ruta)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)


def slug_feed(nombre_feed):
    texto = str(nombre_feed or "feed-sin-nombre").strip().lower()
    normalizado = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(c for c in normalizado if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9]+", "-", sin_acentos).strip("-")
    return limpio or "feed-sin-nombre"


def ruta_log_feed(nombre_feed):
    return os.path.join(LOGS_DIR, f"{slug_feed(nombre_feed)}.json")


def normalizar_url_limpia(url):
    u = (url or "").strip()
    if not u:
        return ""
    u = u.split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()
    return u


def extraer_appid_steam(texto):
    match = re.search(
        r"store\.steampowered\.com/app/(\d+)", texto or "", flags=re.IGNORECASE
    )
    if match:
        return match.group(1)
    match_uid = re.search(
        r"store-steampowered-com-app-(\d+)", texto or "", flags=re.IGNORECASE
    )
    if match_uid:
        return match_uid.group(1)
    return ""


def obtener_claves_entrada(entry, bloque_raw=""):
    uid = (entry.get("id") or entry.get("link") or "").strip()
    link = (entry.get("link") or "").strip()
    titulo = re.sub(r"\s+", " ", (entry.get("title") or "").strip().lower())
    claves = []

    if uid:
        claves.append(uid)

    url_limpia = normalizar_url_limpia(link)
    if url_limpia and url_limpia not in claves:
        claves.append(url_limpia)

    appid = extraer_appid_steam(f"{uid} {link} {bloque_raw}")
    if appid:
        clave_app = f"steam_app:{appid}"
        if clave_app not in claves:
            claves.append(clave_app)

    if titulo and (url_limpia or appid):
        clave_titulo_ref = f"item:{titulo}|{appid or url_limpia}"
        if clave_titulo_ref not in claves:
            claves.append(clave_titulo_ref)

    return claves


def ya_registrado(claves_entrada, historial_set):
    return any(c in historial_set for c in claves_entrada)


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


def extraer_enlace_resena(entry, texto_html, enlace_juego=""):
    link_entry = (entry.get("link") or "").strip()
    if link_entry.startswith("http") and "store.steampowered.com/app/" not in link_entry:
        return link_entry

    urls = re.findall(r"https?://[^\s\"'<>)\]]+", texto_html or "")
    for u in urls:
        if any(
            pat in u.lower()
            for pat in (
                "steamcommunity.com/groups/",
                "steamcommunity.com/id/",
                "steamcommunity.com/profiles/",
                "store.steampowered.com/curator/",
                "juegohispano.com",
            )
        ):
            return u

    if link_entry.startswith("http"):
        return link_entry
    if enlace_juego and enlace_juego.startswith("http"):
        return enlace_juego
    return ""


def extraer_titulo_limpio(titulo_raw, enlace):
    titulo = (titulo_raw or "").strip()
    if not titulo or titulo.lower() == "featured":
        match_slug = re.search(
            r"store\.steampowered\.com/app/\d+/([^/?#]+)", enlace or ""
        )
        if match_slug:
            return match_slug.group(1).replace("_", " ").replace("-", " ")[:256]
    return (titulo or "Nueva publicacion")[:256]


def deduplicar_texto_repetido(texto):
    limpio = " ".join((texto or "").split()).strip()
    if not limpio:
        return ""

    mitad = len(limpio) // 2
    for delta in range(-25, 26):
        corte = mitad + delta
        if 20 < corte < len(limpio) - 10:
            parte_a = limpio[:corte].strip(" .;-")
            parte_b = limpio[corte:].strip(" .;-")
            if parte_a and parte_a.lower() == parte_b.lower():
                limpio = limpio[:corte].strip()
                break

    segmentos = [
        s.strip() for s in re.split(r"(?<=[.!?])\s+", limpio) if s.strip()
    ]
    resultado = []
    claves_vistas = set()
    for seg in segmentos:
        clave = re.sub(r"[^a-z0-9áéíóúñ]+", "", seg.lower())
        if len(clave) >= 15 and clave in claves_vistas:
            continue
        if (
            resultado
            and re.sub(r"[^a-z0-9áéíóúñ]+", "", resultado[-1].lower()) == clave
        ):
            continue
        resultado.append(seg)
        if len(clave) >= 15:
            claves_vistas.add(clave)

    return " ".join(resultado).strip()


def limpiar_html(texto, url_resena="", etiqueta_enlace="Juego Hispano"):
    raw = texto or ""

    # Convierte etiquetas <a href="URL">texto</a> a enlaces Markdown [texto](URL)
    def reemplazar_link(match):
        href = match.group(1).strip()
        etiqueta = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if href.startswith("http") and etiqueta:
            return f"[{etiqueta}]({href})"
        return etiqueta

    con_links = re.sub(
        r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        reemplazar_link,
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Quita el resto de etiquetas HTML y precios
    limpio = re.sub(r"<[^>]+>", " ", con_links)
    limpio = re.sub(
        r"\b(?:Live)?\d+[.,]\d{2}\s*€|\$\s*\d+[.,]\d{2}",
        " ",
        limpio,
        flags=re.IGNORECASE,
    )
    limpio = " ".join(limpio.split())

    # Si aparece [Juego Hispano](url) o "Juego Hispano", corta justo ahi para evitar texto duplicado
    match_jh_link = re.search(
        r"(\[Juego\s+Hispano\]\(https?://[^\s)]+\))",
        limpio,
        flags=re.IGNORECASE,
    )
    if match_jh_link:
        limpio = limpio[: match_jh_link.end()]
    else:
        match_jh_texto = re.search(
            r"\bJuego\s+Hispano\b", limpio, flags=re.IGNORECASE
        )
        if match_jh_texto:
            limpio = limpio[: match_jh_texto.end()]

    limpio = deduplicar_texto_repetido(limpio)

    # Si el texto no tiene ya el enlace de Juego Hispano y contamos con url_resena, lo agregamos al final
    etiqueta = (etiqueta_enlace or "Juego Hispano").strip()
    if url_resena and url_resena.startswith("http"):
        if not re.search(
            rf"\[{re.escape(etiqueta)}\]\(https?://[^\s)]+\)",
            limpio,
            flags=re.IGNORECASE,
        ):
            limpio = re.sub(
                rf"\s*\b{re.escape(etiqueta)}\b\s*$",
                "",
                limpio,
                flags=re.IGNORECASE,
            ).strip()
            sufijo = f" [{etiqueta}]({url_resena})"
            max_base = max(0, 600 - len(sufijo))
            limpio = f"{limpio[:max_base].rstrip()}{sufijo}"

    return limpio[:600]


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


def url_imagen_accesible(url):
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return False
    try:
        resp = requests.head(
            url, headers=HEADERS_WEB, timeout=6, allow_redirects=True
        )
        if resp.status_code == 200:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "image" in ctype or not ctype:
                return True
        if resp.status_code in (403, 405):
            rget = requests.get(
                url,
                headers=HEADERS_WEB,
                timeout=8,
                stream=True,
                allow_redirects=True,
            )
            ok = rget.status_code == 200 and "image" in (
                rget.headers.get("Content-Type") or ""
            ).lower()
            rget.close()
            return ok
    except Exception:
        return False
    return False


def buscar_imagen_por_appid_en_texto(texto_y_enlace):
    matches = re.findall(
        r"https?://store\.steampowered\.com/app/(\d+)",
        texto_y_enlace or "",
        flags=re.IGNORECASE,
    )
    for appid in matches:
        header_url = (
            f"https://shared.akamai.steamstatic.com/"
            f"store_item_assets/steam/apps/{appid}/header.jpg"
        )
        if url_imagen_accesible(header_url):
            return header_url
    return None


def extraer_posible_juego(titulo, descripcion_limpia):
    texto_titulo = (titulo or "").strip()

    if ":" in texto_titulo:
        tras_dos_puntos = texto_titulo.split(":", 1)[1].strip()
        candidato_colon = re.split(
            r"\b(?:para\s+pc|para\s+android|para\s+ios|para\s+steam|para\s+xbox|para\s+nintendo|para\s+ps\d?|en\s+pc|en\s+steam|en\s+epic|en\s+xbox|en\s+nintendo|en\s+humble|al\s+\d+\s*%|con\s+\d+\s*%)\b",
            tras_dos_puntos,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        candidato_colon = re.sub(r"\s+", " ", candidato_colon).strip(" :-–—|.,")
        if len(candidato_colon) >= 2:
            return candidato_colon[:80]

    base = f"{texto_titulo} {descripcion_limpia or ''}".strip()
    base = re.sub(r"https?://\S+", " ", base)
    base = re.sub(
        r"\b(?:juego\s+gratuito(?:\s+de\s+la\s+semana)?|probable\s+)?(?:fallo\s+de\s+precio|error\s+de\s+precio|oferta|descuento|gratis|bundle|pack|clave|key)s?\s*:?",
        " ",
        base,
        flags=re.IGNORECASE,
    )
    base = re.split(
        r"\b(?:para\s+steam|en\s+steam|en\s+epic|en\s+humble|en\s+xbox|en\s+nintendo|al\s+\d+\s*%|con\s+\d+\s*%)\b",
        base,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    candidato = re.sub(r"\s+", " ", base).strip(" :-–—|.,")
    if len(candidato) >= 3:
        return candidato[:80]
    return ""


def buscar_imagen_en_steam(consulta_juego):
    if not consulta_juego:
        return None
    try:
        q = urllib.parse.quote(consulta_juego)
        url = (
            f"https://store.steampowered.com/api/storesearch/"
            f"?term={q}&l=spanish&cc=US"
        )
        resp = requests.get(url, headers=HEADERS_WEB, timeout=8)
        if not resp.ok:
            return None
        data = resp.json()
        items = data.get("items") or []
        if items:
            appid = items[0].get("id")
            if appid:
                header_url = (
                    f"https://shared.akamai.steamstatic.com/"
                    f"store_item_assets/steam/apps/{appid}/header.jpg"
                )
                if url_imagen_accesible(header_url):
                    return header_url
            tiny = items[0].get("tiny_image")
            if tiny and url_imagen_accesible(tiny):
                return tiny
    except Exception:
        pass
    return None


def buscar_og_image_en_url(url_objetivo):
    if not url_objetivo or not url_objetivo.startswith("http"):
        return None
    try:
        resp = requests.get(
            url_objetivo,
            headers=HEADERS_WEB,
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
        if og_match:
            candidata = og_match.group(1).strip()
            if url_imagen_accesible(candidata):
                return candidata
    except Exception:
        pass
    return None


def obtener_imagen_desde_lista(feed_cfg, rotacion_state, cambios_rotacion_ref):
    lista_imgs = feed_cfg.get("imagenes")
    if not isinstance(lista_imgs, list) or not lista_imgs:
        return None
    urls_validas = [
        str(u).strip() for u in lista_imgs if str(u).strip().startswith("http")
    ]
    if not urls_validas:
        return None

    modo_aleatorio = bool(feed_cfg.get("imagenes_aleatorias", False))
    if modo_aleatorio:
        candidatas = urls_validas.copy()
        random.shuffle(candidatas)
        for url in candidatas:
            if url_imagen_accesible(url):
                return url
        return None

    clave_feed = str(
        feed_cfg.get("nombre") or feed_cfg.get("rss_url") or "default"
    )
    idx_base = int(rotacion_state.get(clave_feed, 0)) % len(urls_validas)
    for offset in range(len(urls_validas)):
        idx = (idx_base + offset) % len(urls_validas)
        candidata = urls_validas[idx]
        if url_imagen_accesible(candidata):
            rotacion_state[clave_feed] = (idx + 1) % len(urls_validas)
            cambios_rotacion_ref[0] = True
            return candidata
    return None


def obtener_imagen_plataforma(texto_completo, feed_cfg):
    mapa = feed_cfg.get("imagenes_plataforma")
    if not isinstance(mapa, dict):
        return None
    txt = (texto_completo or "").lower()
    plataformas = [
        ("epic", ["epic games", "store.epicgames.com", " en epic", "epic:"]),
        ("xbox", ["xbox", "game pass"]),
        ("nintendo", ["nintendo", "switch"]),
        ("playstation", ["playstation", "ps4", "ps5"]),
    ]
    for clave, keywords in plataformas:
        if any(k in txt for k in keywords):
            url = (mapa.get(clave) or "").strip()
            if url and url_imagen_accesible(url):
                return url
    return None


def obtener_imagen(
    entry,
    enlace,
    feed_cfg,
    rotacion_state,
    cambios_rotacion_ref,
    titulo_limpio="",
    resumen_limpio="",
):
    if "media_content" in entry and entry.media_content:
        url = entry.media_content[0].get("url")
        if url and url_imagen_accesible(url):
            return url
    if "media_thumbnail" in entry and entry.media_thumbnail:
        url = entry.media_thumbnail[0].get("url")
        if url and url_imagen_accesible(url):
            return url

    for coleccion in (entry.get("enclosures", []), entry.get("links", [])):
        for item in coleccion:
            if item.get("type", "").startswith("image/") and item.get("href"):
                if url_imagen_accesible(item["href"]):
                    return item["href"]

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
        if url_imagen_accesible(match_img.group(1)):
            return match_img.group(1)

    img_appid = buscar_imagen_por_appid_en_texto(f"{enlace or ''} {texto_completo}")
    if img_appid:
        return img_appid

    if feed_cfg.get("buscar_imagen_juego", True):
        posible_juego = extraer_posible_juego(titulo_limpio, resumen_limpio)
        img_steam = buscar_imagen_en_steam(posible_juego)
        if img_steam:
            return img_steam

    urls_en_texto = re.findall(r"https?://[^\s\"'<>)\]]+", texto_completo)
    for u in urls_en_texto:
        if "steamcommunity.com" in u or "facebook.com" in u:
            continue
        og = buscar_og_image_en_url(u)
        if og:
            return og

    if enlace and "steamcommunity.com/groups/" not in enlace:
        og_principal = buscar_og_image_en_url(enlace)
        if og_principal:
            return og_principal

    img_plat = obtener_imagen_plataforma(
        f"{titulo_limpio} {resumen_limpio} {texto_completo}", feed_cfg
    )
    if img_plat:
        return img_plat

    usar_lista_fallback = feed_cfg.get("rotar_en_fallback", True)
    if usar_lista_fallback:
        img_lista = obtener_imagen_desde_lista(
            feed_cfg, rotacion_state, cambios_rotacion_ref
        )
        if img_lista:
            return img_lista

    img_defecto = (
        feed_cfg.get("imagen_defecto") or IMAGEN_ULTIMO_RECURSO
    ).strip()
    if img_defecto and url_imagen_accesible(img_defecto):
        return img_defecto

    return img_defecto or None


def main():
    bot_token = os.environ["DISCORD_BOT_TOKEN"]
    feeds = json.loads(os.environ["FEEDS_JSON"])
    solo_semilla = (
        os.environ.get("SEMILLA_SIN_ENVIAR", "false").lower() == "true"
    )

    historial = cargar_lista_json(HISTORIAL_FILE)
    historial_set = set(historial)
    log_envios = cargar_lista_json(LOG_FILE)
    logs_por_feed = {}
    feeds_con_log_nuevo = set()
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
            print(
                f"Feed desactivado (activo=false): "
                f"{feed_cfg.get('nombre', 'Sin nombre')}"
            )
            continue

        parsed = feedparser.parse(feed_cfg["rss_url"])
        if not parsed.entries:
            print(
                f"Sin entradas en el feed: "
                f"{feed_cfg.get('nombre', 'Sin nombre')}"
            )
            continue

        entradas_nuevas = []
        for e in reversed(parsed.entries[:8]):
            bloque_previo = " ".join([
                e.get("summary", ""),
                e.get("description", ""),
                " ".join(c.get("value", "") for c in e.get("content", [])),
            ])
            claves = obtener_claves_entrada(e, bloque_previo)
            if claves and not ya_registrado(claves, historial_set):
                entradas_nuevas.append((e, claves))
                for c in claves:
                    historial_set.add(c)

        if not entradas_nuevas:
            print(f"Sin novedades en {feed_cfg.get('nombre', 'Feed')}.")
            continue

        for entry, claves in entradas_nuevas:
            uid = entry.get("id") or entry.get("link") or claves[0]

            if solo_semilla:
                for c in claves:
                    if c not in historial:
                        historial.append(c)
                    historial_set.add(c)
                cambios_historial = True
                print(f"[SEMILLA] Registrado sin enviar: {uid}")
                continue

            bloque_raw = " ".join([
                entry.get("summary", ""),
                entry.get("description", ""),
                " ".join(c.get("value", "") for c in entry.get("content", [])),
            ])

            enlace = extraer_enlace_juego(entry, bloque_raw)
            url_resena = extraer_enlace_resena(entry, bloque_raw, enlace)
            titulo = extraer_titulo_limpio(entry.get("title"), enlace)
            resumen = limpiar_html(
                bloque_raw,
                url_resena=url_resena,
                etiqueta_enlace=feed_cfg.get("etiqueta_enlace") or "Juego Hispano",
            )
            imagen = obtener_imagen(
                entry,
                enlace,
                feed_cfg,
                rotacion_state,
                cambios_rotacion,
                titulo_limpio=titulo,
                resumen_limpio=resumen,
            )
            autor = obtener_autor(entry, feed_cfg, bloque_raw)
            fecha_texto = obtener_fecha_texto(entry)
            base_pie = str(
                feed_cfg.get("pie_pagina") or "Publicado en Juego Hispano"
            ).strip()
            pie_texto = f"{base_pie} • {fecha_texto}"[:2048]
            color_embed = parsear_color(
                feed_cfg.get("color"), defecto=7225568
            )
            pie_icono = (
                feed_cfg.get("pie_icono") or "https://i.imgur.com/2osEkLR.png"
            ).strip()

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
            url_api = (
                f"https://discord.com/api/v10/channels/"
                f"{feed_cfg['channel_id']}/messages"
            )
            resp = requests.post(
                url_api, headers=headers, json=payload, timeout=15
            )
            if resp.status_code in (200, 204):
                for c in claves:
                    if c not in historial:
                        historial.append(c)
                    historial_set.add(c)
                cambios_historial = True

                nombre_feed_actual = feed_cfg.get("nombre", "")
                registro_envio = {
                    "fecha_envio_utc": datetime.now(timezone.utc).isoformat(),
                    "feed": nombre_feed_actual,
                    "channel_id": str(feed_cfg.get("channel_id", "")),
                    "titulo": titulo,
                    "enlace": enlace,
                    "uid": uid,
                }
                log_envios.append(registro_envio)
                cambios_log = True

                ruta_individual = ruta_log_feed(nombre_feed_actual)
                if ruta_individual not in logs_por_feed:
                    logs_por_feed[ruta_individual] = cargar_lista_json(
                        ruta_individual
                    )
                logs_por_feed[ruta_individual].append(registro_envio)
                feeds_con_log_nuevo.add(ruta_individual)
                print(f"Publicado: {titulo}")
            else:
                print(f"Error al publicar ({resp.status_code}): {resp.text}")

    if cambios_historial:
        guardar_lista_json(HISTORIAL_FILE, historial[-2500:])
    if cambios_log:
        guardar_lista_json(LOG_FILE, log_envios[-2000:])
    for ruta_individual in feeds_con_log_nuevo:
        guardar_lista_json(
            ruta_individual, logs_por_feed[ruta_individual][-1000:]
        )
    if cambios_rotacion[0]:
        guardar_dict_json(ROTACION_FILE, rotacion_state)


if __name__ == "__main__":
    main()
