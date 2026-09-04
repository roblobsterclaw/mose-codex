#!/usr/bin/env python3
"""
MOSE Buy Zone — Daily Email Report
Shows ALL stocks from ALL buckets (except AI bench), sorted cheapest to most
expensive by 52-week range position. Buy zone names (within threshold) are
highlighted. Emailed as HTML with one-page PDF attachment.

Usage:
  /usr/bin/python3 /Users/joemac/Documents/mose/scripts/daily_buyzone_email.py

Schedule: Mon-Fri 9:40 AM ET via cron

Author: Hermes Agent for Joe Lynch
"""
import json, os, sys, subprocess, tempfile, base64, datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# --- Config ---
REPO_PATH = "/Users/joemac/Documents/mose"
REPO_URL = "https://github.com/roblobsterclaw/mose-codex.git"
DATA_FILE = "live-quotes.json"
RECIPIENT = "rob.lobster.claw@gmail.com"
GMAIL_TOKEN = "/Users/joemac/.openclaw/workspace/config/gmail/token.json"
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# --- Buckets: name -> (threshold, [tickers]) ---
# AI bench and Dry powder EXCLUDED per Joe's request
BUCKETS = [
    ("Forever compounders", 50, ["GOOGL", "AMZN", "BRK.B", "AAPL", "MSFT", "META", "COST", "MELI", "CSU", "WMT"]),
    ("Toll booths",         45, ["V", "MA", "AXP", "MCO", "SPGI", "PGR"]),
    ("Hard assets",         40, ["BN", "PLD", "CP", "CVX", "OXY", "GE", "HON", "NLR", "SOLS"]),
    ("AI core",             30, ["AVGO", "LRCX", "TSM", "ASML", "NVDA", "SMH"]),
    ("Radar",               35, ["LLY", "DE", "ROP", "FICO", "VRSN", "ORLY", "TXN", "RACE"]),
    ("Opportunistic",       25, ["UBER", "APP", "MDB", "DASH", "RBLX", "FROG", "KVYO", "BABA", "CVNA", "TSLA", "SPCX", "CODI", "MBGL", "BE", "HHH"]),
]

def git_pull():
    """Pull latest MOSE repo data."""
    if not os.path.exists(REPO_PATH):
        os.makedirs(os.path.dirname(REPO_PATH), exist_ok=True)
        subprocess.run(["git", "clone", REPO_URL, REPO_PATH], capture_output=True, timeout=30)
    result = subprocess.run(["git", "-C", REPO_PATH, "pull"], capture_output=True, timeout=30)
    return result.returncode == 0

def load_quotes():
    """Load live-quotes.json from the repo."""
    path = os.path.join(REPO_PATH, DATA_FILE)
    with open(path) as f:
        return json.load(f)

def compute_all(data):
    """Compute 52-wk range for ALL tickers across all included buckets.
    Returns (all_items sorted by range_pos asc, skipped_list, buyzone_count)."""
    quotes = {q["ticker"]: q for q in data.get("quotes", [])}
    all_items = []
    skipped = []
    buyzone_count = 0

    for bucket_name, threshold, tickers in BUCKETS:
        for ticker in tickers:
            q = quotes.get(ticker)
            if not q:
                skipped.append((ticker, bucket_name, "no quote in data"))
                continue

            price = q.get("price")
            hi = q.get("week52_high")
            lo = q.get("week52_low")

            if not price or not hi or not lo or hi == lo:
                skipped.append((ticker, bucket_name, "missing/zero 52-wk data"))
                continue

            range_pos = (price - lo) / (hi - lo) * 100
            in_zone = range_pos <= threshold

            if in_zone:
                buyzone_count += 1

            all_items.append({
                "ticker": ticker,
                "bucket": bucket_name,
                "range_pos": range_pos,
                "price": price,
                "week52_high": hi,
                "week52_low": lo,
                "threshold": threshold,
                "in_zone": in_zone,
            })

    # Sort ascending by range_pos (cheapest first)
    all_items.sort(key=lambda x: x["range_pos"])
    return all_items, skipped, buyzone_count

def fmt_price(p):
    """Format price: whole dollars over $100, cents under $100."""
    if p >= 100:
        return f"${p:,.0f}"
    else:
        return f"${p:,.2f}"

def build_html(all_items, skipped, buyzone_count, generated_at, date_str):
    """Build the HTML email body — all stocks, buy zone ones highlighted."""
    total = len(all_items)

    # Color bar for range_pos
    def bar_html(rp):
        if rp <= 25:
            color = "#CC0000"
        elif rp <= 40:
            color = "#CC6600"
        elif rp <= 60:
            color = "#CCCC00"
        else:
            color = "#006600"
        width = max(2, rp)
        return f'<div style="display:inline-block;width:60px;height:12px;background:#e0e0e0;border-radius:3px;vertical-align:middle;"><div style="width:{width}%;height:100%;background:{color};border-radius:3px;"></div></div>'

    rows = ""
    # Track ranking among buy zone items only for stars
    zone_rank = 0
    for item in all_items:
        in_zone = item["in_zone"]
        star = ""
        row_style = ""

        if in_zone:
            zone_rank += 1
            if zone_rank <= 3:
                star = " ⭐"
                row_style = "background:#FFF3CD;"  # light gold highlight
            else:
                row_style = "background:#F0F7FF;"  # light blue for in-zone

        zone_badge = '<span style="color:#CC0000;font-weight:bold;font-size:8pt;">IN ZONE</span>' if in_zone else '<span style="color:#999;font-size:8pt;">—</span>'

        rows += f"""
        <tr style="{row_style}">
            <td style="text-align:center;padding:4px 6px;">{zone_rank if in_zone else ''}{star if in_zone else ''}</td>
            <td style="font-weight:bold;padding:4px 6px;">{item['ticker']}</td>
            <td style="padding:4px 6px;">{item['bucket']}</td>
            <td style="padding:4px 6px;">{zone_badge}</td>
            <td style="padding:4px 6px;">{bar_html(item['range_pos'])} {item['range_pos']:.1f}%</td>
            <td style="text-align:right;padding:4px 6px;">{fmt_price(item['price'])}</td>
            <td style="text-align:right;font-size:9pt;color:#666;padding:4px 6px;">{fmt_price(item['week52_low'])} – {fmt_price(item['week52_high'])}</td>
        </tr>"""

    skipped_html = ""
    if skipped:
        skip_items = ", ".join(f"{t} ({b}: {r})" for t, b, r in skipped)
        skipped_html = f"<p style='font-size:9pt;color:#999;'><b>Skipped (no data):</b> {skip_items}</p>"

    # Parse generated_at for display
    try:
        gen_dt = datetime.datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        gen_display = gen_dt.strftime("%b %d, %Y %H:%M UTC")
    except:
        gen_display = generated_at

    html = f"""\
<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, 'Segoe UI', Arial, sans-serif; font-size: 11pt; color: #1a1a1a; max-width: 750px; margin: 0 auto;">

<h1 style="color:#002B5C; border-bottom: 3px solid #C59E3C; padding-bottom: 5px; margin-bottom: 5px;">MOSE — Buy Zone</h1>
<p style="color:#666; font-size:10pt; margin-top:0;">As of {gen_display} &nbsp;|&nbsp; {buyzone_count} of {total} names in buy zone</p>

<p style="font-size:9pt; color:#666; background:#f5f5f5; padding:6px 10px; border-radius:4px;">
<b>52-wk Range:</b> 0% = at the 52-week low, 100% = at the high; lower = cheaper.
<span style="color:#C59E3C;">⭐</span> = 3 cheapest in zone.
<span style="color:#CC0000;font-weight:bold;">IN ZONE</span> = within bucket threshold.
</p>

<table style="width:100%; border-collapse:collapse; font-size:10pt; margin-top:10px;">
    <thead>
    <tr style="background:#002B5C; color:#fff;">
        <th style="padding:6px 6px; text-align:center;">Zone#</th>
        <th style="padding:6px 6px; text-align:left;">Ticker</th>
        <th style="padding:6px 6px; text-align:left;">Bucket</th>
        <th style="padding:6px 6px; text-align:center;">Status</th>
        <th style="padding:6px 6px; text-align:left;">52-wk Range %</th>
        <th style="padding:6px 6px; text-align:right;">Price</th>
        <th style="padding:6px 6px; text-align:right;">52-wk Low-High</th>
    </tr>
    </thead>
    <tbody>
    {rows}
    </tbody>
</table>

{skipped_html}

<p style="margin-top:20px; font-size:9pt; color:#999; border-top:1px solid #e0e0e0; padding-top:8px;">
Not financial advice — my plan.
</p>

</body></html>
"""
    return html

def generate_pdf(html_content, output_path):
    """Generate PDF from HTML using headless Chrome."""
    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
        f.write(html_content)
        html_path = f.name

    try:
        subprocess.run([
            CHROME_PATH,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--print-to-pdf=" + output_path,
            "--print-to-pdf-no-header",
            "file://" + html_path
        ], capture_output=True, timeout=30)
    finally:
        os.unlink(html_path)

    return os.path.exists(output_path)

def send_email(html_body, pdf_path, date_str, buyzone_count, total_count):
    """Send email via Gmail API."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    subject = f"MOSE Buy Zone — {date_str} ({buyzone_count} of {total_count} in zone)"

    with open(GMAIL_TOKEN) as f:
        token_data = json.load(f)

    scopes = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.readonly']
    creds = Credentials.from_authorized_user_info(token_data, scopes=scopes)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(GMAIL_TOKEN, 'w') as f:
            json.dump(json.loads(creds.to_json()), f, indent=2)
        print("Token refreshed")

    service = build('gmail', 'v1', credentials=creds)

    msg = MIMEMultipart()
    msg['to'] = RECIPIENT
    msg['subject'] = subject

    msg.attach(MIMEText(html_body, 'html'))

    if os.path.exists(pdf_path):
        with open(pdf_path, 'rb') as f:
            part = MIMEBase('application', 'pdf')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="MOSE_BuyZone_{date_str.replace(" ","_")}.pdf"')
            msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(userId='me', body={'raw': raw}).execute()
    return result['id'], subject

def main():
    print("=== MOSE Buy Zone Report ===")

    # 1. Git pull
    print("Pulling latest MOSE data...")
    git_pull()

    # 2. Load quotes
    data = load_quotes()
    generated_at = data.get("generated_at", "unknown")
    print(f"Data generated: {generated_at}")
    print(f"Quotes loaded: {len(data.get('quotes', []))} tickers")

    # 3. Compute all items
    all_items, skipped, buyzone_count = compute_all(data)
    print(f"Total stocks in report: {len(all_items)}")
    print(f"In buy zone: {buyzone_count}")
    print(f"Skipped (no data): {len(skipped)}")

    # 4. Build HTML
    now = datetime.datetime.now()
    date_str = now.strftime("%b %-d, %Y")
    html = build_html(all_items, skipped, buyzone_count, generated_at, date_str)

    # 5. Generate PDF
    pdf_path = f"/tmp/MOSE_BuyZone_{now.strftime('%Y-%m-%d')}.pdf"
    print("Generating PDF...")
    if generate_pdf(html, pdf_path):
        print(f"PDF saved: {pdf_path}")
    else:
        print("WARNING: PDF generation failed — sending email without attachment")
        pdf_path = ""

    # 6. Send email
    print(f"Sending email to {RECIPIENT}...")
    msg_id, subject = send_email(html, pdf_path, date_str, buyzone_count, len(all_items))
    print(f"\n✅ SENT! Message ID: {msg_id}")
    print(f"To: {RECIPIENT}")
    print(f"Subject: {subject}")
    print(f"Total stocks: {len(all_items)} | In buy zone: {buyzone_count}")

    # Print summary
    print("\n--- Full Ranking (cheapest first) ---")
    zone_rank = 0
    for item in all_items:
        if item["in_zone"]:
            zone_rank += 1
            star = " ⭐" if zone_rank <= 3 else ""
            print(f"  {zone_rank:2d}. {item['ticker']:6s} ({item['bucket']:20s}) {item['range_pos']:5.1f}% {fmt_price(item['price'])} IN ZONE{star}")
        else:
            print(f"   -  {item['ticker']:6s} ({item['bucket']:20s}) {item['range_pos']:5.1f}% {fmt_price(item['price'])}")

if __name__ == "__main__":
    main()
