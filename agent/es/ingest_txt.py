# agent/es/ingest_txt.py
"""Compatibility wrapper for the TXT-to-Elasticsearch ingestion CLI.

The implementation lives in :mod:`data_ingestion.txt_to_es.ingest_txt` so all
ETL-style ingestion entry points stay under ``data_ingestion/``.
"""

from data_ingestion.txt_to_es.ingest_txt import *  # noqa: F403
from data_ingestion.txt_to_es.ingest_txt import main


if __name__ == "__main__":
    main()
