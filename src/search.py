"""
Lógica central de búsqueda reutilizable por main.py (CLI) y app.py (web).
"""
import logging
from typing import Optional

import config
from src.api.mercadolibre import MercadoLibreClient
from src.analyzers.price_analyzer import (
    compute_price_stats,
    analyze_listing,
    get_ml_reference_price,
    PriceStats,
    ListingAnalysis,
)
from src.analyzers.keyword_analyzer import detect_urgency_keywords, is_anticipo

logger = logging.getLogger(__name__)


def _process_brand(
    client: MercadoLibreClient,
    brand: str,
    threshold: float,
    on_progress=None,
) -> tuple[Optional[PriceStats], list[ListingAnalysis]]:
    """
    Descarga, filtra y analiza todas las publicaciones de una marca.

    Orden de prioridad para el precio de referencia de mercado:
      1. sale_price.regular_amount — dato propio de ML (el del gráfico de la UI)
      2. original_price — descuento declarado por el vendedor
      3. Precio de catálogo ML (GET /products/{catalog_product_id})
      4. Mediana estadística del mercado (fallback)
    """
    raw_items = client.fetch_all_for_brand(brand)

    if on_progress:
        on_progress(brand, f"{len(raw_items)} publicaciones descargadas")

    # Filtrar anticipos y precios irreales
    valid_items = []
    for item in raw_items:
        title = item.get("title", "")
        price = float(item.get("price") or 0)
        if is_anticipo(title):
            continue
        if price < config.MIN_PRICE_ARS:
            continue
        valid_items.append(item)

    logger.info(f"{brand}: {len(raw_items) - len(valid_items)} filtrados, {len(valid_items)} válidos.")

    if not valid_items:
        return None, []

    # Enriquecer con precios de catálogo ML para items que no tienen
    # sale_price.regular_amount ni original_price
    catalog_prices: dict[str, float] = {}
    catalog_ids_to_fetch = set()

    for item in valid_items:
        ml_ref, _ = get_ml_reference_price(item)
        if ml_ref is None:
            cid = item.get("catalog_product_id")
            if cid:
                catalog_ids_to_fetch.add(cid)

    if catalog_ids_to_fetch:
        if on_progress:
            on_progress(brand, f"consultando {len(catalog_ids_to_fetch)} catálogos ML...")
        for cid in catalog_ids_to_fetch:
            catalog = client.get_catalog_product(cid)
            # El precio del catálogo puede estar en distintos lugares según el producto
            cat_price = (
                (catalog.get("buy_box_winner") or {}).get("price")
                or catalog.get("price")
            )
            if cat_price:
                catalog_prices[cid] = float(cat_price)

    # Calcular estadísticas de mercado como fallback
    prices = [float(i.get("price") or 0) for i in valid_items if i.get("price")]
    ml_ref_count = sum(1 for i in valid_items if get_ml_reference_price(i)[0] is not None)
    stats = compute_price_stats(brand, prices, ml_ref_count=ml_ref_count)

    if stats is None:
        return None, []

    original_threshold = config.PRICE_BELOW_MARKET_THRESHOLD
    config.PRICE_BELOW_MARKET_THRESHOLD = threshold

    analyzed: list[ListingAnalysis] = []
    for item in valid_items:
        cid = item.get("catalog_product_id")
        catalog_ref = catalog_prices.get(cid) if cid else None
        listing = analyze_listing(item, stats, catalog_ref_price=catalog_ref)
        listing.urgency_keywords = detect_urgency_keywords(listing.title)
        listing.compute_opportunity_score()
        analyzed.append(listing)

    config.PRICE_BELOW_MARKET_THRESHOLD = original_threshold
    return stats, analyzed


def run_search(
    brands: list[str],
    threshold: float = 0.20,
    min_score: int = 1,
    keywords_only: bool = False,
    on_progress=None,
) -> tuple[dict[str, Optional[PriceStats]], list[ListingAnalysis]]:
    """
    Ejecuta la búsqueda completa para las marcas indicadas.
    Retorna (stats_by_brand, opportunities).
    """
    client = MercadoLibreClient()
    all_stats: dict[str, Optional[PriceStats]] = {}
    all_opportunities: list[ListingAnalysis] = []

    for brand in brands:
        if on_progress:
            on_progress(brand, "buscando...")

        stats, analyzed = _process_brand(client, brand, threshold, on_progress=on_progress)
        all_stats[brand] = stats

        if not analyzed:
            continue

        if keywords_only:
            opportunities = [l for l in analyzed if l.urgency_keywords]
        else:
            opportunities = [l for l in analyzed if l.opportunity_score >= min_score]

        all_opportunities.extend(opportunities)

    all_opportunities.sort(key=lambda x: (-x.opportunity_score, x.price))
    return all_stats, all_opportunities
