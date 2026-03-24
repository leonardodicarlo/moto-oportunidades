#!/usr/bin/env python3
"""
Moto Oportunidades — detecta motos de primeras marcas por debajo del precio de mercado
en MercadoLibre Argentina.

Uso:
    python main.py
    python main.py --brands Honda Yamaha
    python main.py --threshold 0.15 --top 20
    python main.py --no-export
"""
import argparse
import logging
import sys
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

import config
from src.api.mercadolibre import MercadoLibreClient
from src.analyzers.price_analyzer import compute_price_stats, analyze_listing, ListingAnalysis
from src.analyzers.keyword_analyzer import detect_urgency_keywords, is_anticipo
from src.reporter.console_reporter import (
    print_summary_header,
    print_brand_stats,
    print_opportunities,
    export_to_csv,
)

console = Console()
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s | %(name)s | %(message)s",
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Detecta motos de primeras marcas por debajo del precio de mercado en MercadoLibre Argentina."
    )
    parser.add_argument(
        "--brands",
        nargs="+",
        default=config.BRANDS,
        metavar="MARCA",
        help=f"Marcas a buscar (default: {', '.join(config.BRANDS)})",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=config.PRICE_BELOW_MARKET_THRESHOLD,
        metavar="PORCENTAJE",
        help="Umbral para considerar 'precio bajo mercado' (ej: 0.20 = 20%% bajo mediana). Default: %(default)s",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="Mostrar solo los N mejores resultados. Default: todos.",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=1,
        choices=range(1, 6),
        metavar="1-5",
        help="Puntaje mínimo de oportunidad para mostrar. Default: %(default)s",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="No exportar resultados a CSV.",
    )
    parser.add_argument(
        "--output",
        default=config.CSV_OUTPUT_FILE,
        help="Nombre del archivo CSV de salida. Default: %(default)s",
    )
    parser.add_argument(
        "--keywords-only",
        action="store_true",
        help="Mostrar solo publicaciones con keywords de urgencia (ignora análisis de precio).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Mostrar logs detallados.",
    )
    return parser.parse_args()


def process_brand(
    client: MercadoLibreClient,
    brand: str,
    threshold: float,
    progress=None,
    task_id=None,
) -> tuple[Optional[object], list[ListingAnalysis]]:
    """
    Procesa todos los listings de una marca:
    1. Descarga publicaciones
    2. Filtra anticipos y precios irreales
    3. Calcula estadísticas de mercado
    4. Analiza cada listing contra la mediana
    5. Detecta keywords de urgencia
    """
    raw_items = client.fetch_all_for_brand(brand)

    if progress and task_id is not None:
        progress.advance(task_id)

    # Paso 1: filtrar anticipos y precios irreales
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

    if filtered_anticipo or filtered_price:
        console.print(
            f"  [dim]{brand}: {filtered_anticipo} anticipos y {filtered_price} precios "
            f"< ${config.MIN_PRICE_ARS:,} filtrados.[/dim]"
        )

    if not valid_items:
        console.print(f"  [yellow]Sin publicaciones válidas para {brand}.[/yellow]")
        return None, []

    # Paso 2: calcular estadísticas de mercado
    prices = [float(item.get("price") or 0) for item in valid_items if item.get("price")]
    stats = compute_price_stats(brand, prices)

    if stats is None:
        return None, []

    # Paso 3: override threshold si se pasó por argumento
    original_threshold = config.PRICE_BELOW_MARKET_THRESHOLD
    config.PRICE_BELOW_MARKET_THRESHOLD = threshold

    # Paso 4: analizar cada listing
    analyzed: list[ListingAnalysis] = []
    for item in valid_items:
        listing = analyze_listing(item, stats)
        listing.urgency_keywords = detect_urgency_keywords(listing.title)
        listing.compute_opportunity_score()
        analyzed.append(listing)

    config.PRICE_BELOW_MARKET_THRESHOLD = original_threshold
    return stats, analyzed


def main():
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    # Actualizar threshold si se pasó por argumento
    config.PRICE_BELOW_MARKET_THRESHOLD = args.threshold

    print_summary_header(args.brands, args.threshold)
    console.print()

    client = MercadoLibreClient()
    all_stats = {}
    all_opportunities: list[ListingAnalysis] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Analizando marcas...", total=len(args.brands))

        for brand in args.brands:
            progress.update(task, description=f"Buscando [bold]{brand}[/bold]...")
            stats, analyzed = process_brand(client, brand, args.threshold)
            all_stats[brand] = stats
            progress.advance(task)

            if not analyzed:
                continue

            # Filtrar por criterio de selección
            if args.keywords_only:
                opportunities = [l for l in analyzed if l.urgency_keywords]
            else:
                opportunities = [
                    l for l in analyzed
                    if l.opportunity_score >= args.min_score
                ]

            all_opportunities.extend(opportunities)

    console.print()
    print_brand_stats(all_stats)
    console.print()

    if not all_opportunities:
        console.print(
            f"\n[yellow]No se encontraron oportunidades con puntaje >= {args.min_score}.[/yellow]\n"
            "[dim]Probá reducir --min-score o --threshold.[/dim]"
        )
        sys.exit(0)

    print_opportunities(all_opportunities, top_n=args.top)

    if not args.no_export and config.EXPORT_CSV:
        export_to_csv(all_opportunities, args.output)


if __name__ == "__main__":
    main()
