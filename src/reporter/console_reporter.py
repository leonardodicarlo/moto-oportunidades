import csv
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from src.analyzers.price_analyzer import ListingAnalysis, PriceStats
import config

console = Console()


def _fmt_price(price: float, currency: str = "ARS") -> str:
    symbol = "$" if currency == "ARS" else currency
    return f"{symbol} {price:,.0f}".replace(",", ".")


def _score_color(score: int) -> str:
    if score >= 4:
        return "bold red"
    if score >= 3:
        return "bold yellow"
    if score >= 2:
        return "bold green"
    return "green"


def _condition_label(condition: str) -> str:
    return "Usado" if condition == "used" else "Nuevo" if condition == "new" else condition


def print_brand_stats(stats_by_brand: dict[str, Optional[PriceStats]]):
    table = Table(
        title="Estadísticas de mercado por marca",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Marca", style="bold white")
    table.add_column("Muestras", justify="right")
    table.add_column("Mediana", justify="right", style="cyan")
    table.add_column("Promedio", justify="right")
    table.add_column("P25", justify="right", style="dim")
    table.add_column("P75", justify="right", style="dim")
    table.add_column("Umbral oportunidad", justify="right", style="yellow")

    for brand, stats in stats_by_brand.items():
        if stats is None:
            table.add_row(brand, "—", "—", "—", "—", "—", "—")
            continue
        table.add_row(
            brand,
            str(stats.count),
            _fmt_price(stats.median),
            _fmt_price(stats.mean),
            _fmt_price(stats.p25),
            _fmt_price(stats.p75),
            _fmt_price(stats.below_market_threshold()),
        )

    console.print(table)


def print_opportunities(listings: list[ListingAnalysis], top_n: Optional[int] = None):
    if not listings:
        console.print(Panel("[yellow]No se encontraron oportunidades con los criterios actuales.[/yellow]"))
        return

    sorted_listings = sorted(listings, key=lambda x: (-x.opportunity_score, x.price))
    if top_n:
        sorted_listings = sorted_listings[:top_n]

    table = Table(
        title=f"Oportunidades detectadas ({len(sorted_listings)} resultados)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        show_lines=True,
    )
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Puntaje", justify="center", width=7)
    table.add_column("Marca", width=8)
    table.add_column("Título", min_width=35, max_width=55)
    table.add_column("Precio", justify="right", width=16)
    table.add_column("% bajo\nmercado", justify="right", width=10)
    table.add_column("Estado", width=6)
    table.add_column("Ubicación", width=20)
    table.add_column("Keywords", width=20)

    for i, listing in enumerate(sorted_listings, 1):
        score_text = Text(f"{'★' * listing.opportunity_score}{'☆' * (5 - listing.opportunity_score)}")
        score_text.stylize(_score_color(listing.opportunity_score))

        pct_text = (
            Text(f"-{listing.pct_below_market:.1%}", style="bold green")
            if listing.is_below_market
            else Text("—", style="dim")
        )

        keywords_display = ", ".join(listing.urgency_keywords) if listing.urgency_keywords else "—"
        kw_text = Text(keywords_display, style="yellow bold" if listing.urgency_keywords else "dim")

        table.add_row(
            str(i),
            score_text,
            listing.brand,
            listing.title,
            _fmt_price(listing.price, listing.currency),
            pct_text,
            _condition_label(listing.condition),
            listing.location,
            kw_text,
        )

    console.print(table)

    console.print()
    console.print("[dim]Para ver una publicación, usá el link:[/dim]")
    for i, listing in enumerate(sorted_listings[:10], 1):
        console.print(f"  [cyan]{i}.[/cyan] {listing.link}")


def export_to_csv(listings: list[ListingAnalysis], filepath: str):
    if not listings:
        return

    fieldnames = [
        "id", "titulo", "marca", "precio", "moneda", "pct_bajo_mercado",
        "puntaje", "keywords", "condicion", "ubicacion", "link",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for l in sorted(listings, key=lambda x: (-x.opportunity_score, x.price)):
            writer.writerow({
                "id": l.item_id,
                "titulo": l.title,
                "marca": l.brand,
                "precio": l.price,
                "moneda": l.currency,
                "pct_bajo_mercado": f"{l.pct_below_market:.2%}" if l.is_below_market else "",
                "puntaje": l.opportunity_score,
                "keywords": "; ".join(l.urgency_keywords),
                "condicion": _condition_label(l.condition),
                "ubicacion": l.location,
                "link": l.link,
            })

    console.print(f"\n[green]Resultados exportados a:[/green] [cyan]{filepath}[/cyan]")


def print_summary_header(brands: list[str], threshold_pct: float):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    console.print(Panel(
        f"[bold cyan]Moto Oportunidades[/bold cyan]\n"
        f"[dim]Ejecutado: {now}[/dim]\n"
        f"Marcas: [yellow]{', '.join(brands)}[/yellow]\n"
        f"Umbral precio bajo mercado: [green]{threshold_pct:.0%}[/green] por debajo de la mediana",
        box=box.DOUBLE_EDGE,
        style="bold",
    ))
