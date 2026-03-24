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
        # User-Agent de browser real para evitar bloqueos por bot-detection
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        if config.ML_ACCESS_TOKEN:
            self.session.headers.update(
                {"Authorization": f"Bearer {config.ML_ACCESS_TOKEN}"}
            )
        self._catalog_cache: dict[str, dict] = {}

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{config.BASE_URL}{path}"
        p = dict(params or {})
        # ML acepta el token como query param además del header — lo mandamos de ambas formas
        if config.ML_ACCESS_TOKEN:
            p["access_token"] = config.ML_ACCESS_TOKEN
        try:
            response = self.session.get(url, params=p, timeout=15)
            # Si el token expiró, intentar renovarlo una vez
            if response.status_code == 401 and config.ML_REFRESH_TOKEN:
                logger.info("Token expirado, renovando...")
                new_token = _refresh_access_token()
                if new_token:
                    p["access_token"] = new_token
                    self.session.headers.update({"Authorization": f"Bearer {new_token}"})
                    response = self.session.get(url, params=p, timeout=15)
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
        # app_id solo se usa cuando no hay access_token (son mutuamente excluyentes)
        if config.ML_APP_ID and not config.ML_ACCESS_TOKEN:
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
        Obtiene todas las motos usadas de una marca.
        Intenta el API oficial primero; si está bloqueado (403) usa el scraper web.
        """
        logger.info(f"Buscando publicaciones de {brand}...")

        # Probar API oficial
        test = self.search_motorcycles(brand, offset=0)
        if test.get("results") is not None:
            # API disponible — paginar normalmente
            all_items: dict[str, dict] = {}
            total_available = test.get("paging", {}).get("total", 0)
            batch = test.get("results", [])
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

            logger.info(f"  -> {len(all_items)} usadas via API para {brand}")
            return list(all_items.values())

        # API bloqueada — usar scraper web
        logger.info(f"  API no disponible, usando scraper web para {brand}")
        from src.api.scraper import fetch_all_for_brand as scrape
        return scrape(brand)
