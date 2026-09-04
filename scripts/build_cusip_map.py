#!/usr/bin/env python3
"""Bootstrap CUSIP -> ticker resolution for the 13F universe, offline.

Layer 2 unlock (see docs/CODEX-HANDOFF-2026-09.md §6). Without a working
CUSIP map only 37 of ~1,300 latest-quarter names resolve, so every consensus,
eligibility and guard-rail feature is computed on a sliver of the book.

Resolution order, most to least trustworthy:
  1. cusip-seed  : a CUSIP the raw 13F pull already resolved in any quarter,
                   plus reference-data/ticker-map.json (hand-verified)
  2. alias       : curated issuer-name -> ticker table below
  3. name-exact  : normalised issuer name == normalised ticker-directory name
  4. name-expand : same, after expanding 13F filing abbreviations
                   (AMER->AMERICA, MATLS->MATERIALS, ...)
Anything else is written to the `unresolved` list with its dollar weight so
the OpenFIGI pass (Codex, Layer 2) knows what to chase first.

Outputs:
  reference-data/cusip-map.json   {cusip: {ticker, name, method}}
  eligible-universe.json          latest quarter: ticker -> holders[]
Run:  python3 scripts/build_cusip_map.py
"""
from __future__ import annotations
import json, re, collections
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "sec-13f-filings.json"
DIR = ROOT / "reference-data" / "ticker-directory.json"
TMAP = ROOT / "reference-data" / "ticker-map.json"
OUT_MAP = ROOT / "reference-data" / "cusip-map.json"
OUT_ELIG = ROOT / "eligible-universe.json"

STOP = r"\b(INC|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|HOLDINGS|HOLDING|HLDGS|HLDG|GROUP|GRP|CLASS|CL|COM|COMMON|NEW|SHS|SH|ADR|ADS|SA|NV|N V|THE|DEL|ORD|STK|USD|A|B|C)\b"
ABBR = {
    "AMER": "AMERICA", "PETE": "PETROLEUM", "MATLS": "MATERIALS", "INSTRS": "INSTRUMENTS",
    "PAC": "PACIFIC", "INTL": "INTERNATIONAL", "FINL": "FINANCIAL", "NATL": "NATIONAL",
    "RY": "RAILWAY", "MFG": "MANUFACTURING", "MANUFAC": "MANUFACTURING", "TECHN": "TECHNOLOGIES",
    "TECH": "TECHNOLOGY", "CMNTYS": "COMMUNITIES", "APT": "APARTMENT", "SOFTWAR": "SOFTWARE",
    "COR": "CORP", "SVCS": "SERVICES", "SVC": "SERVICE", "SYS": "SYSTEMS", "PRODS": "PRODUCTS",
    "PWR": "POWER", "ELEC": "ELECTRIC", "MTN": "", "BE": "", "INDS": "INDUSTRIES",
    "IND": "INDUSTRIES", "ENTMT": "ENTERTAINMENT", "COMMUNICATNS": "COMMUNICATIONS",
    "RES": "RESOURCES", "GLOBL": "GLOBAL", "PPTYS": "PROPERTIES", "PPTY": "PROPERTY",
    "TR": "TRUST", "BK": "BANK", "BANCORP": "BANCORP", "GP": "GROUP", "HEALTHCR": "HEALTHCARE",
    "PHARMACEUTICLS": "PHARMACEUTICALS", "LABS": "LABORATORIES", "MED": "MEDICAL",
    "DEVS": "DEVICES", "SEMICONDUCTOR": "SEMICONDUCTOR", "MOTORS": "MOTORS", "AIRLS": "AIRLINES",
}
ALIAS = {  # normalised issuer-name prefix -> ticker (checked as whole-token prefix)
    "BANK OF AMER": "BAC", "BANK OF AMERICA": "BAC", "GE AEROSPACE": "GE", "GENERAL ELECTRIC": "GE",
    "OCCIDENTAL PETE": "OXY", "OCCIDENTAL PETROLEUM": "OXY", "TAIWAN SEMICONDUCTOR": "TSM",
    "SPACE EXPLORATION TECHN": "SPCX", "SPACE EXPLORATION TECHNOLOGIES": "SPCX", "SPACE EXPL TECHNOLOGIES": "SPCX",
    "PROCTER GAMBLE": "PG", "CHURCH DWIGHT": "CHD", "JOHNSON CONTROLS": "JCI", "AUTOMATIC DATA PROCESSING": "ADP", "STMICROELECTRONICS": "STM", "CORNING": "GLW", "IDEXX": "IDXX", "APPLIED MATLS": "AMAT",
    "APPLIED MATERIALS": "AMAT", "SIRIUSXM": "SIRI", "SIRIUS XM": "SIRI", "VERISIGN": "VRSN",
    "RESTAURANT BRANDS": "QSR", "WATERS": "WAT", "AIR PRODUCTS": "APD", "ALLY FINL": "ALLY",
    "ALLY FINANCIAL": "ALLY", "CANADIAN NATL RY": "CNI", "CANADIAN NATIONAL RAILWAY": "CNI",
    "NEW YORK TIMES": "NYT", "LENNOX": "LII", "QUALCOMM": "QCOM", "MARTIN MARIETTA": "MLM",
    "TEXAS INSTRS": "TXN", "TEXAS INSTRUMENTS": "TXN", "VULCAN MATLS": "VMC", "VULCAN MATERIALS": "VMC",
    "UNION PAC": "UNP", "UNION PACIFIC": "UNP", "MID AMER APT": "MAA", "TAKE TWO INTERACTIVE": "TTWO",
    "CORE SCIENTIFIC": "CORZ", "ADAPTIVE BIOTECHNOLOGIES": "ADPT", "ALPHABET": "GOOGL",
    "BERKSHIRE HATHAWAY": "BRK.B", "META PLATFORMS": "META", "AMAZON": "AMZN", "MICROSOFT": "MSFT",
    "APPLE": "AAPL", "NVIDIA": "NVDA", "BROADCOM": "AVGO", "NETFLIX": "NFLX", "VISA": "V",
    "MASTERCARD": "MA", "S P GLOBAL": "SPGI", "MOODYS": "MCO", "AMERICAN EXPRESS": "AXP",
    "UBER TECHNOLOGIES": "UBER", "BROOKFIELD": "BN", "ADVANCED MICRO DEVICES": "AMD",
    "ARM HOLDINGS": "ARM", "ARM": "ARM", "LAM RESEARCH": "LRCX", "INTEL": "INTC", "MICRON TECHNOLOGY": "MU",
    "ASML": "ASML", "MERCADOLIBRE": "MELI", "COSTCO": "COST", "WALMART": "WMT", "CHEVRON": "CVX",
    "PROLOGIS": "PLD", "HONEYWELL": "HON", "PROGRESSIVE": "PGR", "ELI LILLY": "LLY", "LILLY ELI": "LLY",
    "DEERE": "DE", "ROPER": "ROP", "FAIR ISAAC": "FICO", "OREILLY": "ORLY", "FERRARI": "RACE",
    "HOWARD HUGHES": "HHH", "LOAR": "LOAR", "TEXAS PACIFIC LAND": "TPL", "WALT DISNEY": "DIS",
    "DISNEY WALT": "DIS", "TRANSDIGM": "TDG", "CAPITAL ONE": "COF", "CARVANA": "CVNA",
    "DOORDASH": "DASH", "ROBLOX": "RBLX", "MONGODB": "MDB", "APPLOVIN": "APP", "ALIBABA": "BABA",
    "TESLA": "TSLA", "JPMORGAN": "JPM", "WELLS FARGO": "WFC", "GOLDMAN SACHS": "GS",
    "MORGAN STANLEY": "MS", "CITIGROUP": "C", "BLACKROCK": "BLK", "STATE STREET": "STT",
    "INVESCO LTD": "IVZ", "SEAGATE TECHNOLOGY": "STX", "NEBIUS": "NBIS", "PALO ALTO NETWORKS": "PANW",
    "CEREBRAS": "CBRS", "SNOWFLAKE": "SNOW", "QUANTINUUM": "QNT", "LEMONADE": "LMND", "BLOCK": "XYZ",
    "UNITEDHEALTH": "UNH", "PDD": "PDD", "SALESFORCE": "CRM", "ORACLE": "ORCL", "SERVICENOW": "NOW",
    "PALANTIR": "PLTR", "SHOPIFY": "SHOP", "SPOTIFY": "SPOT", "AIRBNB": "ABNB", "BOOKING": "BKNG",
    "CROWDSTRIKE": "CRWD", "DATADOG": "DDOG", "ARISTA": "ANET", "MARVELL": "MRVL", "KLA": "KLAC",
    "COINBASE": "COIN", "ROBINHOOD": "HOOD", "CANADIAN PACIFIC": "CP", "CONSTELLATION SOFTWARE": "CSU",
    "EQUIPMENTSHARE": "EQS", "HERTZ GLOBAL": "HTZ", "SUNBELT RENTALS": "SUNB", "RINGCENTRAL": "RNG",
    "CME": "CME", "CARNIVAL": "CCL", "VANECK SEMICONDUCTOR": "SMH", "VANECK VECTORS SEMICONDUCTOR": "SMH", "VANECK URANIUM": "NLR", "VANECK URANIUM NUCLEAR": "NLR", "COMPASS DIVERSIFIED": "CODI", "DIGITAL RLTY": "DLR", "DIGITAL REALTY": "DLR", "TJX": "TJX", "DICKS SPORTING": "DKS", "GALLAGHER ARTHUR": "AJG", "FIRST CTZNS BANCSHARES": "FCNCA", "CRH": "CRH", "TELEPHONE DATA SYS": "TDS", "DANAHER": "DHR", "CIPHER MINING": "CIFR", "NATERA": "NTRA",
}
ETF_WORDS = ("ETF", "SPDR", "ISHARES", "VANGUARD", "INVESCO QQQ", "INDEX FD", "TRUST SHS", "ISHARES TR",
             "INVESCO EXCHANGE", "SELECT SECTOR", "PROSHARES", "DIREXION", "ARK ", "TRUST UNIT", "ETN")

def norm(s: str) -> str:
    s = re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())
    s = re.sub(STOP, " ", s)
    return re.sub(r"\s+", " ", s).strip()

def expand(n: str) -> str:
    return re.sub(r"\s+", " ", " ".join(ABBR.get(w, w) for w in n.split())).strip()

def is_fund(name: str) -> bool:
    u = (name or "").upper()
    return any(re.search(r"(^|\W)" + re.escape(w.strip()) + r"(\W|$)", u) for w in ETF_WORDS)

def main() -> None:
    raw = json.load(open(RAW))
    directory = json.load(open(DIR))["symbols"]
    tmap = json.load(open(TMAP)) if TMAP.exists() else {}
    name2t: dict[str, str] = {}
    for s in directory:
        n = norm(s["n"])
        if n and n not in name2t:
            name2t[n] = s["t"]
    name2t_exp = {expand(k): v for k, v in name2t.items()}

    seeds: dict[str, str] = {}
    for k, v in (tmap.items() if isinstance(tmap, dict) else []):
        t = v if isinstance(v, str) else (v or {}).get("ticker")
        if t: seeds[k] = t
    for inv in raw["investors"]:
        for f in inv["filings"]:
            for h in f["holdings"]:
                t = h.get("ticker") or ""
                if t and not t.startswith("CUSIP:") and h.get("cusip"):
                    seeds.setdefault(h["cusip"], t)

    names_by_cusip: dict[str, list[str]] = collections.defaultdict(list)
    for inv in raw["investors"]:
        for f in inv["filings"]:
            for h in f["holdings"]:
                c, nm = h.get("cusip"), h.get("company") or ""
                if c and nm and nm not in names_by_cusip[c]: names_by_cusip[c].append(nm)

    def resolve_one(name: str) -> tuple[str, str]:
        n = norm(name)
        for k, v in ALIAS.items():
            if n == k or n.startswith(k + " "): return v, "alias"
        if n in name2t: return name2t[n], "name-exact"
        e = expand(n)
        if e in name2t_exp: return name2t_exp[e], "name-expand"
        return "", "unresolved"

    def resolve(cusip: str, name: str) -> tuple[str, str]:
        if cusip in seeds: return seeds[cusip], "cusip-seed"
        best = ("", "unresolved")
        for nm in ([name] + [x for x in names_by_cusip.get(cusip, []) if x != name]):
            t, m = resolve_one(nm)
            if t: return t, ("fund" if is_fund(nm) else m)
        return ("", "fund") if any(is_fund(x) for x in names_by_cusip.get(cusip, [name])) else best

    latest = max(f["quarter"] for inv in raw["investors"] for f in inv["filings"])
    cmap: dict[str, dict] = {}
    unresolved: collections.Counter = collections.Counter()
    unresolved_name: dict[str, str] = {}
    holders: dict[str, dict] = collections.defaultdict(lambda: {"holders": [], "value_usd": 0.0, "company": ""})
    by_method = collections.Counter(); by_val = collections.Counter(); total_val = 0.0
    for inv in raw["investors"]:
        for f in inv["filings"]:
            for h in f["holdings"]:
                c = h.get("cusip"); nm = h.get("company") or ""
                if not c: continue
                if c not in cmap:
                    t, m = resolve(c, nm)
                    cmap[c] = {"ticker": t, "name": nm, "method": m}
                if f["quarter"] == latest:
                    v = float(h.get("market_value") or 0)
                    total_val += v; by_method[cmap[c]["method"]] += 1; by_val[cmap[c]["method"]] += v
                    t = cmap[c]["ticker"]
                    if t:
                        d = holders[t]
                        if inv["name"] not in d["holders"]: d["holders"].append(inv["name"])
                        d["value_usd"] += v; d["company"] = d["company"] or nm
                    elif cmap[c]["method"] == "unresolved":
                        unresolved[c] += v; unresolved_name[c] = nm

    OUT_MAP.write_text(json.dumps({
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "offline bootstrap (scripts/build_cusip_map.py) — replace/extend with OpenFIGI pass",
        "resolved": sum(1 for v in cmap.values() if v["ticker"]),
        "total": len(cmap),
        "map": {c: v for c, v in cmap.items() if v["ticker"]},
        "unresolved": [{"cusip": c, "name": unresolved_name[c], "latest_value_usd": round(v)}
                        for c, v in unresolved.most_common()],
    }, indent=1))
    elig_rows = sorted(({"ticker": t, "company": d["company"], "holders": sorted(d["holders"]),
                         "holder_count": len(d["holders"]), "value_usd": round(d["value_usd"])}
                        for t, d in holders.items()), key=lambda r: (-r["holder_count"], -r["value_usd"]))
    OUT_ELIG.write_text(json.dumps({
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "quarter": latest,
        "investors": sorted({i["name"] for i in raw["investors"]}),
        "rule": "eligible = held by >=1 tracked 13F filer in the latest quarter",
        "tickers": elig_rows,
    }, indent=1))
    print(f"quarter {latest}: {len(cmap)} CUSIPs, {sum(1 for v in cmap.values() if v['ticker'])} resolved; eligible tickers {len(elig_rows)}")
    for m in by_method:
        print(f"  {m:12} rows {by_method[m]:5}  value {by_val[m]/total_val*100:5.1f}%")
    print("top unresolved:", [(unresolved_name[c], round(v/total_val*100, 2)) for c, v in unresolved.most_common(8)])

if __name__ == "__main__":
    main()
