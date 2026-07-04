"""Shared MongoDB client and collection handles.

Connection settings come from the environment: ``MONGO_DB_URL`` (required) and
``MONGO_DB_NAME`` (optional, defaults to ``BharatBhraman_v2``).

TLS certificates are verified by default via certifi's CA bundle rather than the
system store, because many environments (notably macOS Python builds) lack a
local CA store even though MongoDB Atlas presents publicly-signed certs. Setting
``MONGO_TLS_INSECURE=true`` is an escape hatch for local servers using
self-signed certs.
"""
import os
import certifi
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URL = os.environ.get('MONGO_DB_URL')
if not MONGO_URL:
    raise RuntimeError(
        "MONGO_DB_URL environment variable is required (see .env.example)."
    )

DB_NAME = os.environ.get('MONGO_DB_NAME', 'BharatBhraman_v2')

_tls_insecure = os.environ.get('MONGO_TLS_INSECURE', 'false').lower() in ('1', 'true', 'yes')

if _tls_insecure:
    client = MongoClient(MONGO_URL, tlsAllowInvalidCertificates=True)
else:
    client = MongoClient(MONGO_URL, tlsCAFile=certifi.where())

db = client[DB_NAME]

languages = db['languages']
content = db['content']
guides = db['guides']
users = db['users']
trips = db['trips']
metrics = db['metrics']
