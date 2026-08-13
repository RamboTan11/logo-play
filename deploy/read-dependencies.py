"""Print project runtime dependencies as JSON for the PowerShell bootstrapper."""

import json
import sys
import tomllib
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: read-dependencies.py <pyproject.toml>")

    configuration_path = Path(sys.argv[1]).resolve()
    with configuration_path.open("rb") as file:
        configuration = tomllib.load(file)
    print(json.dumps(configuration["project"]["dependencies"]))


if __name__ == "__main__":
    main()
