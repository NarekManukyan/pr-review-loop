# python — Python service / library (STUB)

**Loaded when:** `pyproject.toml` / `requirements.txt` / `setup.cfg` present.
**Composes with:** universal lenses. Deepen for the framework in use (FastAPI/Django/
Flask) once evidence accrues. **Status: stub** (~7 repos in the portfolio).

## Idiom rules (top known)
- **Async correctness (maps U1/U7):** blocking I/O inside an `async def` (sync DB/HTTP
  call) stalls the event loop; un-awaited coroutines; shared mutable state across async
  tasks without a lock. **P1**.
- **Concurrency (maps U1):** read-then-write races on a row → `SELECT … FOR UPDATE` /
  guarded `UPDATE`; Django `select_for_update`/`F()` expressions, or optimistic version.
- **Fail-closed config (maps U4):** `os.getenv("SECRET", "")` with a silent default that
  disables a gate; missing input validation (pydantic/DRF serializer). **P1**.
- **Idempotency (maps U3):** payment/create endpoints without an idempotency key.
- **Resource lifecycle (maps U12):** files/sessions/clients not closed (use context
  managers); DB connections leaked; unbounded queries (missing `LIMIT`/pagination).
- **Error handling (maps U7):** bare `except:` / `except Exception: pass` swallowing;
  broad catches hiding failures.
- **Django/DRF/FastAPI:** N+1 (`select_related`/`prefetch_related`); migrations
  reversible + numbered without collision; DRF permission classes fail-closed;
  FastAPI dependency-injected auth on mutating routes.

## CI gates (for Reviewer D)
Mirror CI: `ruff`/`flake8` + `black --check`/`ruff format --check`, `mypy`, `pytest`;
`pip install`/`poetry install` on the lockfile; migrations against a throwaway DB.

## Generated / skip
`__pycache__/`, `*.pyc`, `.venv/`, `dist/`, `build/`, generated protobuf `*_pb2.py`.

## Notes
STUB — promote from evidence.
