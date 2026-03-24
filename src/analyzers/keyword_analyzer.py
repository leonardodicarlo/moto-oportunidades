import unicodedata
import re
from typing import Optional

import config


def _normalize(text: str) -> str:
    """Convierte a minúsculas y elimina tildes para comparación robusta."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _contains_any(text: str, keywords: list[str]) -> Optional[str]:
    """Retorna la primera keyword encontrada en el texto, o None."""
    normalized = _normalize(text)
    for kw in keywords:
        pattern = r"\b" + re.escape(_normalize(kw)) + r"\b"
        if re.search(pattern, normalized):
            return kw
    return None


def detect_urgency_keywords(title: str, description: str = "") -> list[str]:
    """
    Detecta palabras clave de urgencia/oportunidad en título y descripción.
    Retorna lista de keywords encontradas.
    """
    combined = f"{title} {description}"
    found = []
    normalized = _normalize(combined)
    for kw in config.URGENCY_KEYWORDS:
        pattern = r"\b" + re.escape(_normalize(kw)) + r"\b"
        if re.search(pattern, normalized) and kw not in found:
            found.append(kw)
    return found


def is_anticipo(title: str, description: str = "") -> bool:
    """
    Detecta si una publicación es un anticipo/seña en lugar del precio final.
    Retorna True si debe ser filtrada.
    """
    combined = f"{title} {description}"
    return _contains_any(combined, config.ANTICIPO_KEYWORDS) is not None


def extract_brand_from_title(title: str, brands: list[str]) -> Optional[str]:
    """Intenta detectar qué marca se menciona en el título."""
    normalized = _normalize(title)
    for brand in brands:
        if _normalize(brand) in normalized:
            return brand
    return None
