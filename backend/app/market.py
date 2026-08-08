from __future__ import annotations

import re
import time
from datetime import datetime, timezone, timedelta

import httpx
from sqlmodel import select

from .db import Item, session_scope

API_BASE="https://api.warframe.market/v1/items/"


def _slug(name:str)->str:
    return re.sub(r"_+","_",re.sub(r"[^a-z0-9]+","_",name.lower())).strip("_")


def refresh_market_prices(item_ids:list[str])->dict:
    updated=0; unavailable=[]
    headers={"Platform":"pc","Language":"en","User-Agent":"warframe-prime-tracker/1.0"}
    with session_scope() as session, httpx.Client(headers=headers,timeout=20,follow_redirects=True) as client:
        items=[session.get(Item,item_id) for item_id in dict.fromkeys(item_ids)]
        for index,item in enumerate(item for item in items if item):
            try: fresh=datetime.now(timezone.utc)-datetime.fromisoformat(item.updated_at)<timedelta(minutes=30)
            except (TypeError,ValueError): fresh=False
            if item.market_median is not None and fresh:
                updated+=1
                continue
            try:
                response=client.get(f"{API_BASE}{_slug(item.name)}/statistics"); response.raise_for_status()
                stats=response.json()["payload"]["statistics_closed"]
                recent=[row for row in stats.get("48hours",[]) if row.get("volume",0)>0 and row.get("median") is not None]
                fallback=[row for row in stats.get("90days",[]) if row.get("volume",0)>0 and row.get("median") is not None]
                row=(recent or fallback)[-1]
                item.market_median=float(row["median"]); item.market_window="48h" if recent else "90d"
                item.updated_at=datetime.now(timezone.utc).isoformat(); updated+=1
            except (httpx.HTTPError,KeyError,ValueError,IndexError): unavailable.append(item.id)
            if index<len(items)-1: time.sleep(0.34)
    return {"updated":updated,"unavailable":unavailable}
