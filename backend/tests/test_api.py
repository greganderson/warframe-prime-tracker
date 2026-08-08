def test_collection_recipe_status(client):
    data = client.get("/api/v1/collection").json()[0]
    assert data["missing_count"] == 4
    assert data["ready"] is False


def test_run_confirmation_is_atomic_idempotent_and_undoable(client):
    run = client.post("/api/v1/runs", json={"relic_ids":["lith-b4","meso-b1"],"user_slot":0}).json()
    payload = {"item_id":"boar-prime-receiver","idempotency_key":"round-unique-001"}
    first = client.post(f"/api/v1/runs/{run['id']}/confirm", json=payload)
    assert first.status_code == 200 and not first.json()["duplicate"]
    # Another squad member's reward consumes only our Lith relic.
    relics = {x["id"]:x["owned"] for x in client.get("/api/v1/catalog/relics").json()}
    assert relics == {"lith-b4":2,"meso-b1":2}
    duplicate = client.post(f"/api/v1/runs/{run['id']}/confirm", json=payload)
    assert duplicate.json()["duplicate"] is True
    client.post(f"/api/v1/transactions/{first.json()['transaction_id']}/undo")
    relics = {x["id"]:x["owned"] for x in client.get("/api/v1/catalog/relics").json()}
    assert relics["lith-b4"] == 3


def test_duplicate_relic_slots_are_valid(client):
    response = client.post("/api/v1/runs", json={"relic_ids":["lith-b4","lith-b4"],"user_slot":1})
    assert response.status_code == 201 and len(response.json()["columns"]) == 2


def test_inventory_cannot_be_negative(client):
    response = client.patch("/api/v1/inventory/boar-prime-barrel", json={"delta":-1})
    assert response.status_code == 409
