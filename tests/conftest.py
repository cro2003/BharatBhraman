"""Test environment bootstrap.

Loads a local ``.env`` when present so live integration tests use real
credentials, then falls back to inert defaults for the values the app package
requires at import time. This lets the offline suite import ``app`` in CI, where
no ``.env`` exists and the connection layer would otherwise fail-fast on a
missing ``MONGO_DB_URL`` (the Mongo client connects lazily, so the dummy URL is
never dialed by offline tests).
"""
import os

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("MONGO_DB_URL", "mongodb://localhost:27017/bharatbhraman_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
