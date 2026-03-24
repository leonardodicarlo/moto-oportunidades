#!/usr/bin/env python3
"""
Moto Oportunidades — CLI
Detecta motos de primeras marcas por debajo del precio de mercado en MercadoLibre Argentina.

Uso:
    python main.py
    python main.py --brands Honda Yamaha
    python main.py --threshold 0.15 --top 20
    python main.py --no-export
"""
import argparse
import logging
import sys

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

import config
from src.search import run_search
from src.reporter.console_reporter import (
    print_summary_header,
    print_brand_stats,
    print_opportunities,
    export_to_csv,
)

console = Console()
logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(name)s | %(message)s")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Detecta motos de primeras marcas por debajo del precio de mercado en MercadoLibre Argentina."
    )
    parser.add_argument("--brands", nargs="+", default=config.BRANDS, metavar="MARCA",
                        help=f"Marcas a buscar (default: {', '.join(config.BRANDS)})")
    parser.add_argument("--threshold", type=float, default=config.PRICE_BELOW_MARKET_THRESHOLD,
                        metavar="PORCENTAJE",
                        help="Umbral para 'precio bajo mercado' (ej: 0.20 = 20%% bajo mediana). Default: %(default)s")
    parser.add_argument("--top", type=int, default=None, metavar="N",
                        help="Mostrar solo los N mejores resultados.")
    parser.add_argument("--min-score", type=int, default=1, choices=range(1, 6), metavar="1-5",
                        help="Puntaje mínimo de oportunidad. Default: %(default)s")
    parser.add_argument("--no-export", action="store_true", help="No exportar resultados a CSV.")
    parser.add_argument("--output", default=config.CSV_OUTPUT_FILE,
                        help="Nombre del archivo CSV de salida. Default: %(default)s")
    parser.add_argument("--keywords-only", action="store_true",
                        help="Mostrar solo publicaciones con keywords de urgencia.")
    parser.add_argument("--verbose", action="store_true", help="Mostrar logs detallados.")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    print_summary_header(args.brands, args.threshold)
    console.print()

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  BarColumn(), TaskProgressColumn(), console=console) as progress:
        task = progress.add_task("Analizando marcas...", total=len(args.brands))

        def on_progress(brand, message):
            progress.update(task, description=f"[bold]{brand}[/bold]: {message}")

        all_stats, all_opportunities = run_search(
            brands=args.brands,
            threshold=args.threshold,
            min_score=args.min_score,
            keywords_only=args.keywords_only,
            on_progress=on_progress,
        )
        progress.update(task, completed=len(args.brands))

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
