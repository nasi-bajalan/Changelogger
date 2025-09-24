import importlib
import logging
import sys
import tomllib
from enum import Enum
from pathlib import Path
from types import TracebackType

import frontmatter
from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    ValidationInfo,
    field_validator,
    model_validator,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
        # The `context` is passed in during validation.
        config: ChangeloggerConfig | None = info.context.get("config")
        if not config or not config.validation:
            return self  # No validation rules configured, so we`re done.

        # Rule: require_ticket_for
        if config.validation.require_ticket_for and (
            self.change_type.value in config.validation.require_ticket_for
            and not self.ticket
        ):
            msg = f"Based on your configuration, a `ticket` is required for change type `{self.change_type.value}`"
            raise ValueError(msg)

        return self


class SectionConfig(BaseModel):
    title: str


class ValidationConfig(BaseModel):
    require_ticket_for: list[str] | None = None


class TicketConfig(BaseModel):
    base_url: HttpUrl | None = None


class ChangeloggerConfig(BaseModel):
    changelog_file: Path = Field(default=Path("CHANGELOG.md"))
    # The name change is reflected here
    changelog_dir: Path = Field(default=Path(".changelog/"))
    sections: dict[str, SectionConfig]
    validation: ValidationConfig | None = Field(default_factory=ValidationConfig)
    tickets: TicketConfig | None = Field(default_factory=TicketConfig)


# Helper context manager from above
class TemporaryPath:
    """A context manager for temporarily adding a path to sys.path."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> None:
        sys.path.insert(0, str(self.path))

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        # Ensure the path is removed even if an error occurs
        if str(self.path) in sys.path:
            sys.path.remove(str(self.path))


def get_project_version(pyproject_path: Path) -> str | None:
    """
    Retrieve the package version from a pyproject.toml file, resolving
    dynamic versions by importing code or reading files.

    Args:
        pyproject_path: The file path to the pyproject.toml file.

    Returns:
        The resolved version string if found, otherwise None.

    """
    pyproject_path = pyproject_path.resolve()

    if not pyproject_path.is_file():
        logger.debug(f"Error: File not found at '{pyproject_path}'")

    try:
        with Path.open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        logger.debug(f"Error parsing '{pyproject_path}': {e}")

    # Static version checks (higher priority)
    project = data.get("project", {})
    if "version" in project:
        return project["version"]

    poetry = data.get("tool", {}).get("poetry", {})
    if "version" in poetry:
        return poetry["version"]

    # Dynamic version check
    if "version" in project.get("dynamic", []):
        # --- Resolve dynamic version from source ---
        dynamic_config = data.get("tool", {}).get("setuptools", {}).get("dynamic", {})
        version_config = dynamic_config.get("version")

        if version_config and isinstance(version_config, dict):
            # Case 1: Dynamic version from a file
            if "file" in version_config:
                project_root = pyproject_path.parent
                version_file_path = project_root / version_config["file"]
                if version_file_path.is_file():
                    return version_file_path.read_text().strip()
                logger.debug(
                    f"Error: Dynamic version file '{version_file_path}' not found."
                )

            # Case 2: Dynamic version from a module attribute
            elif "attr" in version_config:
                attr_string = version_config["attr"]
                try:
                    # Split module path from attribute name
                    module_name, attr_name = attr_string.rsplit(".", 1)
                except ValueError:
                    logger.debug(f"Error: Invalid 'attr' format: {attr_string}")

                # Temporarily add project root to path to allow import
                with TemporaryPath(project_root):
                    try:
                        module = importlib.import_module(module_name)
                        version = getattr(module, attr_name)
                        return str(version)
                    except ImportError:
                        logger.debug(
                            f"Error: Could not import module '{module_name}' to find version."
                        )
                    except AttributeError:
                        logger.debug(
                            f"Error: Attribute '{attr_name}' not found in module '{module_name}'."
                        )
    return None


def load_config(
    pyproject_path: Path = Path("pyproject.toml"),
) -> ChangeloggerConfig:
    """Load the project configuration from the `pyproject.toml`."""
    if not pyproject_path.exists():
        raise FileNotFoundError("pyproject.toml not found.")

    with pyproject_path.open("rb") as f:
        pyproject_data = tomllib.load(f)

    config_data = pyproject_data.get("tool", {}).get("changelogger", {})
    if not config_data:
        raise ValueError("[tool.changelogger] section not found in pyproject.toml.")

    return ChangeloggerConfig(**config_data)


def parse_fragment(path: Path, config: ChangeloggerConfig) -> Fragment:
    """Load a Markdown file with front matter and validates it."""
    try:
        post = frontmatter.load(path)
    except Exception as e:
        # Catch errors if the file is malformed
        msg = f"Could not parse front matter. Original error: {e}"
        raise ValueError(msg) from e

    description = post.content.strip()

    # Combine the metadata from the front matter with the description
    data = {**post.metadata, "description": description}
    return Fragment.model_validate(data, context={"config": config})
