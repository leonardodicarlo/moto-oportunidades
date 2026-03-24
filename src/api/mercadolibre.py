import time
import logging
import requests
from typing import Optional

import config

logger = logging.getLogger(__name__)


class MercadoLibreClient:
    """Cliente para la API pública de MercadoLibre."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "moto-oportunidades/1.0"})
        if config.ML_ACCESS_TOKEN:
            self.session.headers.update(
                {"Authorization": f"Bearer {config.ML_ACCESS_TOKEN}"}
            )

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{config.BASE_URL}{path}"
        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP error {e.response.status_code} for {url}: {e}")
            return {}
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request error for {url}: {e}")
            return {}

    def search_motorcycles(self, brand: str, offset: int = 0) -> dict:
        """Busca motos de una marca en la categoría de motos de MercadoLibre Argentina."""
        params = {
            "q": brand,
            "category": config.MOTO_CATEGORY,
            "limit": config.API_PAGE_SIZE,
            "offset": offset,
            "sort": "price_asc",  # Primero los más baratos para detectar outliers
        }
        if config.ML_APP_ID:
            params["app_id"] = config.ML_APP_ID

        result = self._get(f"/sites/{config.SITE_ID}/search", params=params)
        time.sleep(config.RATE_LIMIT_DELAY)
        return result

    def get_item_detail(self, item_id: str) -> dict:
        """Obtiene el detalle completo de un ítem."""
        result = self._get(f"/items/{item_id}")
        time.sleep(config.RATE_LIMIT_DELAY)
        return result

    def get_item_description(self, item_id: str) -> str:
        """Obtiene la descripción textual de un ítem."""
        result = self._get(f"/items/{item_id}/description")
        time.sleep(config.RATE_LIMIT_DELAY)
        return result.get("plain_text", "")

    def fetch_all_for_brand(self, brand: str) -> list[dict]:
        """Pagina por todos los resultados disponibles para una marca (hasta MAX_RESULTS_PER_BRAND)."""
        all_items = []
        offset = 0

        logger.info(f"Buscando publicaciones de {brand}...")
        first_page = self.search_motorcycles(brand, offset=0)
        total_available = first_page.get("paging", {}).get("total", 0)
        results = first_page.get("results", [])
        all_items.extend(results)

        max_to_fetch = min(total_available, config.MAX_RESULTS_PER_BRAND)
        offset = len(results)

        while offset < max_to_fetch:
            page = self.search_motorcycles(brand, offset=offset)
            batch = page.get("results", [])
            if not batch:
                break
            all_items.extend(batch)
            offset += len(batch)

        logger.info(f"  -> {len(all_items)} publicaciones obtenidas para {brand} (total disponible: {total_available})")
        return all_items
