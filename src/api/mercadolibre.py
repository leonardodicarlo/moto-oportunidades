import time
import logging
import requests
from typing import Optional

import config

logger = logging.getLogger(__name__)

# ML's hard limit: offset + limit <= 1000
ML_MAX_OFFSET = 950


class MercadoLibreClient:
    """Cliente para la API pública de MercadoLibre."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "moto-oportunidades/1.0"})
        if config.ML_ACCESS_TOKEN:
            self.session.headers.update(
                {"Authorization": f"Bearer {config.ML_ACCESS_TOKEN}"}
            )
        self._catalog_cache: dict[str, dict] = {}

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

    def search_motorcycles(self, brand: str, offset: int = 0, condition: Optional[str] = None) -> dict:
        """Busca motos de una marca. condition: 'new', 'used', o None (todos)."""
        params = {
            "q": brand,
            "category": config.MOTO_CATEGORY,
            "limit": config.API_PAGE_SIZE,
            "offset": offset,
        }
        if condition:
            params["condition"] = condition
        if config.ML_APP_ID:
            params["app_id"] = config.ML_APP_ID

        result = self._get(f"/sites/{config.SITE_ID}/search", params=params)
        time.sleep(config.RATE_LIMIT_DELAY)
        return result

    def get_catalog_product(self, catalog_product_id: str) -> dict:
        """
        Obtiene el producto de catálogo de ML con su precio de referencia.
        Usa cache para no repetir llamadas al mismo producto.
        """
        if catalog_product_id in self._catalog_cache:
            return self._catalog_cache[catalog_product_id]
        result = self._get(f"/products/{catalog_product_id}")
        time.sleep(config.RATE_LIMIT_DELAY)
        self._catalog_cache[catalog_product_id] = result
        return result

    def _paginate_condition(self, brand: str, condition: Optional[str]) -> list[dict]:
        """Pagina todos los resultados para una marca y condición hasta el límite de ML."""
        items: dict[str, dict] = {}
        offset = 0

        first_page = self.search_motorcycles(brand, offset=0, condition=condition)
        total_available = first_page.get("paging", {}).get("total", 0)
        batch = first_page.get("results", [])
        for item in batch:
            items[item["id"]] = item

        offset = len(batch)
        cap = min(total_available, ML_MAX_OFFSET + config.API_PAGE_SIZE)

        while offset < cap and batch:
            page = self.search_motorcycles(brand, offset=offset, condition=condition)
            batch = page.get("results", [])
            for item in batch:
                items[item["id"]] = item
            offset += len(batch)

        label = condition or "all"
        logger.info(f"  [{label}] {len(items)} items (total disponible: {total_available})")
        return list(items.values())

    def fetch_all_for_brand(self, brand: str) -> list[dict]:
        """
        Descarga TODAS las publicaciones disponibles para una marca:
        - Busca 'used' y 'new' por separado para maximizar cobertura
        - Pagina hasta el límite de la API de ML (~1000 por condición)
        - Deduplica por ID
        """
        logger.info(f"Buscando publicaciones de {brand}...")
        all_items: dict[str, dict] = {}

        for condition in ["used", "new"]:
            batch = self._paginate_condition(brand, condition)
            for item in batch:
                all_items[item["id"]] = item

        total = len(all_items)
        logger.info(f"  -> {total} publicaciones únicas para {brand}")
        return list(all_items.values())
