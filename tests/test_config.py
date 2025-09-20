import pathlib

import pytest

from chnagelogger.config import (
    ChangeloggerConfig,
    load_config,
)

DATA_FILE_PATH = pathlib.Path(__file__).parent / "data"


def test_load_config() -> None:
    pyproject_path = DATA_FILE_PATH / "test_pyproject.toml"
    result = load_config(pyproject_path)
    assert isinstance(result, ChangeloggerConfig)


@pytest.mark.parametrize(
    ("pyproject_path", "expected_error", "expected_error_message"),
    [
        (
            DATA_FILE_PATH / "test_pyproject_n.toml",
            FileNotFoundError,
            "pyproject.toml not found.",
        ),
        (
            DATA_FILE_PATH / "test_pyproject_no_tool.toml",
            ValueError,
            "[tool.changelogger] section not found in pyproject.toml.",
        ),
    ],
)
def test_load_config_no_tool(
    pyproject_path: pathlib.Path, expected_error: Exception, expected_error_message: str
) -> None:
    with pytest.raises(expected_error) as err:
        load_config(pyproject_path)
    assert str(err.value) == expected_error_message
