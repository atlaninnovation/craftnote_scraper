import asyncio
import logging
from pathlib import Path
from typing import Annotated, Final

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from craftnote_scraper.api.client import CraftnoteClient
from craftnote_scraper.api.exceptions import CraftnoteAPIError
from craftnote_scraper.mapping.models import WindFarm
from craftnote_scraper.mapping.wind_farms import (
    build_wind_farm_map,
    discover_craftnote_structure,
    parse_matrix_wind_farms,
)
from craftnote_scraper.scraper.browser import BRAVE_EXECUTABLE_PATH, BrowserConfig, browser_context
from craftnote_scraper.scraper.downloader import (
    download_all_project_files,
    download_wind_farm_files,
)
from craftnote_scraper.storage.models import DownloadedFile, FileType
from craftnote_scraper.storage.organizer import save_file
from craftnote_scraper.storage.tracker import DownloadTracker

DEFAULT_OUTPUT_DIR: Final[str] = "downloads"
DEFAULT_DB_PATH: Final[str] = "downloads.db"
DEFAULT_MATRIX_MAPPING_PATH: Final[str] = "learning/wind-farm-spaces.md"
EXIT_CODE_SUCCESS: Final[int] = 0
EXIT_CODE_ERROR: Final[int] = 1

EXCLUDED_FOLDERS: Final[set[str]] = {
    # Administrative / IT
    "DFÜ",
    "IT Projekte ",
    "IT-Projekte",
    "Koordinaten Windparks",
    "Lager",
    "Marketing",
    "Projekte",
    "Rechnungen Scan",
    "Starlink Görlitz",
    "Test",
    "Unternehmens-Chat",
    # Real estate
    "Doku Unterkunft",
    "Eimsbüttler Chaussee",
    "Immobilien",
    "Immobilien Hamburg",
    # Insurance / damages
    "Einbruchschaden Langendorf",
    "Gewährleistung",
    "Versicherungsfälle",
    "Versicherungsschäden",
    # External / misc
    "Beispiel-Projekt",
    "Fremdaufträge",
    "Fuhrpark",
    "Sommerfest 2021",
    "Windkraftmesse 2024",
}

app = typer.Typer(
    name="craftnote-scraper",
    help="Download service report PDFs and spreadsheets from Craftnote project chats.",
    no_args_is_help=True,
)
console = Console()
error_console = Console(stderr=True)


class VerbosityLevel:
    QUIET = 0
    NORMAL = 1
    VERBOSE = 2


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.ERROR
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )


def get_wind_farms_sync(matrix_path: Path | None = None) -> list[WindFarm]:
    return asyncio.run(_get_wind_farms(matrix_path))


async def _get_wind_farms(matrix_path: Path | None = None) -> list[WindFarm]:
    matrix_farms = []
    if matrix_path and matrix_path.exists():
        matrix_farms = parse_matrix_wind_farms(matrix_path)

    async with CraftnoteClient() as client:
        return await build_wind_farm_map(client, matrix_farms)


async def _get_craftnote_structure() -> dict[str, list]:
    async with CraftnoteClient() as client:
        return await discover_craftnote_structure(client)


def find_farm_by_name(farms: list[WindFarm], name: str) -> WindFarm | None:
    name_lower = name.lower()
    for farm in farms:
        if farm.name.lower() == name_lower:
            return farm
    for farm in farms:
        if name_lower in farm.name.lower():
            return farm
    return None


@app.command("list-farms")
def list_farms(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable verbose output")] = False,
) -> None:
    """Show all wind farms and turbine counts."""
    setup_logging(verbose)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Fetching wind farms from Craftnote...", total=None)
        try:
            structure = asyncio.run(_get_craftnote_structure())
        except CraftnoteAPIError as e:
            error_console.print(f"[red]API Error:[/red] {e}")
            raise typer.Exit(EXIT_CODE_ERROR) from e

    if not structure:
        console.print("[yellow]No wind farms found.[/yellow]")
        raise typer.Exit(EXIT_CODE_SUCCESS)

    table = Table(title="Wind Farms")
    table.add_column("Name", style="cyan")
    table.add_column("Turbines", justify="right", style="green")

    for farm_name, turbines in sorted(structure.items()):
        table.add_row(farm_name, str(len(turbines)))

    console.print(table)
    console.print(f"\nTotal: {len(structure)} wind farms")


@app.command("list-turbines")
def list_turbines(
    farm: Annotated[str, typer.Option("--farm", "-f", help="Wind farm name")],
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable verbose output")] = False,
) -> None:
    """Show turbines for a specific wind farm."""
    setup_logging(verbose)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Fetching wind farm data...", total=None)
        try:
            structure = asyncio.run(_get_craftnote_structure())
        except CraftnoteAPIError as e:
            error_console.print(f"[red]API Error:[/red] {e}")
            raise typer.Exit(EXIT_CODE_ERROR) from e

    farm_lower = farm.lower()
    matched_farm = None
    matched_turbines = None

    for farm_name, turbines in structure.items():
        if farm_name.lower() == farm_lower or farm_lower in farm_name.lower():
            matched_farm = farm_name
            matched_turbines = turbines
            break

    if not matched_farm or matched_turbines is None:
        error_console.print(f"[red]Wind farm not found:[/red] {farm}")
        error_console.print("\nAvailable farms:")
        for name in sorted(structure.keys()):
            error_console.print(f"  - {name}")
        raise typer.Exit(EXIT_CODE_ERROR)

    table = Table(title=f"Turbines in {matched_farm}")
    table.add_column("Name", style="cyan")
    table.add_column("Project ID", style="dim")

    for turbine in sorted(matched_turbines, key=lambda t: t.name):
        table.add_row(turbine.name, turbine.id)

    console.print(table)
    console.print(f"\nTotal: {len(matched_turbines)} turbines")


@app.command("download")
def download(
    farm: Annotated[
        str | None, typer.Option("--farm", "-f", help="Wind farm name to download")
    ] = None,
    all_farms: Annotated[
        bool, typer.Option("--all", "-a", help="Download from all wind farms")
    ] = False,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", "-o", help="Output directory for downloads")
    ] = Path(DEFAULT_OUTPUT_DIR),
    headless: Annotated[
        bool, typer.Option("--headless/--no-headless", help="Run browser in headless mode")
    ] = True,
    resume: Annotated[
        bool, typer.Option("--resume", "-r", help="Skip farms that already have a folder")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Show what would be downloaded")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable verbose output")] = False,
) -> None:
    """Download files for one or all wind farms."""
    setup_logging(verbose)

    if not farm and not all_farms:
        error_console.print("[red]Error:[/red] Specify --farm <name> or --all")
        raise typer.Exit(EXIT_CODE_ERROR)

    if farm and all_farms:
        error_console.print("[red]Error:[/red] Cannot use both --farm and --all")
        raise typer.Exit(EXIT_CODE_ERROR)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Fetching wind farm data...", total=None)
        try:
            wind_farms = get_wind_farms_sync()
        except CraftnoteAPIError as e:
            error_console.print(f"[red]API Error:[/red] {e}")
            raise typer.Exit(EXIT_CODE_ERROR) from e

    if farm:
        matched_farm = find_farm_by_name(wind_farms, farm)
        if not matched_farm:
            error_console.print(f"[red]Wind farm not found:[/red] {farm}")
            raise typer.Exit(EXIT_CODE_ERROR)
        farms_to_download = [matched_farm]
    else:
        farms_to_download = [wf for wf in wind_farms if wf.name not in EXCLUDED_FOLDERS]
        excluded_count = len(wind_farms) - len(farms_to_download)
        if excluded_count > 0 and verbose:
            console.print(f"[dim]Skipping {excluded_count} excluded folders[/dim]")

    if dry_run:
        console.print("[yellow]Dry run mode - no files will be downloaded[/yellow]\n")
        for wf in farms_to_download:
            console.print(f"[cyan]{wf.name}[/cyan]")
            for turbine in wf.turbines:
                if turbine.craftnote_project_id:
                    console.print(f"  - {turbine.name} ({turbine.craftnote_project_id})")
        console.print(f"\nWould download from {len(farms_to_download)} wind farm(s)")
        raise typer.Exit(EXIT_CODE_SUCCESS)

    asyncio.run(_download_farms(farms_to_download, output_dir, headless, verbose, resume))


def _sanitize_folder_name(name: str) -> str:
    """Sanitize folder name to match downloader logic."""
    invalid_chars = '<>:"/\\|?*'
    result = name
    for char in invalid_chars:
        result = result.replace(char, "_")
    return result.strip()


async def _download_farms(
    farms: list[WindFarm],
    output_dir: Path,
    headless: bool,
    verbose: bool,
    resume: bool = False,
) -> None:
    total_files = 0
    total_errors = 0
    skipped_farms = 0

    if resume:
        farms_to_process = []
        for farm in farms:
            folder_name = _sanitize_folder_name(farm.name)
            farm_dir = output_dir / folder_name
            if farm_dir.exists():
                skipped_farms += 1
                if verbose:
                    console.print(f"[dim]Skipping {farm.name} (already exists)[/dim]")
            else:
                farms_to_process.append(farm)
        farms = farms_to_process
        if skipped_farms > 0:
            console.print(f"[yellow]Resuming: skipped {skipped_farms} existing farms[/yellow]")

    if not farms:
        console.print("[green]Nothing to download - all farms already processed[/green]")
        return

    total_turbines = sum(1 for farm in farms for t in farm.turbines if t.craftnote_project_id)

    config = BrowserConfig(headless=headless, executable_path=BRAVE_EXECUTABLE_PATH)
    async with browser_context(config) as context:
        page = await context.new_page()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            overall_task = progress.add_task("[cyan]Downloading...", total=total_turbines)

            for farm in farms:
                turbines = [
                    (t.name, t.craftnote_project_id)
                    for t in farm.turbines
                    if t.craftnote_project_id
                ]

                if not turbines:
                    if verbose:
                        console.print(
                            f"[yellow]Skipping {farm.name} - no turbines with project IDs[/yellow]"
                        )
                    continue

                progress.update(overall_task, description=f"[cyan]{farm.name}")

                result = await download_wind_farm_files(
                    page=page,
                    wind_farm_name=farm.name,
                    turbines=turbines,
                    base_download_dir=output_dir,
                )

                total_files += result.total_files
                total_errors += result.total_errors
                progress.advance(overall_task, len(turbines))

                if verbose:
                    console.print(f"  {farm.name}: {result.total_files} files")
                if result.total_errors > 0:
                    error_console.print(f"  [red]{farm.name}: {result.total_errors} errors[/red]")

    console.print(f"\n[green]Complete![/green] Downloaded {total_files} files")
    if total_errors > 0:
        error_console.print(f"[red]Total errors: {total_errors}[/red]")
        raise typer.Exit(EXIT_CODE_ERROR)


@app.command("sync")
def sync(
    farm: Annotated[str | None, typer.Option("--farm", "-f", help="Wind farm name to sync")] = None,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", "-o", help="Output directory for downloads")
    ] = Path(DEFAULT_OUTPUT_DIR),
    db_path: Annotated[
        Path, typer.Option("--db", help="Path to download tracking database")
    ] = Path(DEFAULT_DB_PATH),
    headless: Annotated[
        bool, typer.Option("--headless/--no-headless", help="Run browser in headless mode")
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Show what would be downloaded")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable verbose output")] = False,
) -> None:
    """Incremental download - skip already downloaded files."""
    setup_logging(verbose)

    tracker = DownloadTracker(db_path)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Fetching wind farm data...", total=None)
        try:
            wind_farms = get_wind_farms_sync()
        except CraftnoteAPIError as e:
            error_console.print(f"[red]API Error:[/red] {e}")
            raise typer.Exit(EXIT_CODE_ERROR) from e

    if farm:
        matched_farm = find_farm_by_name(wind_farms, farm)
        if not matched_farm:
            error_console.print(f"[red]Wind farm not found:[/red] {farm}")
            raise typer.Exit(EXIT_CODE_ERROR)
        farms_to_sync = [matched_farm]
    else:
        farms_to_sync = [wf for wf in wind_farms if wf.name not in EXCLUDED_FOLDERS]

    if dry_run:
        console.print("[yellow]Dry run mode - checking what would be synced[/yellow]\n")
        existing = tracker.get_download_history()
        existing_ids = {f.file_id for f in existing}
        console.print(f"Already downloaded: {len(existing_ids)} files")
        console.print(f"Would sync {len(farms_to_sync)} wind farm(s)")
        raise typer.Exit(EXIT_CODE_SUCCESS)

    asyncio.run(_sync_farms(farms_to_sync, output_dir, tracker, headless, verbose))


async def _sync_farms(
    farms: list[WindFarm],
    output_dir: Path,
    tracker: DownloadTracker,
    headless: bool,
    verbose: bool,
) -> None:
    from datetime import datetime

    total_downloaded = 0
    total_skipped = 0
    total_errors = 0

    total_turbines = sum(1 for farm in farms for t in farm.turbines if t.craftnote_project_id)

    config = BrowserConfig(headless=headless, executable_path=BRAVE_EXECUTABLE_PATH)
    async with browser_context(config) as context:
        page = await context.new_page()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            overall_task = progress.add_task("[cyan]Syncing...", total=total_turbines)

            for farm in farms:
                for turbine in farm.turbines:
                    if not turbine.craftnote_project_id:
                        continue

                    progress.update(overall_task, description=f"[cyan]{farm.name} / {turbine.name}")

                    try:
                        results = await download_all_project_files(
                            page=page,
                            project_id=turbine.craftnote_project_id,
                            download_dir=output_dir / farm.name / turbine.name,
                        )

                        for result in results:
                            file_id = f"{turbine.craftnote_project_id}_{result.metadata.filename}"

                            if tracker.is_already_downloaded(file_id):
                                total_skipped += 1
                                continue

                            final_path, checksum = save_file(
                                content=result.saved_path.read_bytes(),
                                wind_farm=farm.name,
                                turbine=turbine.name,
                                filename=result.metadata.filename,
                                base_dir=output_dir,
                            )

                            downloaded_file = DownloadedFile(
                                file_id=file_id,
                                filename=result.metadata.filename,
                                file_type=FileType.from_filename(result.metadata.filename),
                                downloaded_at=datetime.now(),
                                path=final_path,
                                checksum=checksum,
                                wind_farm=farm.name,
                                turbine=turbine.name,
                            )
                            tracker.record_download(downloaded_file)
                            total_downloaded += 1

                    except Exception as e:
                        total_errors += 1
                        if verbose:
                            error_console.print(f"[red]Error syncing {turbine.name}: {e}[/red]")

                    progress.advance(overall_task)

    console.print("\n[green]Sync complete![/green]")
    console.print(f"  Downloaded: {total_downloaded}")
    console.print(f"  Skipped: {total_skipped}")
    if total_errors > 0:
        error_console.print(f"  [red]Errors: {total_errors}[/red]")
        raise typer.Exit(EXIT_CODE_ERROR)


@app.command("status")
def status(
    farm: Annotated[
        str | None, typer.Option("--farm", "-f", help="Filter by wind farm name")
    ] = None,
    db_path: Annotated[
        Path, typer.Option("--db", help="Path to download tracking database")
    ] = Path(DEFAULT_DB_PATH),
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable verbose output")] = False,
) -> None:
    """Show download statistics."""
    setup_logging(verbose)

    if not db_path.exists():
        console.print("[yellow]No download history found.[/yellow]")
        console.print(f"Database path: {db_path}")
        raise typer.Exit(EXIT_CODE_SUCCESS)

    tracker = DownloadTracker(db_path)
    downloads = tracker.get_download_history(wind_farm=farm)

    if not downloads:
        if farm:
            console.print(f"[yellow]No downloads found for wind farm: {farm}[/yellow]")
        else:
            console.print("[yellow]No downloads recorded yet.[/yellow]")
        raise typer.Exit(EXIT_CODE_SUCCESS)

    farms_files: dict[str, int] = {}
    farms_turbines: dict[str, set[str]] = {}
    for dl in downloads:
        if dl.wind_farm not in farms_files:
            farms_files[dl.wind_farm] = 0
            farms_turbines[dl.wind_farm] = set()
        farms_files[dl.wind_farm] += 1
        farms_turbines[dl.wind_farm].add(dl.turbine)

    table = Table(title="Download Statistics")
    table.add_column("Wind Farm", style="cyan")
    table.add_column("Files", justify="right", style="green")
    table.add_column("Turbines", justify="right", style="blue")

    total_files = 0
    total_turbines: set[str] = set()

    for farm_name in sorted(farms_files.keys()):
        file_count = farms_files[farm_name]
        turbine_set = farms_turbines[farm_name]
        table.add_row(farm_name, str(file_count), str(len(turbine_set)))
        total_files += file_count
        total_turbines.update(turbine_set)

    console.print(table)
    console.print(f"\nTotal: {total_files} files across {len(total_turbines)} turbines")

    if verbose and downloads:
        console.print("\n[dim]Recent downloads:[/dim]")
        for dl in downloads[:10]:
            console.print(
                f"  {dl.downloaded_at:%Y-%m-%d %H:%M} - {dl.wind_farm}/{dl.turbine}/{dl.filename}"
            )


@app.command("mapping")
def mapping(
    matrix_path: Annotated[
        Path, typer.Option("--matrix-file", "-m", help="Path to Matrix rooms markdown file")
    ] = Path(DEFAULT_MATRIX_MAPPING_PATH),
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable verbose output")] = False,
) -> None:
    """Show Craftnote to Matrix mapping."""
    setup_logging(verbose)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Building mapping...", total=None)
        try:
            wind_farms = get_wind_farms_sync(matrix_path)
        except CraftnoteAPIError as e:
            error_console.print(f"[red]API Error:[/red] {e}")
            raise typer.Exit(EXIT_CODE_ERROR) from e
        except FileNotFoundError as e:
            error_console.print(f"[red]Matrix mapping file not found:[/red] {matrix_path}")
            raise typer.Exit(EXIT_CODE_ERROR) from e

    table = Table(title="Craftnote ↔ Matrix Mapping")
    table.add_column("Wind Farm", style="cyan")
    table.add_column("Craftnote ID", style="dim")
    table.add_column("Matrix Space", style="magenta")
    table.add_column("Turbines", justify="right")
    table.add_column("Matched", justify="right", style="green")

    for farm in sorted(wind_farms, key=lambda f: f.name):
        craftnote_id = farm.craftnote_folder_id or "[none]"
        matrix_space = farm.matrix_space_id or "[none]"
        total_turbines = len(farm.turbines)
        matched = sum(1 for t in farm.turbines if t.matrix_room_id)

        match_style = "green" if matched == total_turbines else "yellow"
        table.add_row(
            farm.name,
            craftnote_id[:12] + "..." if len(craftnote_id) > 15 else craftnote_id,
            matrix_space[:20] + "..." if len(matrix_space) > 23 else matrix_space,
            str(total_turbines),
            f"[{match_style}]{matched}/{total_turbines}[/{match_style}]",
        )

    console.print(table)

    if verbose:
        unmatched_turbines = [
            (farm.name, t.name)
            for farm in wind_farms
            for t in farm.turbines
            if t.craftnote_project_id and not t.matrix_room_id
        ]
        if unmatched_turbines:
            console.print("\n[yellow]Unmatched turbines:[/yellow]")
            for farm_name, turbine_name in unmatched_turbines[:20]:
                console.print(f"  {farm_name} / {turbine_name}")
            if len(unmatched_turbines) > 20:
                console.print(f"  ... and {len(unmatched_turbines) - 20} more")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
