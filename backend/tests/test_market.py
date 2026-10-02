import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import market
from app.db import Item, session_scope


def stats(median):
    return {"payload":{"statistics_closed":{"48hours":[{"volume":3,"median":median}],"90days":[]}}}


@pytest.fixture()
def fake_market(client, monkeypatch):
    """Route warframe.market calls to a handler and record the slugs requested."""
    calls=[]; responses={}
    def handler(request):
        slug=request.url.path.split("/")[-2]; calls.append(slug)
        status,body=responses.get(slug,(404,{}))
        return httpx.Response(status,json=body)
    real=httpx.Client
    monkeypatch.setattr(market.httpx,"Client",lambda **kwargs: real(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setattr(market,"limiter",market.RateLimiter(interval=0))
    return calls,responses


def test_prices_are_saved_per_item_and_skipped_while_fresh(client, fake_market):
    calls,responses=fake_market
    responses["boar_prime_barrel"]=(200,stats(12))
    result=client.post("/api/v1/market/prices",json={"item_ids":["boar-prime-barrel","boar-prime-stock"]}).json()
    assert result=={"updated":1,"unavailable":["boar-prime-stock"]}
    barrel=next(p for p in client.get("/api/v1/collection").json()[0]["parts"] if p["id"]=="boar-prime-barrel")
    assert barrel["market_median"]==12 and barrel["market_updated_at"]
    calls.clear()
    client.post("/api/v1/market/prices",json={"item_ids":["boar-prime-barrel"]})
    assert calls==[]


def test_server_errors_back_off_and_do_not_mark_the_item(client, fake_market):
    calls,responses=fake_market
    responses["boar_prime_barrel"]=(503,{})
    assert client.post("/api/v1/market/prices",json={"item_ids":["boar-prime-barrel"]}).json()["unavailable"]==["boar-prime-barrel"]
    assert market.limiter.backoff==5.0
    with session_scope() as session: assert session.get(Item,"boar-prime-barrel").market_updated_at is None


def test_crawl_prefers_owned_then_unpriced_then_oldest(client):
    client.patch("/api/v1/inventory/boar-prime-stock",json={"delta":1})
    assert market.next_stale_item()=="boar-prime-stock"
    old=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    fresh=datetime.now(timezone.utc).isoformat()
    with session_scope() as session:
        for item in session.exec(market._tradeable(session)).all(): item.market_updated_at=fresh
        session.get(Item,"boar-prime-stock").market_updated_at=fresh
        session.get(Item,"boar-prime-receiver").market_updated_at=old
    assert market.next_stale_item()=="boar-prime-receiver"
    with session_scope() as session: session.get(Item,"boar-prime-receiver").market_updated_at=fresh
    assert market.next_stale_item() is None
    assert client.get("/api/v1/market/status").json()=={"total":5,"fresh":5,"running":False}


def test_priority_requests_go_before_background_requests():
    limiter=market.RateLimiter(interval=0.05); order=[]
    limiter.acquire(priority=False)
    def take(name,priority): limiter.acquire(priority); order.append(name)
    background=threading.Thread(target=take,args=("background",False)); background.start()
    time.sleep(0.01)
    priority=threading.Thread(target=take,args=("priority",True)); priority.start()
    background.join(); priority.join()
    assert order==["priority","background"]
