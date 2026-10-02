from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import func, or_
from sqlmodel import Session, select

from .db import Inventory, Item, Recipe, RelicReward, engine, session_scope

API_BASE="https://api.warframe.market/v1/items/"
HEADERS={"Platform":"pc","Language":"en","User-Agent":"warframe-prime-tracker/1.0"}
# warframe.market asks for at most 3 requests/second; this is the floor for every request.
MIN_INTERVAL=0.34
BACKGROUND_INTERVAL=3.0
BACKGROUND_MAX_AGE=timedelta(hours=12)
REWARD_MAX_AGE=timedelta(minutes=30)
IDLE_CHECK=600
MAX_BACKOFF=300.0

log=logging.getLogger(__name__)


def _slug(name:str)->str:
    return re.sub(r"_+","_",re.sub(r"[^a-z0-9]+","_",name.lower())).strip("_")


def _now()->datetime: return datetime.now(timezone.utc)


def _fresh(item:Item,max_age:timedelta)->bool:
    try: return item.market_updated_at is not None and _now()-datetime.fromisoformat(item.market_updated_at)<max_age
    except ValueError: return False


class RateLimiter:
    """One request at a time across the app. Priority callers (the rewards screen) go before the background crawl,
    and errors from the API pause everyone with a doubling backoff."""
    def __init__(self,interval:float=MIN_INTERVAL):
        self.interval=interval; self.condition=threading.Condition()
        self.next_at=0.0; self.backoff=0.0; self.priority_waiting=0

    def acquire(self,priority:bool)->None:
        with self.condition:
            if priority: self.priority_waiting+=1
            try:
                while True:
                    delay=self.next_at-time.monotonic()
                    if delay<=0 and (priority or not self.priority_waiting): break
                    self.condition.wait(delay if delay>0 else None)
                self.next_at=time.monotonic()+self.interval
            finally:
                if priority: self.priority_waiting-=1; self.condition.notify_all()

    def succeeded(self)->None:
        with self.condition: self.backoff=0.0

    def failed(self)->None:
        with self.condition:
            self.backoff=min(MAX_BACKOFF,max(5.0,self.backoff*2))
            self.next_at=max(self.next_at,time.monotonic()+self.backoff); self.condition.notify_all()


limiter=RateLimiter()


def _median(stats:dict)->tuple[float,str]|None:
    recent=[row for row in stats.get("48hours",[]) if row.get("volume",0)>0 and row.get("median") is not None]
    fallback=[row for row in stats.get("90days",[]) if row.get("volume",0)>0 and row.get("median") is not None]
    rows=recent or fallback
    return (float(rows[-1]["median"]),"48h" if recent else "90d") if rows else None


def fetch_price(client:httpx.Client,item_id:str,priority:bool)->bool:
    """Fetch one item's price and save it in its own short transaction, so callers can see progress as it lands.
    Returns False when the item has no market price. Raises httpx.HTTPError for transient failures."""
    with Session(engine) as session:
        item=session.get(Item,item_id)
        if not item: return False
        name=item.name
    limiter.acquire(priority)
    try:
        response=client.get(f"{API_BASE}{_slug(name)}/statistics")
        if response.status_code==429 or response.status_code>=500: response.raise_for_status()
    except httpx.HTTPError as error:
        limiter.failed()
        raise httpx.HTTPError(f"{name}: {error}") from error
    limiter.succeeded()
    try: price=_median(response.json()["payload"]["statistics_closed"]) if response.is_success else None
    except (KeyError,ValueError,TypeError): price=None
    with session_scope() as session:
        item=session.get(Item,item_id)
        if not item: return False
        # Record the attempt even without a price so the crawl doesn't retry untradeable items every pass.
        item.market_updated_at=_now().isoformat()
        if price: item.market_median,item.market_window=price
    return price is not None


def refresh_market_prices(item_ids:list[str])->dict:
    """Rewards screen: price these items now, ahead of the background crawl."""
    updated=0; unavailable=[]
    with Session(engine) as session:
        items=[item for item_id in dict.fromkeys(item_ids) if (item:=session.get(Item,item_id))]
        stale=[item.id for item in items if item.market_median is None or not _fresh(item,REWARD_MAX_AGE)]
    updated+=len(items)-len(stale)
    with httpx.Client(headers=HEADERS,timeout=20,follow_redirects=True) as client:
        for item_id in stale:
            try: priced=fetch_price(client,item_id,priority=True)
            except httpx.HTTPError: priced=False
            if priced: updated+=1
            else: unavailable.append(item_id)
    return {"updated":updated,"unavailable":unavailable}


def _tradeable(session:Session):
    return select(Item).where(or_(Item.id.in_(select(Recipe.component_id)),Item.id.in_(select(RelicReward.item_id))))


def next_stale_item()->str|None:
    """Oldest-priced tradeable part, owned parts first."""
    cutoff=(_now()-BACKGROUND_MAX_AGE).isoformat()
    with Session(engine) as session:
        owned=func.coalesce(select(Inventory.quantity).where(Inventory.item_id==Item.id).scalar_subquery(),0)
        statement=(_tradeable(session).where(or_(Item.market_updated_at.is_(None),Item.market_updated_at<cutoff))
                   .order_by((owned>0).desc(),Item.market_updated_at.is_not(None),Item.market_updated_at).limit(1))
        item=session.exec(statement).first()
        return item.id if item else None


def status()->dict:
    cutoff=(_now()-BACKGROUND_MAX_AGE).isoformat()
    with Session(engine) as session:
        items=session.exec(_tradeable(session)).all()
    return {"total":len(items),"fresh":sum(1 for item in items if item.market_updated_at and item.market_updated_at>=cutoff),
            "running":crawler.running()}


class BackgroundCrawler:
    def __init__(self): self.stop_event=threading.Event(); self.thread:threading.Thread|None=None

    def start(self)->None:
        if os.getenv("TRACKER_DISABLE_SYNC") or self.running(): return
        self.stop_event.clear()
        self.thread=threading.Thread(target=self._run,name="market-crawler",daemon=True); self.thread.start()

    def stop(self)->None:
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=5)

    def running(self)->bool: return bool(self.thread and self.thread.is_alive())

    def _run(self)->None:
        with httpx.Client(headers=HEADERS,timeout=20,follow_redirects=True) as client:
            while not self.stop_event.is_set():
                try: item_id=next_stale_item()
                except Exception: log.exception("Market crawl query failed"); item_id=None
                if not item_id: self.stop_event.wait(IDLE_CHECK); continue
                try: fetch_price(client,item_id,priority=False)
                except httpx.HTTPError as error: log.warning("Market price fetch failed: %s",error)
                except Exception: log.exception("Market price update failed")
                self.stop_event.wait(BACKGROUND_INTERVAL)


crawler=BackgroundCrawler()
