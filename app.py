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
    """Diagnóstico completo: muestra credenciales cargadas y prueba la API."""
    import requests as req

    base = config.BASE_URL
    token = config.ML_ACCESS_TOKEN
    app_id = config.ML_APP_ID

    headers = {"User-Agent": "moto-oportunidades/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def do_get(params):
        if app_id:
            params["app_id"] = app_id
        if token:
            params["access_token"] = token
        r = req.get(f"{base}/sites/{config.SITE_ID}/search",
                    params=params, headers=headers, timeout=10)
        d = r.json()
        return {
            "url": r.url,
            "status": r.status_code,
            "total": d.get("paging", {}).get("total"),
            "returned": len(d.get("results", [])),
            "error": d.get("message") or d.get("error"),
            "raw_response_preview": str(d)[:300],
            "sample_titles": [i.get("title") for i in d.get("results", [])[:5]],
            "sample_conditions": [i.get("condition") for i in d.get("results", [])[:5]],
            "sample_prices": [i.get("price") for i in d.get("results", [])[:5]],
        }

    return jsonify({
        "credentials": {
            "app_id": app_id or "VACÍO",
            "access_token": (token[:20] + "...") if token else "VACÍO",
            "refresh_token": ("configurado" if config.ML_REFRESH_TOKEN else "VACÍO"),
        },
        "test_con_categoria": do_get({"q": brand, "category": config.MOTO_CATEGORY, "limit": 5}),
        "test_sin_categoria": do_get({"q": f"{brand} moto usado", "limit": 5}),
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
