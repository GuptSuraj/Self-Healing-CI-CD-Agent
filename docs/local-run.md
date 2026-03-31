# Local Run Guide

## Backend

1. Create and activate a Python 3.11+ virtual environment.
2. Install the API package:

```bash
python -m pip install ./apps/api
```

3. Run migrations:

```bash
alembic -c apps/api/alembic.ini upgrade head
```

4. Start the API:

```bash
PYTHONPATH=apps/api/src python -m uvicorn self_healing_agent.api.main:app --host 127.0.0.1 --port 8000
```

5. Start the worker in another terminal:

```bash
PYTHONPATH=apps/api/src python -c "from self_healing_agent.worker import run_worker_loop; run_worker_loop()"
```

## Dashboard

```bash
cd apps/dashboard
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

## GitHub integration smoke check

Once the API is running and GitHub App settings are configured:

```bash
curl http://127.0.0.1:8000/api/integrations/github/status
curl http://127.0.0.1:8000/api/integrations/github/repositories/<owner>/<repo>/probe
```

## Docker validation smoke check

Enable execution:

```bash
export SHCA_ENABLE_VALIDATION_EXECUTION=true
```

If you want the validator to prepare its own repository checkout from GitHub:

```bash
export SHCA_ENABLE_VALIDATION_REPO_SYNC=true
```

Otherwise, attach a local checkout path in the failure context:

```json
{
  "context": {
    "local_repo_path": "/absolute/path/to/repository"
  }
}
```
