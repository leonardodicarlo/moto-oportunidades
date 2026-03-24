"""
Scraper del sitio público de MercadoLibre Argentina.
Usado como alternativa al API de búsqueda que requiere aprobación de partners.
Los datos son públicos y accesibles desde cualquier browser.
"""
import re
import json
import time
import logging
import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

BASE_URL = "https://listado.mercadolibre.com.ar"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9",
}
# ML muestra 48 resultados por página
PAGE_SIZE = 48


def _extract_items_from_page(html: str) -> list[dict]:
    """
    Extrae los items de una página de resultados de ML.
    ML embebe la data de los listings como JSON en un script tag:
    window.__PRELOADED_STATE__ o similar (patrón Next.js/Nordic).
    Como fallback, parsea el HTML directamente.
    """
    items = []

    # Intentar extraer JSON del estado del servidor (método más confiable)
    json_patterns = [
        r'window\.__PRELOADED_STATE__\s*=\s*(\{.+?\})(?:;</script>|;?\s*\n)',
        r'<script[^>]*type="application/json"[^>]*>(\{[^<]+)</script>',
    ]
    for pattern in json_patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                found = _extract_from_json_state(data)
                if found:
                    return found
            except (json.JSONDecodeError, KeyError):
                pass

    # Fallback: parsear HTML
    soup = BeautifulSoup(html, "lxml")

    # ML usa distintas clases según la versión del frontend
    item_selectors = [
        ".ui-search-layout__item",
        ".andes-card.poly-card",
        "[class*='ui-search-result']",
    ]
    item_els = []
    for sel in item_selectors:
        item_els = soup.select(sel)
        if item_els:
            break

    for el in item_els:
        item = _parse_item_element(el)
        if item:
            items.append(item)

    return items


def _extract_from_json_state(data: dict) -> list[dict]:
    """Navega el JSON del estado del servidor para extraer listings."""
    results = []

    def search_results(obj, depth=0):
        if depth > 8:
            return
        if isinstance(obj, list):
            for item in obj:
                search_results(item, depth + 1)
        elif isinstance(obj, dict):
            # Detectar objetos que parecen listings de ML
            if (obj.get("id", "").startswith("MLA")
                    and "title" in obj
                    and "price" in obj):
                results.append(obj)
                return
            for v in obj.values():
                search_results(v, depth + 1)

    search_results(data)
    return results


def _parse_item_element(el) -> dict | None:
    """Extrae datos de un elemento HTML de listing."""
    # Título
    title_el = el.select_one(
        ".poly-component__title, .ui-search-item__title, "
        "[class*='title']:not([class*='category'])"
    )
    if not title_el:
        return None
    title = title_el.get_text(strip=True)

    # Link y ID
    link_el = el.select_one("a[href*='mercadolibre']")
    if not link_el:
        return None
    href = link_el.get("href", "")
    mla_match = re.search(r'MLA-?(\d+)', href)
    if not mla_match:
        return None
    item_id = f"MLA{mla_match.group(1)}"
    clean_link = href.split("?")[0]  # Quitar query params de tracking

    # Moneda y Precio
    price = None
    currency_id = "ARS"

    # Buscar el contenedor de precio para extraer moneda y fracción juntos
    price_container_selectors = [
        ".andes-money-amount",
        ".price-tag",
        "[class*='price']",
    ]
    price_container = None
    for sel in price_container_selectors:
        price_container = el.select_one(sel)
        if price_container:
            break

    if price_container:
        # Detectar moneda — buscar el símbolo en el contenedor
        currency_el = price_container.select_one(
            ".andes-money-amount__currency-symbol, .price-tag-symbol"
        )
        if currency_el:
            symbol = currency_el.get_text(strip=True)
            if "U$S" in symbol or "USD" in symbol or "US$" in symbol:
                currency_id = "USD"
        else:
            # Fallback: buscar "U$S" en el texto del contenedor de precio
            container_text = price_container.get_text()
            if "U$S" in container_text or "US$" in container_text:
                currency_id = "USD"

    price_selectors = [
        ".andes-money-amount__fraction",
        ".price-tag-fraction",
        "[class*='price'] [class*='fraction']",
    ]
    for sel in price_selectors:
        price_el = el.select_one(sel)
        if price_el:
            raw = price_el.get_text(strip=True).replace(".", "").replace(",", "")
            try:
                price = float(raw)
                break
            except ValueError:
                continue
    if not price:
        return None

    # Precio original (tachado)
    original_price = None
    orig_el = el.select_one(".andes-money-amount--previous, [class*='original']")
    if orig_el:
        frac = orig_el.select_one(".andes-money-amount__fraction")
        if frac:
            raw = frac.get_text(strip=True).replace(".", "").replace(",", "")
            try:
                original_price = float(raw)
            except ValueError:
                pass

    # Ubicación
    location = ""
    loc_el = el.select_one(".poly-component__location, .ui-search-item__location")
    if loc_el:
        location = loc_el.get_text(strip=True)

    return {
        "id": item_id,
        "title": title,
        "price": price,
        "currency_id": currency_id,
        "permalink": clean_link,
        "condition": "used",
        "original_price": original_price,
        "sale_price": None,
        "catalog_product_id": None,
        "seller": {},
        "location": {"city": {"name": location}, "state": {"name": ""}},
        "thumbnail": "",
    }


def _scrape_pages(session, brand: str, max_pages: int, sort: str = "relevance") -> list[dict]:
    """
    Scrapea N páginas de ML para una marca.
    sort="relevance"  → orden por defecto de ML (más relevantes primero)
    sort="price_asc"  → más baratos primero (_OrderId_PRICE*)
    """
    order_tag = "_OrderId_PRICE*" if sort == "price_asc" else ""
    all_items: dict[str, dict] = {}
    page = 0

    while page < max_pages:
        if page == 0:
            url = f"{BASE_URL}/motos/{brand.lower()}/usado/{order_tag}"
        else:
            offset = page * PAGE_SIZE + 1
            url = f"{BASE_URL}/motos/{brand.lower()}/usado/_Desde_{offset}{order_tag}_NoIndex_True"

        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                logger.warning(f"  {brand} [{sort}] página {page+1}: HTTP {r.status_code}")
                break

            items = _extract_items_from_page(r.text)
            if not items:
                break

            for item in items:
                if item["id"] not in all_items:
                    all_items[item["id"]] = item

            logger.info(f"  {brand} [{sort}] p{page+1}: {len(items)} items")

            if len(items) < PAGE_SIZE:
                break

            page += 1
            time.sleep(config.RATE_LIMIT_DELAY)

        except requests.RequestException as e:
            logger.warning(f"  Error scrapeando {brand}: {e}")
            break

    return list(all_items.values())


def fetch_all_for_brand(brand: str, max_pages: int = 5) -> list[dict]:
    """
    Estrategia de dos fases para maximizar detección de oportunidades:

    Fase 1 — muestra de mercado (sort por relevancia, 3 páginas):
      Obtiene una distribución representativa de precios para calcular la mediana.
      Los primeros resultados de ML son los más completos y representativos del mercado.

    Fase 2 — candidatos baratos (sort por precio ascendente, max_pages páginas):
      Las oportunidades reales están entre los más baratos. Este sort trae primero
      los listings con precios más bajos, que es justamente donde hay ventas urgentes.

    Los stats se calculan sobre la Fase 1 (representativa).
    El análisis de oportunidades corre sobre la unión de ambas fases.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    logger.info(f"Scrapeando ML para {brand}...")

    # Fase 1: muestra representativa para estadísticas de mercado
    market_sample = _scrape_pages(session, brand, max_pages=3, sort="relevance")
    # Marcar cuáles son de la muestra de mercado
    for item in market_sample:
        item["_market_sample"] = True

    # Fase 2: listings más baratos (donde están las oportunidades)
    cheap_candidates = _scrape_pages(session, brand, max_pages=max_pages, sort="price_asc")

    # Unir ambas fases (dedup por id; cheap_candidates sobrescribe para preservar precios)
    combined: dict[str, dict] = {i["id"]: i for i in market_sample}
    for item in cheap_candidates:
        combined[item["id"]] = item  # no sobreescribir el flag _market_sample si ya estaba

    logger.info(
        f"  -> {len(market_sample)} muestra mercado + {len(cheap_candidates)} baratos "
        f"= {len(combined)} únicos para {brand}"
    )
    return list(combined.values())
