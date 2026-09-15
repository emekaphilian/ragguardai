install:
	python -m pip install -r requirements.txt

test:
	pytest -q

demo:
	python scripts/run_pipeline.py

evaluate:
	python scripts/evaluate.py

api:
	uvicorn ragguard.api.app:app --reload
