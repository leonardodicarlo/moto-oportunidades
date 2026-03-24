import os
import time
import logging
import requests
from typing import Optional

import config

logger = logging.getLogger(__name__)

# ML's hard limit: offset + limit <= 1000
ML_MAX_OFFSET = 950
_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def _refresh_access_token() -> str:
    """Renueva el Access Token usando el Refresh Token y lo persiste en .env."""
    if not config.ML_REFRESH_TOKEN:
        return ""
    response = requests.post(
        "https://api.mercadolibre.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": config.ML_APP_ID,
            "client_secret": config.ML_CLIENT_SECRET,
            "refresh_token": config.ML_REFRESH_TOKEN,
        },
        timeout=15,
    )
    if response.status_code != 200:
        logger.error(f"Error al renovar token: {response.json()}")
        return ""
    data = response.json()
    new_token = data.get("access_token", "")
    new_refresh = data.get("refresh_token", config.ML_REFRESH_TOKEN)

    # Persistir en .env y en config en memoria
    config.ML_ACCESS_TOKEN = new_token
    config.ML_REFRESH_TOKEN = new_refresh
    _write_env_key("ML_ACCESS_TOKEN", new_token)
    _write_env_key("ML_REFRESH_TOKEN", new_refresh)
    logger.info("Access Token renovado exitosamente.")
    return new_token


def _write_env_key(key: str, value: str):
    if not os.path.exists(_ENV_PATH):
        return
    with open(_ENV_PATH) as f:
        lines = f.readlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")
    with open(_ENV_PATH, "w") as f:
        f.writelines(lines)


class MercadoLibreClient:
    """Cliente para la API de MercadoLibre con auto-refresh de token."""

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
            # Si el token expiró, intentar renovarlo una vez
            if response.status_code == 401 and config.ML_REFRESH_TOKEN:
                logger.info("Token expirado, renovando...")
                new_token = _refresh_access_token()
                if new_token:
                    self.session.headers.update({"Authorization": f"Bearer {new_token}"})
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
        }
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

    def fetch_all_for_brand(self, brand: str) -> list[dict]:
        """
        Descarga todas las publicaciones de motos usadas para una marca.
        Pagina hasta el límite de la API de ML (~1000 resultados).
        Filtra client-side por condition=='used' ya que ML no acepta el
        parámetro condition como filtro directo en el search endpoint.
        """
        logger.info(f"Buscando publicaciones de {brand}...")
        all_items: dict[str, dict] = {}
        offset = 0

        first_page = self.search_motorcycles(brand, offset=0)
        total_available = first_page.get("paging", {}).get("total", 0)
        batch = first_page.get("results", [])
        for item in batch:
            if item.get("condition") == "used":
                all_items[item["id"]] = item

        offset = len(batch)
        cap = min(total_available, ML_MAX_OFFSET + config.API_PAGE_SIZE)

        while offset < cap and batch:
            page = self.search_motorcycles(brand, offset=offset)
            batch = page.get("results", [])
            for item in batch:
                if item.get("condition") == "used":
                    all_items[item["id"]] = item
            offset += len(batch)

        logger.info(f"  -> {len(all_items)} usadas de {total_available} totales para {brand}")
        return list(all_items.values())
