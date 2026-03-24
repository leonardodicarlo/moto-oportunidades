import statistics
import logging
from dataclasses import dataclass, field
from typing import Optional

import config

logger = logging.getLogger(__name__)


@dataclass
class PriceStats:
    brand: str
    count: int
    median: float
    mean: float
    std_dev: float
    p25: float  # percentil 25
    p75: float  # percentil 75
    min_price: float
    max_price: float

    def below_market_threshold(self) -> float:
        """Precio a partir del cual un ítem se considera debajo del mercado."""
        return self.median * (1 - config.PRICE_BELOW_MARKET_THRESHOLD)


@dataclass
class ListingAnalysis:
    item_id: str
    title: str
    price: float
    currency: str
    link: str
    brand: str
    condition: str
    thumbnail: str
    seller_id: Optional[int]
    location: str

    # Análisis
    is_below_market: bool = False
    pct_below_market: float = 0.0   # positivo = cuánto % más barato que la mediana
    urgency_keywords: list[str] = field(default_factory=list)
    is_anticipo: bool = False
    opportunity_score: int = 0      # 0-5: mayor = mejor oportunidad

    def compute_opportunity_score(self):
        """
        Calcula un puntaje de oportunidad combinando precio y keywords.
          - Precio < 20% bajo mediana: +2
          - Precio < 30% bajo mediana: +3 (reemplaza el anterior)
          - Keywords de urgencia detectadas: +1 por keyword (máx +2)
          - Combinado (precio Y keyword): bonus +1
        """
        score = 0

        if self.is_below_market:
            if self.pct_below_market >= 0.30:
                score += 3
            else:
                score += 2

        keyword_bonus = min(len(self.urgency_keywords), 2)
        score += keyword_bonus

        if self.is_below_market and self.urgency_keywords:
            score += 1  # bonus por combinación

        self.opportunity_score = min(score, 5)


def _percentile(sorted_data: list[float], pct: float) -> float:
    """Calcula el percentil de una lista ya ordenada."""
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    idx = (n - 1) * pct
    lower = int(idx)
    upper = lower + 1
    if upper >= n:
        return sorted_data[lower]
    frac = idx - lower
    return sorted_data[lower] * (1 - frac) + sorted_data[upper] * frac


def compute_price_stats(brand: str, prices: list[float]) -> Optional[PriceStats]:
    """Calcula estadísticas de precio para una lista de precios de una marca."""
    if len(prices) < 5:
        logger.warning(f"Muy pocas muestras para {brand} ({len(prices)}). Estadísticas poco confiables.")
        if not prices:
            return None

    sorted_prices = sorted(prices)
    return PriceStats(
        brand=brand,
        count=len(prices),
        median=statistics.median(sorted_prices),
        mean=statistics.mean(sorted_prices),
        std_dev=statistics.stdev(sorted_prices) if len(sorted_prices) > 1 else 0.0,
        p25=_percentile(sorted_prices, 0.25),
        p75=_percentile(sorted_prices, 0.75),
        min_price=sorted_prices[0],
        max_price=sorted_prices[-1],
    )


def analyze_listing(item: dict, stats: PriceStats) -> ListingAnalysis:
    """Construye un ListingAnalysis a partir de un ítem de la API y las estadísticas del mercado."""
    price = float(item.get("price") or 0)
    location_data = item.get("location") or item.get("seller_address") or {}
    city = (
        location_data.get("city", {}).get("name", "")
        or location_data.get("city_name", "")
        or "N/A"
    )
    state = (
        location_data.get("state", {}).get("name", "")
        or location_data.get("state_name", "")
        or ""
    )
    location_str = f"{city}, {state}".strip(", ") or "N/A"

    pct_below = (stats.median - price) / stats.median if stats.median > 0 else 0.0
    is_below = pct_below >= config.PRICE_BELOW_MARKET_THRESHOLD

    analysis = ListingAnalysis(
        item_id=item.get("id", ""),
        title=item.get("title", ""),
        price=price,
        currency=item.get("currency_id", "ARS"),
        link=item.get("permalink", ""),
        brand=stats.brand,
        condition=item.get("condition", ""),
        thumbnail=item.get("thumbnail", ""),
        seller_id=item.get("seller", {}).get("id"),
        location=location_str,
        is_below_market=is_below,
        pct_below_market=max(pct_below, 0.0),
    )
    return analysis
