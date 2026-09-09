# Joe Lynch Super Investor List

## Purpose

MOSE Codex Lab maintains a reviewable working list of 13F filers. The current
screen may contain more than 50 names while Joe decides how broad the final
roster should be. Filing behavior nominates candidates; it does not silently
remove a manager from Joe's working list.

The app uses an inclusive default: every unmarked investor is included. Joe's
explicit X removes an investor, and Joe's check records an explicit keep. A
cleared choice returns the investor to the automatic included state. This lets
Joe review the strongest names without having to approve every row manually.

## Joe-style nomination screen

The quarterly universe job discovers the latest Form 13F filers and reviews up
to eight quarters by CUSIP. Its comparison baseline is recalculated from the
latest history of the concentrated, patient members of Joe's current roster on
every run. It looks for a $150 million to $75
billion representative public-equity book, 3-50 positions, at least six usable
quarters, a top-10 weight of at least 55%, limited fund exposure, and enough
long-only exposure for the 13F to be meaningful.

Candidates are separated into two lanes:

- **Core patient value:** no more than 25% estimated turnover, at least a
  six-quarter median hold, and at least 65% in the top 10 positions.
- **Adventurous value:** up to 42% estimated turnover, at least a four-quarter
  median hold, and at least 55% in the top 10. This permits more change and
  uncertainty without admitting short-term trading behavior.

The 0-100 Joe Fit score weights concentration (25), patience (25), disciplined
turnover (20), similarity to the current roster (20), and cloneability (10).
It does not claim to identify a value philosophy, investment performance, or
drawdown skill. A 13F cannot establish those facts by itself.

## Human qualification review

Before making a final roster decision, review primary-source investment letters, interviews, the
fund mandate, succession, use of shorts and derivatives, private or foreign
holdings omitted from 13F, and whether the public filing is representative
enough to follow. Evidence must show a valuation-aware process and a willingness
to hold through ordinary volatility. Record a short reason for every decision.

Existing CIK-map investors are grandfathered so the current dashboard does not
lose coverage. The universe report still shows their failed gates, making it
possible to prune the roster deliberately instead of silently.

## Monitoring after approval

Every active approved CIK is checked four times daily for SC 13D/G, Form 4,
13F amendments, and configured N-PORT filings. Verified first-party RSS/Atom
sources for letters, interviews, podcasts, and posts are configured in
`reference-data/investor-sources.json`.

The official SEC bulk-data path remains preferred. If SEC blocks the GitHub
runner, the universe job can use the separately gated forms13f.com index as a
transport fallback. That fallback retains the original SEC filing URL for each
candidate and is never treated as final verification. `SEC_TRANSPORT_READY`
enables the official scheduled path; `FORMS13F_FALLBACK_READY` explicitly
enables the fallback. Manual workflow runs remain available.

Structured filings may affect conviction. Words and news can create a watch
item, but do not change a score. Unknown tickers and directions remain null or
neutral; the system does not infer them from a headline.

## 13F accuracy controls

- Holdings are matched quarter to quarter by CUSIP. A ticker resolved in one
  quarter and unresolved in another still represents the same security.
- Form 13F XML values filed since January 3, 2023 are treated as nearest-dollar
  values. Derived files and Supabase rows use U.S. dollars throughout.
- Duplicate information-table rows for one CUSIP are aggregated before a
  change is classified or stored.
- Additive amendments are merged into the original filing; restatements replace
  it for the affected quarter.
- Each generated database payload is checked for duplicate primary keys,
  unresolved pseudo-tickers, and broken investor/security/filing references.

The current copied history resolves 1,980 of 3,647 CUSIPs, representing about
99.5% of latest-quarter reported value. The remaining identifiers stay visible
as unresolved and are not guessed.

## Approval operation

In the app, open **Super Investors > Joe's List**. **My list** is the default view:
it includes every investor except those with an explicit X. Use the check to
record an explicit keep, the X to remove a manager, and the clear button to
return a manager to automatic inclusion. The **Removed by Joe** filter makes
the exclusions easy to audit. Choices save to the isolated browser/Firebase
state.

The quantitative score and evidence column are still decision support. They do
not override Joe's explicit removal, and they do not require Joe to click every
strong candidate before it appears on the working list.

After Joe selects a candidate, record the decision with:

```bash
python scripts/review_investor_candidate.py approve --cik 1234567 --reason "Concentrated long-term record and representative 13F"
```

Rejecting a current manager marks the CIK inactive rather than deleting its
history. The next 13F and monitoring runs skip inactive CIKs.
