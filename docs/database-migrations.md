# Database Migrations

The API now uses Alembic for schema management.

## Files

- `apps/api/alembic.ini`
- `apps/api/migrations/env.py`
- `apps/api/migrations/versions/20260330_000001_initial_schema.py`

## Usage

Upgrade the database:

```bash
alembic -c apps/api/alembic.ini upgrade head
```

Create a new revision after schema changes:

```bash
alembic -c apps/api/alembic.ini revision -m "describe change"
```

Autogenerate a revision:

```bash
alembic -c apps/api/alembic.ini revision --autogenerate -m "describe change"
```

Downgrade one revision:

```bash
alembic -c apps/api/alembic.ini downgrade -1
```

## Startup Behavior

By default, the API does not mutate the database schema on startup.

If you want the service to apply migrations automatically during boot, set:

```bash
SHCA_RUN_DB_MIGRATIONS_ON_STARTUP=true
```

That path runs `upgrade head` programmatically.
