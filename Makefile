.PHONY: api-install api-migrate api-run worker-run api-test dashboard-install dashboard-run dashboard-build

api-install:
	python -m pip install ./apps/api

api-migrate:
	alembic -c apps/api/alembic.ini upgrade head

api-run:
	PYTHONPATH=apps/api/src python -m uvicorn self_healing_agent.api.main:app --host 127.0.0.1 --port 8000

worker-run:
	PYTHONPATH=apps/api/src python -c "from self_healing_agent.worker import run_worker_loop; run_worker_loop()"

api-test:
	PYTHONPATH=apps/api/src python -m unittest discover -s apps/api/tests

dashboard-install:
	cd apps/dashboard && npm install

dashboard-run:
	cd apps/dashboard && npm run dev

dashboard-build:
	cd apps/dashboard && npm run build
