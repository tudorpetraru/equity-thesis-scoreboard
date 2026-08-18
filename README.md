# Equity Thesis Track Record

A static, tamper-evident public record of timestamped equity thesis calls and their benchmark-relative outcomes.

The website publishes no thesis documents. Fresh calls appear first as sealed commitments containing no ticker or direction. After the two-day embargo, each call reveals its sanitized record and random salt. Git history supplies the third-party timestamp; `scripts/verify.py` proves the revealed content matches the earlier commitment.

## Verify the record

Clone this repository and run:

```sh
python3 scripts/verify.py
python3 scripts/verify.py --call-id <id>
git log --follow -p -- data/calls.json
```

The commitment convention is SHA-256 over UTF-8 `canonical_json(record) + salt`. Canonical JSON uses sorted keys, separators `,` and `:`, and no ASCII escaping. A later void is lifecycle metadata, so verification restores `voided` to `null`, its value at seal time.

## Methodology v1

- Data: daily dividend- and split-adjusted closes from Yahoo Finance chart data, with Stooq daily closes as an automatic fallback. Fallback records are flagged as not dividend-adjusted. Benchmark: SPY.
- Entry: the first trading session whose close occurs at or after `generated_at`; SPY uses the same session.
- Horizons: 182 and 365 calendar days after entry. Each uses the last close on or before the horizon date.
- Excess return: `(P_h / P_0 - 1) - (B_h / B_0 - 1)`.
- Buy and strong-buy calls are correct when excess return is positive. Sell and strong-sell calls are correct when it is negative. Hold is correct when absolute excess return is at most five percentage points.
- Source `AVOID` calls normalize to `STRONG_SELL`. Conviction is displayed as issued (`HIGH`, `MEDIUM-HIGH`, `MEDIUM`, or `LOW`) and does not affect scoring.
- Pending horizons are not scored. Delistings or acquisitions use the last available close and are flagged.
- Target and stop crossings use daily closes and are informational only.
- Headline aggregates include revealed, non-voided, live calls only. Backfilled calls remain visually separate and are excluded.

Version 1 is frozen. A future methodology version must be displayed and scored separately.

## Public data

`data/calls.json` is the source of truth:

- `format_version`, `methodology_version`, and `embargo_days`
- `calls`, ordered by seal time
- sealed entries: call identifier, state, seal time, commitment, methodology version
- revealed entries: the sealed fields plus salt and the sanitized call record

`data/performance.json` is derived daily:

- `computed_at`, format and methodology versions
- `calls`: per-call price source, adjustment flag, entry prices, horizon returns and verdicts, data-gap and delisting flags, and target/stop outcome
- `aggregates`: record counts, rating counts, and per-horizon totals, hit rates, mean/median excess returns, equal-weight excess return, and rating breakdowns

## Automated safeguards

- `scripts/validate.py` validates the exact call contract and rejects deleted, reordered, or edited revealed calls. A one-way reveal and a one-time `null` to void-object transition are the only lifecycle changes.
- `scripts/sanitize.py` scans all public text for identifier, local-path, runtime-internal, and credential patterns. An optional repository secret adds a hash-only check for a private repository name.
- `scripts/score.py` refreshes prices and rebuilds performance daily. Unavailable tickers become visible data gaps instead of failing the whole refresh.
- The test suite covers weekend and after-close entries, the inclusive hold band, delisting, scoring math, commitments, schemas, append-only behavior, and planted privacy violations.

Run all local checks with:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/validate.py data/calls.json
python3 scripts/sanitize.py .
```

## Disclosure

These documents are AI-generated research, not investment advice or a personal recommendation. Tickers are user-requested, so the sample is biased toward popular names. Past performance does not predict future results. No position disclosures are implied.

## License

MIT
