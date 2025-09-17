import pathlib
import frontmatter
import tomllib
from enum import Enum

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    ValidationInfo,
    field_validator,
    model_validator,
)


class ChangeType(str, Enum):
    """Defines the allowed types of changes."""

    FEATURE = "feature"
    FIX = "fix"
    DOCS = "docs"
    INTERNAL = "internal"


class Fragment(BaseModel):
    """A model for a changelog fragment. Validation is context-aware."""

    change_type: ChangeType
    description: str
    ticket: str | None = None

    @field_validator("description")
    @classmethod
    def description_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Description must not be empty.")
        return v.strip()

    @model_validator(mode="after")
    def check_configured_rules(self, info: ValidationInfo) -> "Fragment":
        """Access the config from the validation context to apply optional rules."""
        # The 'context' is passed in during validation.
        config: ChangeloggerConfig | None = info.context.get("config")
        if not config or not config.validation:
            return self  # No validation rules configured, so we're done.

        # Rule: require_ticket_for
        if config.validation.require_ticket_for:
            if (
                self.change_type.value in config.validation.require_ticket_for
                and not self.ticket
            ):
                raise ValueError(
                    f"Based on your configuration, a 'ticket' is required for change type '{self.change_type.value}'"
                )

        return self


class SectionConfig(BaseModel):
    title: str


class ValidationConfig(BaseModel):
    require_ticket_for: list[str] | None = None


class TicketConfig(BaseModel):
    base_url: HttpUrl | None = None


class ChangeloggerConfig(BaseModel):
    changelog_file: pathlib.Path = Field(default=pathlib.Path("CHANGELOG.md"))
    # The name change is reflected here
    changelog_dir: pathlib.Path = Field(default=pathlib.Path(".changelog/"))
    sections: dict[str, SectionConfig]
    validation: ValidationConfig | None = Field(
        default_factory=ValidationConfig
    )
    tickets: TicketConfig | None = Field(default_factory=TicketConfig)


def get_project_version() -> str:
    """Read the version string from the [project] section of pyproject.toml."""
    pyproject_path = pathlib.Path("pyproject.toml")
    if not pyproject_path.exists():
        raise FileNotFoundError("pyproject.toml not found.")

    with pyproject_path.open("rb") as f:
        pyproject_data = tomllib.load(f)

    try:
        version = pyproject_data["project"]["version"]
        return version
    except KeyError:
        raise ValueError("Could not find [project].version in pyproject.toml.")


def load_config() -> ChangeloggerConfig:
    """Load the project configuration from the 'pyproject.toml'."""
    pyproject_path = pathlib.Path("pyproject.toml")
    if not pyproject_path.exists():
        raise FileNotFoundError("pyproject.toml not found.")

    with pyproject_path.open("rb") as f:
        pyproject_data = tomllib.load(f)

    config_data = pyproject_data.get("tool", {}).get("changelogger", {})
    if not config_data:
        raise ValueError(
            "[tool.changelogger] section not found in pyproject.toml."
        )

    return ChangeloggerConfig(**config_data)


def parse_fragment(path: pathlib.Path, config: ChangeloggerConfig) -> Fragment:
    """Loads a Markdown file with YAML front matter and validates it."""
    try:
        # Use the frontmatter library to load the file
        post = frontmatter.load(path)
    except Exception as e:
        # Catch errors if the file is malformed
        raise ValueError(f"Could not parse front matter. Original error: {e}")

    description = post.content.strip()

    # Combine the metadata from the front matter with the description
    data = {**post.metadata, "description": description}
    return Fragment.model_validate(data, context={"config": config})
