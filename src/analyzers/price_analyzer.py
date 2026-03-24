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
    p25: float
    p75: float
    min_price: float
    max_price: float
    # Cuántos items tuvieron precio de referencia de ML vs estadístico
    ml_ref_count: int = 0
    currency: str = "ARS"

    def below_market_threshold(self) -> float:
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

    # Precio de referencia de mercado
    market_ref_price: Optional[float] = None   # precio de referencia usado
    price_ref_source: str = "estadístico"      # "ML precio regular" | "precio original" | "catálogo ML" | "estadístico"

    # Análisis
    is_below_market: bool = False
    pct_below_market: float = 0.0
    urgency_keywords: list[str] = field(default_factory=list)
    opportunity_score: int = 0

    def compute_opportunity_score(self):
        score = 0
        if self.is_below_market:
            score += 3 if self.pct_below_market >= 0.30 else 2
        score += min(len(self.urgency_keywords), 2)
        if self.is_below_market and self.urgency_keywords:
            score += 1
        self.opportunity_score = min(score, 5)


def _percentile(sorted_data: list[float], pct: float) -> float:
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


def compute_price_stats(brand: str, prices: list[float], ml_ref_count: int = 0, currency: str = "ARS") -> Optional[PriceStats]:
    if not prices:
        return None
    if len(prices) < 5:
        logger.warning(f"Pocas muestras para {brand} ({len(prices)}). Estadísticas poco confiables.")

    sorted_prices = sorted(prices)
    return PriceStats(
        brand=brand,
        count=len(sorted_prices),
        median=statistics.median(sorted_prices),
        mean=statistics.mean(sorted_prices),
        std_dev=statistics.stdev(sorted_prices) if len(sorted_prices) > 1 else 0.0,
        p25=_percentile(sorted_prices, 0.25),
        p75=_percentile(sorted_prices, 0.75),
        min_price=sorted_prices[0],
        max_price=sorted_prices[-1],
        ml_ref_count=ml_ref_count,
        currency=currency,
    )


def get_ml_reference_price(item: dict) -> tuple[Optional[float], str]:
    """
    Extrae el precio de referencia de mercado provisto directamente por ML.

    ML provee varios campos para esto, en orden de confiabilidad:
      1. sale_price.regular_amount: el "precio regular" de ML, usado en el gráfico
         de comparación de precio en la UI. Es el precio de referencia más directo.
      2. original_price: precio previo a un descuento aplicado por el vendedor.

    Retorna (ref_price, source) o (None, 'none') si ML no provee referencia.
    """
    price = float(item.get("price") or 0)
    if price <= 0:
        return None, "none"

    # 1. sale_price.regular_amount — el precio "de lista" según ML
    sale_price = item.get("sale_price") or {}
    regular_amount = sale_price.get("regular_amount")
    if regular_amount:
        ref = float(regular_amount)
        if ref > price:
            return ref, "ML precio regular"

    # 2. original_price — precio original antes del descuento del vendedor
    original_price = item.get("original_price")
    if original_price:
        ref = float(original_price)
        if ref > price:
            return ref, "precio original"

    return None, "none"


def analyze_listing(
    item: dict,
    stats: Optional["PriceStats"],
    catalog_ref_price: Optional[float] = None,
    threshold: Optional[float] = None,
) -> ListingAnalysis:
    """
    Analiza un ítem determinando si su precio está bajo el precio de mercado.

    Orden de prioridad para el precio de referencia:
      1. sale_price.regular_amount (ML precio regular — datos propios de ML)
      2. original_price (descuento declarado por vendedor)
      3. Precio de catálogo ML (si se pasó catalog_ref_price)
      4. Mediana estadística del mercado (fallback)
    """
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

    # Determinar precio de referencia
    ref_price, ref_source = get_ml_reference_price(item)

    if ref_price is None and catalog_ref_price:
        ref_price = catalog_ref_price
        ref_source = "catálogo ML"

    if ref_price is None and stats and stats.median > 0:
        ref_price = stats.median
        ref_source = "estadístico"

    # Calcular diferencia
    effective_threshold = threshold if threshold is not None else config.PRICE_BELOW_MARKET_THRESHOLD
    if ref_price and ref_price > 0:
        pct_below = (ref_price - price) / ref_price
        is_below = pct_below >= effective_threshold
    else:
        pct_below = 0.0
        is_below = False

    return ListingAnalysis(
        item_id=item.get("id", ""),
        title=item.get("title", ""),
        price=price,
        currency=item.get("currency_id", "ARS"),
        link=item.get("permalink", ""),
        brand=stats.brand if stats else "",
        condition=item.get("condition", ""),
        thumbnail=item.get("thumbnail", ""),
        seller_id=(item.get("seller") or {}).get("id"),
        location=location_str,
        market_ref_price=ref_price,
        price_ref_source=ref_source,
        is_below_market=is_below,
        pct_below_market=max(pct_below, 0.0),
    )
