import datetime
import pathlib
from collections import defaultdict
from typing import Dict, List

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


def archive_fragments(
    version_dir: pathlib.Path, config: ChangeloggerConfig
) -> None:
    """Move the released fragment folder to a '.released' subdirectory."""
    released_dir = config.changelog_dir / ".released"
    released_dir.mkdir(exist_ok=True)

    # Move '.changelog/v1.2.0' to '.changelog/.released/v1.2.0'
    target_path = released_dir / version_dir.name
    version_dir.rename(target_path)


def prepend_to_changelog(
    new_content: str, changelog_file: pathlib.Path
) -> None:
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
            continue  # Skip if section in config isn't a valid ChangeType

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
