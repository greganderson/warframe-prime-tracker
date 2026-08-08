# Upstream data contract

The relic picker imports the complete Lith, Meso, Neo, and Axi list from Public Export, collapses refinement variants, validates the catalog size, and commits it in one SQLite transaction. A failed fetch or validation leaves current tables untouched. Other production catalog sources remain to be completed as described below.

Sources and cadence:

- Warframe Public Export and official drop tables: daily, for equipment, recipes, relic contents, rarity, locations, rotations, and chances.
- Official Prime Resurgence page: daily, layered over normal availability classification.
- Warframe.Market documented API: every 30 minutes; prefer active 48-hour statistics and fall back to the 90-day median. Respect API rate-limit headers.

Each successful refresh should record source URL, fetch time, content hash, parser version, and effective timestamp in `metadata`. Never turn a network failure into an empty catalog. Availability precedence is `exclusive`, `resurgence`, `special`, `farmable`, `vaulted`, then `unknown`; stale or ambiguous entries become `unknown`.

Public Export and drop-table formats change without notice. Before enabling unattended synchronization, implement fixture-based parsers for the current official payloads and test malformed input, stale data, Resurgence transitions, nested/dual-weapon recipes, and atomic rollback. The tracker intentionally starts and remains usable offline with its latest SQLite state.
