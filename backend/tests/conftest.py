import os
os.environ["TRACKER_DB"] = "/tmp/warframe-tracker-test.db"
os.environ["TRACKER_DISABLE_SYNC"] = "1"

import pytest
from fastapi.testclient import TestClient
from app.db import DB_PATH, engine
from app.main import app

@pytest.fixture()
def client():
    engine.dispose()
    for path in (DB_PATH, DB_PATH.with_name(DB_PATH.name + "-wal"), DB_PATH.with_name(DB_PATH.name + "-shm")):
        path.unlink(missing_ok=True)
    with TestClient(app) as c:
        yield c
    engine.dispose()
    for path in (DB_PATH, DB_PATH.with_name(DB_PATH.name + "-wal"), DB_PATH.with_name(DB_PATH.name + "-shm")):
        path.unlink(missing_ok=True)
