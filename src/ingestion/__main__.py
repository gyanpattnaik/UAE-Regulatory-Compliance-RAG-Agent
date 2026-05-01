"""Makes the ingestion package runnable as python -m src.ingestion.cli"""
from .cli import main

if __name__ == "__main__":
    main()
