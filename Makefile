.PHONY: install run eval scenarios demo clean

install:
	pip install -r requirements.txt

run:
	uvicorn controlplane.app:app --port 8000

eval:
	python eval/build_dataset.py && python eval/run_eval.py --sweep

scenarios:
	python demo/run_scenarios.py

demo: 
	@echo "Start the server with 'make run' in one terminal, then 'make scenarios' in another."

clean:
	rm -f data/ledger.jsonl data/calibration.json eval/results.json
