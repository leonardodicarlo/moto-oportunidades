#!/usr/bin/env python3
"""
Moto Oportunidades — Servidor web Flask
Levanta en http://localhost:5000
"""
import logging
import threading
import uuid
from datetime import datetime

from flask import Flask, render_template, request, jsonify, Response
import json

import config
from src.search import run_search

app = Flask(__name__)
logging.basicConfig(level=logging.WARNING)

# Almacén en memoria de búsquedas en curso / completadas (se limpia al reiniciar)
_searches: dict[str, dict] = {}
_searches_lock = threading.Lock()


def _run_search_async(search_id: str, brands: list, threshold: float, min_score: int, keywords_only: bool):
    """Ejecuta la búsqueda en un thread separado y guarda el resultado."""
    progress_log = []

    def on_progress(brand, message):
        progress_log.append(f"{brand}: {message}")
        with _searches_lock:
            _searches[search_id]["progress"] = list(progress_log)
            _searches[search_id]["current_brand"] = brand

    try:
        stats, opportunities = run_search(
            brands=brands,
            threshold=threshold,
            min_score=min_score,
            keywords_only=keywords_only,
            on_progress=on_progress,
        )

        # Serializar resultados para Jinja / JSON
        serialized_opps = []
        for o in opportunities:
            serialized_opps.append({
                "item_id": o.item_id,
                "title": o.title,
                "price": o.price,
                "currency": o.currency,
                "link": o.link,
                "brand": o.brand,
                "condition": "Usado" if o.condition == "used" else "Nuevo" if o.condition == "new" else o.condition,
                "location": o.location,
                "is_below_market": o.is_below_market,
                "pct_below_market": round(o.pct_below_market * 100, 1) if o.is_below_market else None,
                "market_ref_price": o.market_ref_price,
                "price_ref_source": o.price_ref_source,
                "urgency_keywords": o.urgency_keywords,
                "opportunity_score": o.opportunity_score,
            })

        serialized_stats = {}
        for brand, s in stats.items():
            if s:
                serialized_stats[brand] = {
                    "count": s.count,
                    "median": s.median,
                    "mean": s.mean,
                    "p25": s.p25,
                    "p75": s.p75,
                    "threshold_price": s.below_market_threshold(),
                    "ml_ref_count": s.ml_ref_count,
                }
            else:
                serialized_stats[brand] = None

        with _searches_lock:
            _searches[search_id].update({
                "status": "done",
                "opportunities": serialized_opps,
                "stats": serialized_stats,
                "completed_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "total_found": len(serialized_opps),
            })

    except Exception as e:
        logging.exception("Error en búsqueda")
        with _searches_lock:
            _searches[search_id].update({
                "status": "error",
                "error": str(e),
            })


@app.route("/debug/<brand>")
def debug_brand(brand: str):
    """Diagnóstico: muestra qué devuelve la API de ML para una marca sin procesar."""
    from src.api.mercadolibre import MercadoLibreClient
    from src.analyzers.keyword_analyzer import is_anticipo
    client = MercadoLibreClient()
    raw = client.search_motorcycles(brand, offset=0, condition="used")
    results = raw.get("results", [])
    total = raw.get("paging", {}).get("total", 0)
    error = raw.get("message") or raw.get("error")

    filtered_anticipo, filtered_price, valid = [], [], []
    for item in results:
        price = float(item.get("price") or 0)
        title = item.get("title", "")
        if is_anticipo(title):
            filtered_anticipo.append({"title": title, "price": price})
        elif price < config.MIN_PRICE_ARS:
            filtered_price.append({"title": title, "price": price})
        else:
            sp = item.get("sale_price") or {}
            valid.append({
                "title": title,
                "price": price,
                "original_price": item.get("original_price"),
                "sale_price_regular": sp.get("regular_amount"),
                "catalog_product_id": item.get("catalog_product_id"),
                "condition": item.get("condition"),
            })

    return jsonify({
        "brand": brand,
        "api_error": error,
        "total_available_in_ml": total,
        "returned_in_this_page": len(results),
        "min_price_ars_filter": config.MIN_PRICE_ARS,
        "valid": valid,
        "filtered_anticipo": filtered_anticipo,
        "filtered_price_too_low": filtered_price,
    })


@app.route("/")
def index():
    return render_template("index.html", brands=config.BRANDS,
                           default_threshold=config.PRICE_BELOW_MARKET_THRESHOLD)


@app.route("/search", methods=["POST"])
def search_start():
    """Inicia una búsqueda asíncrona y devuelve un search_id."""
    brands = request.form.getlist("brands") or config.BRANDS
    threshold = float(request.form.get("threshold", config.PRICE_BELOW_MARKET_THRESHOLD))
    min_score = int(request.form.get("min_score", 1))
    keywords_only = request.form.get("keywords_only") == "on"

    search_id = str(uuid.uuid4())
    with _searches_lock:
        _searches[search_id] = {
            "status": "running",
            "brands": brands,
            "threshold": threshold,
            "min_score": min_score,
            "progress": [],
            "current_brand": None,
        }

    thread = threading.Thread(
        target=_run_search_async,
        args=(search_id, brands, threshold, min_score, keywords_only),
        daemon=True,
    )
    thread.start()
    return jsonify({"search_id": search_id})


@app.route("/search/<search_id>/status")
def search_status(search_id: str):
    """Polling endpoint: devuelve estado actual de la búsqueda."""
    with _searches_lock:
        data = _searches.get(search_id)
    if not data:
        return jsonify({"error": "not found"}), 404
    return jsonify(data)


@app.route("/results/<search_id>")
def results(search_id: str):
    """Página de resultados para una búsqueda completada."""
    with _searches_lock:
        data = _searches.get(search_id)
    if not data or data["status"] != "done":
        return render_template("index.html", brands=config.BRANDS,
                               default_threshold=config.PRICE_BELOW_MARKET_THRESHOLD,
                               error="Búsqueda no encontrada o todavía en progreso.")
    return render_template("results.html", **data)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    print(f"🏍️  Moto Oportunidades corriendo en http://localhost:{args.port}")
    app.run(debug=True, port=args.port)
