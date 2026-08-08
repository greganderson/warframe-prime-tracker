import os
os.environ["TRACKER_DB"] = "/tmp/warframe-tracker-test.db"

import pytest
from fastapi.testclient import TestClient
from app.db import DB_PATH
from app.main import app

@pytest.fixture()
def client():
    DB_PATH.unlink(missing_ok=True)
    with TestClient(app) as c:
        yield c
    DB_PATH.unlink(missing_ok=True)
