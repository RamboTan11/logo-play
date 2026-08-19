"""Regression guard for batch candidate dispatch concurrency."""

from pathlib import Path


def test_batch_generation_has_no_fixed_parallelism_gate() -> None:
    service_path = Path(__file__).parent / "src" / "services" / "batch_generation_service.py"
    service_source = service_path.read_text(encoding="utf-8")

    assert "MAX_PARALLELISM" not in service_source
    assert "asyncio.Semaphore" not in service_source
    assert "asyncio.gather(*(self._execute_candidate(job.id) for job in pending))" in service_source
