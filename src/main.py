import datetime
import pathlib
from collections import defaultdict

import typer
from pydantic import ValidationError
from rich.console import Console

from config import (
    ChangeloggerConfig,
    ChangeType,
    Fragment,
    get_project_version,
    load_config,
    parse_fragment,
)

app = typer.Typer(help="A simple changelog manager.")
console = Console()


def parse_and_group_fragments(
    version_dir: pathlib.Path, config: ChangeloggerConfig
) -> (dict[ChangeType, list[Fragment]], list[str]):
    grouped = defaultdict(list)
    errors = []

    for fragment_file in version_dir.glob("*.md"):
        try:
            # Pass the loaded config to the parser function
            fragment = parse_fragment(fragment_file, config)
            grouped[fragment.change_type].append(fragment)
        except (ValidationError, ValueError) as e:
            error_msg = str(e)
            if isinstance(e, ValidationError):
                error_msg = e.errors()[0]["msg"]
            errors.append(
                f"File [bold magenta]{fragment_file.name}[/bold magenta]: {error_msg}"
            )

    return grouped, errors


def archive_fragments(version_dir: pathlib.Path, config: ChangeloggerConfig) -> None:
    """Move the released fragment folder to a `.released` subdirectory."""
    released_dir = config.changelog_dir / ".released"
    released_dir.mkdir(exist_ok=True)

    # Move `.changelog/v1.2.0` to `.changelog/.released/v1.2.0`
    target_path = released_dir / version_dir.name
    version_dir.rename(target_path)


def prepend_to_changelog(new_content: str, changelog_file: pathlib.Path) -> None:
    """Prepends the new content to the changelog file."""
    original_content = ""
    if changelog_file.exists():
        original_content = changelog_file.read_text()

    # Write new content, followed by a newline, followed by the old content
    changelog_file.write_text(f"{new_content}\n{original_content}")


def generate_markdown(
    version: str,
    fragments: dict[ChangeType, list[Fragment]],
    config: ChangeloggerConfig,
) -> str:
    """Build the markdown, reading all presentation from the config file."""
    today = datetime.date.today().isoformat()
    lines = [f"## [{version}] - {today}\n"]

    # Iterate through the sections in the order they appear in pyproject.toml
    for type_str, section_config in config.sections.items():
        try:
            change_type_enum = ChangeType(type_str)
        except ValueError:
            continue  # Skip if section in config isn`t a valid ChangeType

        if change_type_enum in fragments:
            # Use the title from the config file
            lines.append(f"### {section_config.title}\n")

            for frag in fragments[change_type_enum]:
                # Add ticket link if it exists and is configured
                ticket_part = ""
                if frag.ticket and config.tickets and config.tickets.base_url:
                    ticket_url = f"{config.tickets.base_url}{frag.ticket}"
                    ticket_part = f" ([{frag.ticket}]({ticket_url}))"
                lines.append(f"- {frag.description}{ticket_part}")
            lines.append("")

    return "\n".join(lines)


@app.command()
def start() -> None:
    """Create a new versioned directory for changelog fragments based on pyproject.toml."""
    try:
        config = load_config()
        current_version = get_project_version()
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise typer.Exit(code=1) from e

    version_dir = config.changelog_dir / f"v{current_version}"

    if version_dir.exists():
        console.print(
            f"[yellow]Directory already exists for version {current_version}:[/yellow] `{version_dir}`"
        )
        raise typer.Exit

    console.print(
        f"🚀 Starting work on version [bold cyan]v{current_version}[/bold cyan]."
    )
    version_dir.mkdir(parents=True)
    console.print(f"✅ Created changelog directory: `{version_dir}`")
    console.print("You can now add your .md fragment files there.")


@app.command()
def release(
    dry_run: str = typer.Option(
        default=False,
        help="Don`t write files, just print what would be done.",
    ),
) -> None:
    """Generate a new changelog from the fragments of the current project version."""
    try:
        config = load_config()
        current_version = get_project_version()
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise typer.Exit(code=1) from e

    # Dynamically determine the fragments directory to read from
    version_dir = config.changelog_dir / f"v{current_version}"
    if not version_dir.exists() or not version_dir.is_dir():
        console.print(
            f"[bold red]Error: Changelog directory not found for current version `{current_version}`.[/bold red]"
        )
        console.print(
            f"Run `changelogger start` first to create it at: `{version_dir}`"
        )
        raise typer.Exit(code=1)

    console.print(f"🔍 Reading fragments from [cyan]`{version_dir}`[/cyan]...")

    # Parse fragments from the versioned directory
    fragments_by_type, errors = parse_and_group_fragments(version_dir, config)
    if errors:
        console.print(
            "[bold red]Errors found in fragment files. Please fix before releasing:[/bold red]"
        )
        for error in errors:
            console.print(f"- {error}")
        raise typer.Exit(code=1)

    if not fragments_by_type:
        console.print("[yellow]No changelog fragments found. Exiting.[/yellow]")
        raise typer.Exit

    # Generate markdown (the function call needs the version)
    new_content = generate_markdown(f"v{current_version}", fragments_by_type, config)
    if dry_run:
        console.print(
            "\n[bold yellow]--dry-run enabled. No files will be changed.[/bold yellow]"
        )
        raise typer.Exit

    # Prepend to changelog
    prepend_to_changelog(new_content, config.changelog_file)
    console.print(
        f"\n✅ Updated [bold magenta]`{config.changelog_file}`[/bold magenta]."
    )

    # Archive the fragment folder instead of deleting its contents
    archive_fragments(version_dir, config)
    console.print(f"🗄️ Archived fragment directory for version v{current_version}.")
    console.print("\n🎉 [bold green]Release complete![/bold green]")
