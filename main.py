"""
Entry point — Social Media Manager Multi-Agent System
"""
import typer
from rich.console import Console
from rich.prompt import Prompt

from models.post import Platform
from workflows.orchestrator import Orchestrator

app = typer.Typer(help="Social Media Manager — Sistema Multi-Agente")
console = Console()
orchestrator = Orchestrator()


@app.command()
def start():
    """Avvia l'orchestratore con tutti i job in background."""
    console.print("[bold green]Avvio Social Media Manager...[/bold green]")
    orchestrator.start()


@app.command()
def generate(
    topic: str = typer.Argument(..., help="Argomento del post"),
    platforms: list[str] = typer.Option(["linkedin", "facebook", "instagram"], "--platform", "-p"),
    tone: str = typer.Option("professionale", "--tone", "-t"),
):
    """Genera post per le piattaforme specificate (richiedono approvazione)."""
    platform_enums = []
    for p in platforms:
        try:
            platform_enums.append(Platform(p.lower()))
        except ValueError:
            console.print(f"[red]Piattaforma non valida: {p}[/red]")
            raise typer.Exit(1)

    posts = orchestrator.generate_post(topic=topic, platforms=platform_enums, tone=tone)
    console.print(f"\n[green]{len(posts)} post generati[/green] — approva dal dashboard: http://localhost:8000")


@app.command()
def dashboard():
    """Avvia solo il dashboard di approvazione."""
    import uvicorn
    from config.settings import settings
    console.print(f"[blue]Dashboard disponibile su http://{settings.dashboard_host}:{settings.dashboard_port}[/blue]")
    uvicorn.run("dashboard.main:app", host=settings.dashboard_host, port=settings.dashboard_port, reload=True)


@app.command()
def analytics():
    """Mostra le metriche di performance attuali."""
    from agents.analytics import AnalyticsAgent
    from rich.table import Table

    agent = AnalyticsAgent()
    data = agent.collect_all()

    table = Table(title="Metriche Social")
    table.add_column("Piattaforma", style="bold")
    table.add_column("Metrica")
    table.add_column("Valore")

    for platform, metrics in data.items():
        if platform == "collected_at":
            continue
        if isinstance(metrics, dict):
            for key, value in metrics.items():
                table.add_row(platform.upper(), key, str(value))

    console.print(table)


if __name__ == "__main__":
    app()
