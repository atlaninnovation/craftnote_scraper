# Development Conventions

## Philosophy

- **Simplicity is king** — the simplest solution that works is the best solution
- **Self-documenting code** — if it needs comments, refactor it
- **Functional over OOP** — pure functions, composition, immutability
- **Commit early, commit often** — small, focused, verified commits
- **No shortcuts on quality** — fix errors properly, never suppress warnings without fixing the root cause

---

## Cross-Language Design Principles

These rules apply **to all languages**, regardless of tooling.

### Code Design
- Prefer **pure functions** where feasible; isolate side effects.
- Organize code so changes are easy and predictable.
- Avoid hidden state and mutable globals.

### Types & Data
- Declare types explicitly at *module boundaries*.
- Use language-specific type features to model domain constraints (e.g., Rust enums, TS `zod` schemas).

### Error Handling
- Treat errors as structured data, not control flow.
- **Catch specific exceptions**, never bare `except:` or `except Exception:` unless re-raising.
- Add contextual information when propagating errors.
- Avoid swallowing errors silently.
- Let unexpected errors crash — they reveal bugs. Only catch what you can handle.

### Resource Management
- **Always use context managers** (`with` statements) for resources that need cleanup.
- Never manually call `.close()` — context managers ensure cleanup even on exceptions.
- For custom resources, implement `@contextmanager` or `__enter__`/`__exit__`.

### Testing
- Prefer **unit tests** for pure logic and **integration tests** for I/O boundaries.
- Assert behavior, not implementation details.
- Aim for reproducibility and determinism.
- Use **AAA pattern** (Arrange, Act, Assert):
  ```python
  def test_user_creation():
      # Arrange
      name = "Alice"

      # Act
      user = create_user(name)

      # Assert
      assert user.name == name
  ```

### Snapshot Testing with inline-snapshot

Use `inline-snapshot` to freeze expected values directly in test files. Start with empty `snapshot()` and let the tool fill them in.

**Key insight:** Snapshots store expected values in git, making tests easy to update when data changes. Tests that call DB functions still need the database - use `pytestmark = pytest.mark.skipif(...)` to skip in CI.

**When to use:**
- API response validation (freeze full response structure)
- Database query results (freeze returned data)
- Complex nested structures where manual assertions are tedious

**Workflow:**
```bash
# Write test with empty snapshot()
assert result == snapshot()

# Generate snapshots (fills in empty snapshot() calls)
uv run pytest --inline-snapshot=create

# Update snapshots when data changes intentionally
uv run pytest --inline-snapshot=fix

# Commit filled snapshots so CI has expected values
git add tests/
```

**Example:**
```python
from inline_snapshot import snapshot
from dirty_equals import IsInt, IsDatetime

def test_user():
    user = create_user(name="test")

    # Start with empty snapshot(), run --inline-snapshot=create to fill
    assert user.dict() == snapshot()

    # For dynamic values, use dirty-equals (preserved on update)
    assert user.dict() == snapshot({
        "id": IsInt(),           # Matches any int, preserved on --fix
        "name": "test",
        "created_at": IsDatetime(),
    })

    # Or reference the value directly (also preserved)
    assert user.dict() == snapshot({
        "id": user.id,           # Preserved on --fix
        "name": "test",
    })
```

**Key rules:**
- Start with empty `snapshot()`, never manually write expected values
- Use `dirty-equals` (`IsInt`, `IsDatetime`) for dynamic values you don't want frozen
- Convert data to builtins before snapshotting (avoid constructor signature issues)
- Review `git diff` before committing updated snapshots
- Commit filled snapshots to git so CI can validate without database

### Comments & Docs
- Use comments to explain *why*, never *what* — if you need a "what" comment, rename or refactor instead.
- Bad: `timeout = 30  # API timeout in seconds`
- Good: `API_TIMEOUT_SECONDS = 30`
- Public APIs must have documentation; internal helper functions usually do not.
- If code needs lots of comments, **refactor** instead.

### ASCII Diagrams & Tables
- When drawing ASCII box diagrams, **verify all lines have the same visual width**.
- Use this Python snippet to check visual width (accounts for UTF-8 box-drawing characters):
  ```python
  import unicodedata
  def visual_width(s):
      return sum(2 if unicodedata.east_asian_width(c) in ('F', 'W') else 1 for c in s)
  ```
- All lines within a box must have identical `visual_width()` values.
- Markdown tables should have aligned columns — pad cells with spaces for readability.

### Git & Collaboration
- Use a *feature-branch workflow* with clear naming (e.g., `feat/…`, `fix/…`, `refactor/…`).
- Rebase or squash commits to maintain clean history.
- Use PRs with reviews, tests, and clear descriptions.

### Architecture & Boundaries
- Divide code into *layers* (core logic, side effects, interfaces).
- Keep modules small and focused.
- Separate business logic from runtime and framework concerns.

---

## Layered Architecture

### Core Principles

**1. Dependencies Flow One Direction**

If A → B → C, then C can import B and A, but A cannot import C. This single rule eliminates circular imports entirely.

**2. Leaf Modules Are Your Foundation**

Modules with zero internal imports are the most stable. Put shared types, constants, and pure data structures here. Everything else builds on top.

**3. Group by Reason to Change**
- Data shapes change when contracts change
- Clients change when external APIs change
- Business logic changes when requirements change
- Interfaces change when consumers change

Same reason to change = same module.

**4. Configuration Sits Low**

Config should be readable by all layers but depend on nothing. When config imports business logic, you've inverted the hierarchy.

**5. Ports and Adapters Emerge Naturally**
- **Core**: types, business logic (pure, no I/O)
- **Adapters**: clients (outbound), servers (inbound)
- **Entry points**: CLI, main functions

The core doesn't know how it's called or what it calls.

**6. Comments Signal Missing Structure**

Section dividers and "what" comments often mean the file is doing too much. Clear module boundaries make code self-documenting.

**7. Name Layers by Role, Not Technology**

`services/` not `openai/`. `client.py` not `http.py`. Roles are stable; technologies change.

---

## Project Structure

```
AudITScraper/
├── backend/
│   ├── api/                     # FastAPI REST API
│   │   ├── main.py              # API entry point
│   │   ├── routers/             # API route handlers
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── crud/                # Database operations
│   │   ├── db/                  # Database connections
│   │   ├── security/            # Auth & permissions
│   │   └── utils/               # Helper utilities
│   └── audit_dagster/           # Dagster data pipelines
│       └── audit_dagster/
│           ├── repository.py    # Dagster repository definition
│           ├── ops/             # Dagster operations (jobs)
│           ├── schedules/       # Scheduled jobs
│           ├── sensors/         # Event-driven triggers
│           └── job_configs/     # Job configurations
├── frontend/
│   └── web/                     # Flask web frontend
│       ├── app.py               # Flask entry point
│       ├── routes/              # Route handlers
│       ├── templates/           # Jinja2 templates
│       ├── static/              # CSS, JS, assets
│       └── utils/               # Helper utilities
├── deployment/                  # Docker configs
├── Data/                        # Data files & imports
│   └── ImportData/              # Import source directories
└── docs/                        # Documentation
```

### Layer Responsibilities

| Layer                     | Purpose                          | Dependencies                   |
|---------------------------|----------------------------------|--------------------------------|
| `backend/api/models/`     | SQLAlchemy ORM models            | None (leaf module)             |
| `backend/api/schemas/`    | Pydantic request/response types  | None (leaf module)             |
| `backend/api/crud/`       | Database CRUD operations         | models, schemas                |
| `backend/api/routers/`    | API endpoints                    | crud, schemas, security        |
| `backend/api/security/`   | Authentication & authorization   | models                         |
| `backend/audit_dagster/ops/` | Data pipeline operations      | External APIs, DB              |
| `frontend/web/routes/`    | Web page handlers                | API client, utils              |

### Import Rules

- **Absolute imports only**: `from backend.api.models import User`
- **No circular imports**: lower layers cannot import from higher layers
- **models/ and schemas/ are leaves**: no internal imports allowed

---

## Python

### Tools
| Tool | Purpose | Install |
|------|---------|---------|
| `uv` | Package/project manager, Python versions | `brew install uv` |
| `ruff` | Linter & formatter | `uv tool install ruff` |
| `ty` | Type checker (Astral, 10-100x faster than mypy) | `uv tool install ty` |
| `pytest` | Testing | `uv add --dev pytest` |

### Workflow
```bash
uv init myproject && cd myproject
uv add httpx polars
uv add --dev pytest

uv run python script.py
uv run pytest

# One-off (no install)
uvx ruff check .
uvx ty check .
```

### Before Commit

Run the verification loop:
```bash
uvx ruff format .
uvx ruff check --fix .
uvx ty check .
uv run pytest
```

**Pre-commit checklist** (all must pass):
- [ ] `ruff format .` — no files reformatted
- [ ] `ruff check .` — no errors
- [ ] `ty check .` — all checks passed
- [ ] `pytest` — all tests passed
- [ ] Security scan passed (if auth/API/frontend code changed)
- [ ] No obvious comments (code should be self-documenting)
- [ ] No section divider comments (`# ====...`)
- [ ] Comments explain *why*, not *what*

### Security Scan

Run a security vulnerability scan **before every commit that touches auth, API, or frontend code**, and **after every rebase onto main** (upstream changes may introduce regressions). Start the API server, then test every attack vector:

```bash
export UFARM_SECRET_KEY="test-key-for-scanning-only-32b!"
uv run uvicorn ufarm.api.main:app --port 8000 &
```

**Checklist** (all must pass):

- [ ] **Unauthenticated access** — every protected endpoint returns 401 without a token
- [ ] **Token manipulation** — garbage, empty, wrong-secret, expired, ghost-user, `alg=none`, missing-`sub` tokens all return 401
- [ ] **CORS** — evil origins get no `access-control-allow-origin` header; only allowed origins do
- [ ] **SQL injection** — `' OR 1=1 --` in email/password fields returns 401
- [ ] **Path traversal** — `../../etc/passwd` on both API and frontend returns 404
- [ ] **Docs/OpenAPI** — `/docs` returns 401 without token, 200 with valid token
- [ ] **Rate limiting** — 6th failed login attempt returns 429
- [ ] **Privilege escalation** — editor role gets 403 on all admin endpoints (list/create/update/delete users)
- [ ] **User enumeration** — same error message for valid-email-wrong-password and invalid-email
- [ ] **Inactive user** — deactivated user login returns 400
- [ ] **Hardcoded secrets** — `grep -rn` finds no passwords or secret key fallbacks in `src/`
- [ ] **Secret key enforcement** — app refuses to start with empty `UFARM_SECRET_KEY`
- [ ] **Seed password enforcement** — `ufarm auth seed` fails without `UFARM_SEED_PASSWORD_*` env vars
- [ ] **Admin panel** — `/admin/` returns 302 redirect to login

Example scan commands:
```bash
# Unauthenticated access
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/auth/me  # expect 401

# CORS
curl -s -D- -H "Origin: https://evil.com" http://localhost:8000/health | grep access-control  # expect empty

# Rate limiting
for i in $(seq 1 6); do
  curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/auth/login \
    -d "username=x@x.com&password=wrong${i}"
done  # expect: 401 401 401 401 401 429

# Privilege escalation (with editor token)
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${EDITOR_TOKEN}" \
  http://localhost:8000/users/  # expect 403

# Hardcoded secrets
grep -rn "oilimeodlanyer\|strangepassword42\|dev-secret" src/  # expect no results
```

### No Suppressing Errors

**Never ignore linter/type errors without fixing the underlying issue.**

- Do NOT add `# noqa`, `# type: ignore`, or similar suppressions as a first resort
- Do NOT add rules to `ignore` lists in config files to bypass errors
- If a tool reports an error, **fix the code** — the tool is usually right
- Security warnings (like SQL injection) are real threats even with "trusted" internal data
- If you truly believe an error is a false positive after investigation, document *why* in a comment

Example of what NOT to do:
```python
# BAD: Suppressing instead of fixing
conn.execute(f"SELECT * FROM {table}")  # noqa: S608

# GOOD: Validate input to prevent injection
safe_table = _validate_identifier(table)
conn.execute(f"SELECT * FROM {safe_table}")
```

### Style
```python
async def fetch_users(user_ids: list[int]) -> list[User]:
    """Fetch users by their IDs."""
    async with httpx.AsyncClient() as client:
        tasks = [client.get(f"/users/{id}") for id in user_ids]
        responses = await asyncio.gather(*tasks)
        return [User(**r.json()) for r in responses]
```

- Type annotations: always, Python 3.12+ (`list[T]`, `X | None`)
- Docstrings: brief, public APIs only
- Async for I/O

### Mandatory Libraries

| Use | Instead of | Why |
|-----|------------|-----|
| `polars` | `pandas` | Faster, lazy evaluation, better API |
| `httpx` | `requests` | Async support, connection pooling |

### HTTP Client Pattern

Always use `httpx.AsyncClient` with session reuse:

```python
async with httpx.AsyncClient() as client:
    response = await client.get(url)
    # reuse client for multiple requests
```

### Data Analysis Pattern

```python
import polars as pl

df = pl.read_csv("data.csv")
result = (
    df.lazy()
    .filter(pl.col("status") == "active")
    .group_by("category")
    .agg(pl.col("value").sum())
    .collect()
)
```

---

## Git

### Commit Early, Commit Often

- **Small, focused commits** — each commit should do one thing
- **Commit before refactoring** — create a checkpoint you can roll back to
- **Commit after each fix passes verification** — don't batch unrelated changes
- **Never commit broken code** — all commits must pass the verification loop

This ensures you can always `git revert` or `git reset` to a known good state.

### Commit Format
```
type: short description
```

| Type | Use |
|------|-----|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation |
| `chore:` | Maintenance |
| `refactor:` | Restructure (no behavior change) |
| `test:` | Tests |

### Pull Requests
- **Title**: same format as commits (`type: description`)
- **Description**: explain the *why*, not just the *what*
- **Before/after**: show output changes when relevant
- **Link issues**: reference related issues/discussions
- Keep PRs focused—one logical change per PR

---

## Quick Reference

| Lang | Format | Lint | Type Check | Test |
|------|--------|------|------------|------|
| Python | `ruff format .` | `ruff check --fix .` | `ty check .` | `pytest` |

---

**The Loop:** Change → Verify → Commit → Repeat

If it's not tested, it's not done.
