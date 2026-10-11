build-DealFeedFunction:
	mkdir -p "$(ARTIFACTS_DIR)/backend"
	cp *.py catalog.json service_categories.json "$(ARTIFACTS_DIR)/backend/"
	python3 -m pip install -r requirements.txt -t "$(ARTIFACTS_DIR)"
