# Upstream data contract

The catalog refresh imports the complete Lith, Meso, Neo, and Axi list plus Prime Warframes, weapons, blueprints, components, and nested dual-weapon requirements from Public Export. It collapses relic refinement variants, validates both catalog sizes, and commits through SQLModel sessions. A failed fetch or validation leaves the last usable data available. Other production catalog sources remain to be completed as described below.

Sources and cadence:

- Warframe Public Export and official drop tables: daily, for equipment, recipes, relic contents, rarity, locations, rotations, and chances.
- Official Prime Resurgence page: daily, layered over normal availability classification.
- Warframe.Market API (`/v1/items/{slug}/statistics`, one request per item; there is no bulk price endpoint): prefer the 48-hour median and fall back to the 90-day median. Implemented in `backend/app/market.py`:
  - A background task prices every tradeable part (recipe components and relic rewards) at one request every 3 seconds, owned parts first, refreshing prices older than 12 hours. `items.market_updated_at` records the last attempt, including items with no market listing, so they are not retried every pass.
  - The rewards screen requests its items immediately, skipping prices fetched in the last 30 minutes. These requests go ahead of the background queue.
  - Every request passes through one shared limiter (at most one request per 0.34 s, under the documented 3 requests/second). HTTP 429, 5xx and network errors pause all requests with a backoff that starts at 5 seconds and doubles up to 5 minutes; the failed item is retried later.
  - Each price is written in its own short transaction so other writes are never blocked by network calls.

Each successful refresh should record source URL, fetch time, content hash, parser version, and effective timestamp in `metadata`. Never turn a network failure into an empty catalog. Availability precedence is `exclusive`, `resurgence`, `special`, `farmable`, `vaulted`, then `unknown`; stale or ambiguous entries become `unknown`.

Public Export and drop-table formats change without notice. Before enabling unattended synchronization, implement fixture-based parsers for the current official payloads and test malformed input, stale data, Resurgence transitions, nested/dual-weapon recipes, and atomic rollback. The tracker intentionally starts and remains usable offline with its latest SQLite state.
