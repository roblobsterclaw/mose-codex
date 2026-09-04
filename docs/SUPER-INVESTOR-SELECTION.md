# Joe Lynch Top 50 Super Investors

## Purpose

MOSE Codex Lab maintains a deliberately small approved roster of 13F filers.
The target is 50. The SEC screen nominates candidates; Joe approves or rejects
every addition. No score can approve a manager automatically.

## Quantitative nomination screen

The quarterly universe job reads the latest eight SEC bulk Form 13F data sets.
It keys holdings by CUSIP and evaluates:

- Reported portfolio size between $300 million and $50 billion.
- No more than 50 long positions.
- At least six usable quarters of history.
- Median current-position holding age of at least six quarters.
- Estimated average quarterly turnover no greater than 25%.
- At least 90% of the reported long-plus-option value in non-option positions.
- No obvious bank, pension, trust-department, index, or quantitative mandate.

The 0-100 nomination score weights concentration (30), patience (30), low
turnover (25), reporting consistency (10), and cloneability (5). It does not
claim to measure performance or drawdown skill because 13F data alone cannot
support those claims accurately.

## Human qualification review

Before approval, review the manager's long-term record, investment letters,
interviews, fund mandate, succession, use of shorts and derivatives, private or
foreign holdings omitted from 13F, and whether a public 13F is representative
enough to copy. Record a short reason for every decision.

Existing CIK-map investors are grandfathered so the current dashboard does not
lose coverage. The universe report still shows their failed gates, making it
possible to prune the roster deliberately instead of silently.

## Monitoring after approval

Every active approved CIK is checked four times daily for SC 13D/G, Form 4,
13F amendments, and configured N-PORT filings. Verified first-party RSS/Atom
sources for letters, interviews, podcasts, and posts are configured in
`reference-data/investor-sources.json`.

Structured filings may affect conviction. Words and news can create a watch
item, but do not change a score. Unknown tickers and directions remain null or
neutral; the system does not infer them from a headline.

## Approval operation

After Joe selects a candidate, record the decision with:

```bash
python scripts/review_investor_candidate.py approve --cik 1234567 --reason "Concentrated long-term record and representative 13F"
```

Rejecting a current manager marks the CIK inactive rather than deleting its
history. The next 13F and monitoring runs skip inactive CIKs.
