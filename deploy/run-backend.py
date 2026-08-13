"""Start the production ASGI server with explicit local source paths."""

import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
RUNTIME_ROOT = PROJECT_ROOT / "deploy" / "runtime"

for source_root in (BACKEND_ROOT, PROJECT_ROOT):
    source_path = str(source_root)
    if source_path not in sys.path:
        sys.path.insert(0, source_path)


def main() -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    sys.stdout = (RUNTIME_ROOT / "backend.stdout.log").open(
        "a", encoding="utf-8", buffering=1
    )
    sys.stderr = (RUNTIME_ROOT / "backend.stderr.log").open(
        "a", encoding="utf-8", buffering=1
    )
    uvicorn.run(
        "src.production:create_app",
        factory=True,
        host="127.0.0.1",
        port=8099,
        log_level="info",
    )


if __name__ == "__main__":
    main()
