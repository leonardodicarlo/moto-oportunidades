"""
Lógica central de búsqueda reutilizable por main.py (CLI) y app.py (web).
"""
import logging
from typing import Optional

import config
from src.api.mercadolibre import MercadoLibreClient
from src.analyzers.price_analyzer import compute_price_stats, analyze_listing, PriceStats, ListingAnalysis
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
    on_progress: callback opcional fn(brand, message) para reportar progreso.
    """
    raw_items = client.fetch_all_for_brand(brand)

    if on_progress:
        on_progress(brand, f"{len(raw_items)} publicaciones descargadas")

    valid_items = []
    filtered_anticipo = 0
    filtered_price = 0

    for item in raw_items:
        title = item.get("title", "")
        price = float(item.get("price") or 0)

        if is_anticipo(title):
            filtered_anticipo += 1
            continue
        if price < config.MIN_PRICE_ARS:
            filtered_price += 1
            continue

        valid_items.append(item)

    logger.info(
        f"{brand}: {filtered_anticipo} anticipos y {filtered_price} precios bajos filtrados. "
        f"{len(valid_items)} válidos."
    )

    if not valid_items:
        return None, []

    prices = [float(item.get("price") or 0) for item in valid_items if item.get("price")]
    stats = compute_price_stats(brand, prices)
    if stats is None:
        return None, []

    original_threshold = config.PRICE_BELOW_MARKET_THRESHOLD
    config.PRICE_BELOW_MARKET_THRESHOLD = threshold

    analyzed: list[ListingAnalysis] = []
    for item in valid_items:
        listing = analyze_listing(item, stats)
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

    Retorna:
        stats_by_brand: dict marca -> PriceStats (o None si no hay datos)
        opportunities:  lista de ListingAnalysis que cumplen los criterios
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
