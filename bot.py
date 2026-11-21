def extraer_posible_juego(titulo, descripcion_limpia):
    texto_titulo = (titulo or "").strip()

    # Si hay ":", suele venir el nombre del juego tras los dos puntos (ej. "Juego gratuito en Epic: Knightica...")
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
