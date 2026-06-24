import os
from pymongo import MongoClient

_client = None

def get_db():
    global _client
    if _client is None:
        uri = os.environ.get("MONGO_URI", "")
        _client = MongoClient(uri)
    db_name = os.environ.get("MONGO_DB", "healthandglowServer")
    return _client[db_name]
