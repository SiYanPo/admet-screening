.PHONY: help check tables full hashes clean

help:
	@echo "admet-screening - reproducibility entry points"
	@echo ""
	@echo "  make check     environment, dependencies, data and artefacts (seconds)"
	@echo "  make tables    regenerate Tables 1, 2b, 2c, 3 and verify checksums (under 1 min)"
	@echo "  make full      also retrain all five endpoints (about 1.5 h)"
	@echo "  make hashes    rewrite deposit/EXPECTED_SHA256.json after an intentional change"

check:
	./reproduce.sh --check

tables:
	./reproduce.sh

full:
	./reproduce.sh --full

hashes:
	python tools/verify_table_hashes.py --update

# `make tables` is the default so that a bare `make` does the cheap, useful thing.
default: tables
