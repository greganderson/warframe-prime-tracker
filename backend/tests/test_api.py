def test_collection_recipe_status(client):
    data = client.get("/api/v1/collection").json()[0]
    assert "owned" not in data
    assert data["missing_count"] == 4
    assert data["ready"] is False


def test_run_confirmation_is_atomic_idempotent_and_undoable(client):
    run = client.post("/api/v1/runs", json={"relic_ids":["lith-b4","meso-b1"]}).json()
    payload = {"item_id":"boar-prime-receiver","idempotency_key":"round-unique-001"}
    first = client.post(f"/api/v1/runs/{run['id']}/confirm", json=payload)
    assert first.status_code == 200 and not first.json()["duplicate"]
    assert all("owned" not in relic for relic in client.get("/api/v1/catalog/relics").json())
    duplicate = client.post(f"/api/v1/runs/{run['id']}/confirm", json=payload)
    assert duplicate.json()["duplicate"] is True
    client.post(f"/api/v1/transactions/{first.json()['transaction_id']}/undo")
    assert client.get("/api/v1/collection").json()[0]["missing_count"] == 4


def test_duplicate_relic_slots_are_valid(client):
    response = client.post("/api/v1/runs", json={"relic_ids":["lith-b4","lith-b4"]})
    assert response.status_code == 201 and len(response.json()["columns"]) == 2


def test_run_rewards_show_mastered_equipment(client):
    client.patch("/api/v1/equipment/boar-prime", json={"mastered":True})
    run = client.post("/api/v1/runs", json={"relic_ids":["lith-b4"]}).json()
    barrel = next(reward for reward in run["columns"][0]["rewards"]
                  if reward["id"] == "boar-prime-barrel")
    assert barrel["mastered"] is True


def test_run_rewards_show_complete_unmastered_sets(client):
    for item_id in ("boar-prime-blueprint", "boar-prime-barrel",
                    "boar-prime-receiver", "boar-prime-stock"):
        client.patch(f"/api/v1/inventory/{item_id}", json={"delta":1})
    run = client.post("/api/v1/runs", json={"relic_ids":["lith-b4"]}).json()
    barrel = next(reward for reward in run["columns"][0]["rewards"]
                  if reward["id"] == "boar-prime-barrel")
    assert barrel["set_complete"] is True
    assert barrel["mastered"] is False


def test_run_rewards_distinguish_an_owned_part_from_a_complete_set(client):
    client.patch("/api/v1/inventory/boar-prime-barrel", json={"delta":1})
    run = client.post("/api/v1/runs", json={"relic_ids":["lith-b4"]}).json()
    barrel = next(reward for reward in run["columns"][0]["rewards"]
                  if reward["id"] == "boar-prime-barrel")
    assert barrel["part_owned"] is True
    assert barrel["set_complete"] is False


def test_platinum_highlight_threshold_is_shared_and_validated(client):
    assert client.get("/api/v1/settings").json()["platinum_highlight_threshold"] == 20
    assert client.patch("/api/v1/settings",json={"platinum_highlight_threshold":45}).status_code == 200
    assert client.get("/api/v1/settings").json()["platinum_highlight_threshold"] == 45
    assert client.patch("/api/v1/settings",json={"platinum_highlight_threshold":101}).status_code == 422


def test_inventory_cannot_be_negative(client):
    response = client.patch("/api/v1/inventory/boar-prime-barrel", json={"delta":-1})
    assert response.status_code == 409


def test_build_set_consumes_required_parts(client):
    assert client.post("/api/v1/equipment/boar-prime/build").status_code == 409
    for item_id in ("boar-prime-blueprint", "boar-prime-barrel",
                    "boar-prime-receiver", "boar-prime-stock"):
        client.patch(f"/api/v1/inventory/{item_id}", json={"delta":1})
    client.patch("/api/v1/inventory/boar-prime-barrel", json={"delta":1})
    assert client.post("/api/v1/equipment/boar-prime/build").status_code == 200
    boar = client.get("/api/v1/collection").json()[0]
    assert boar["missing_count"] == 3
    assert {p["id"]:p["owned"] for p in boar["parts"]}["boar-prime-barrel"] == 1
