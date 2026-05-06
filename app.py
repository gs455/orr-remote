from flask import Flask, render_template_string, send_file, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from playwright.sync_api import sync_playwright
import csv, os, io
from datetime import datetime

app = Flask(__name__)
DATA_DIR = "/data/militia_holdings"
os.makedirs(DATA_DIR, exist_ok=True)

def scrape():
    print(f"[{datetime.now()}] Starting scrape...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        page.goto("https://www.militiaetf.com", timeout=30000)
        page.wait_for_selector("table", timeout=15000)

        tables = page.query_selector_all("table")
        target_table = None
        for table in tables:
            heading_text = page.evaluate("""el => {
                let node = el;
                while (node) {
                    if (node.previousElementSibling &&
                        node.previousElementSibling.textContent.includes('Fund Holdings')) {
                        return 'found';
                    }
                    node = node.parentElement;
                }
                return null;
            }""", table)
            if heading_text:
                target_table = table
                break

        if not target_table:
            target_table = tables[-1]

        headers = [th.inner_text().strip() for th in target_table.query_selector_all("thead th")]
        if not headers:
            headers = [td.inner_text().strip() for td in target_table.query_selector_all("tr:first-child td")]

        rows = []
        for tr in target_table.query_selector_all("tbody tr"):
            row = [td.inner_text().strip() for td in tr.query_selector_all("td")]
            if row:
                rows.append(row)

        browser.close()

    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = os.path.join(DATA_DIR, f"militia_holdings_{date_str}.csv")
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if headers:
            writer.writerow(headers)
        writer.writerows(rows)

    print(f"[{datetime.now()}] Saved {len(rows)} rows → {filepath}")
    return filepath, headers, rows

# Schedule daily at 6pm UTC
scheduler = BackgroundScheduler()
scheduler.add_job(scrape, "cron", hour=18, minute=0)
scheduler.start()

HTML = """
<!DOCTYPE html><html><head><title>Militia ETF Holdings</title>
<style>
  body { font-family: monospace; background: #0d0d0d; color: #c8ff00; padding: 2rem; }
  h1 { font-size: 1.4rem; margin-bottom: 1rem; }
  table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
  th { background: #1a1a1a; color: #c8ff00; padding: 8px 12px; text-align: left; border-bottom: 1px solid #333; }
  td { padding: 6px 12px; border-bottom: 1px solid #1e1e1e; color: #ddd; }
  tr:hover td { background: #141414; }
  .btn { background: #c8ff00; color: #000; border: none; padding: 8px 16px;
         font-family: monospace; font-size: 0.9rem; cursor: pointer; margin-right: 8px; }
  .btn:hover { background: #aadd00; }
  .meta { font-size: 0.75rem; color: #666; margin-bottom: 1.5rem; }
  .files { margin-top: 2rem; font-size: 0.8rem; }
  .files a { color: #c8ff00; display: block; margin: 4px 0; }
</style></head><body>
<h1>⚡ MILITIA ETF — FUND HOLDINGS</h1>
<div class="meta">Last scraped: {{ last_scraped }} &nbsp;|&nbsp; {{ row_count }} holdings</div>
<button class="btn" onclick="runScrape()">↻ Scrape Now</button>
<a href="/download/latest"><button class="btn">↓ Download Latest CSV</button></a>
<br><br>
{% if headers %}
<table><thead><tr>{% for h in headers %}<th>{{ h }}</th>{% endfor %}</tr></thead>
<tbody>{% for row in rows %}<tr>{% for cell in row %}<td>{{ cell }}</td>{% endfor %}</tr>{% endfor %}</tbody>
</table>
{% else %}<p>No data yet. Click "Scrape Now" to fetch holdings.</p>{% endif %}
<div class="files"><strong>Archive:</strong><br>
{% for f in files %}<a href="/download/{{ f }}">{{ f }}</a>{% endfor %}</div>
<script>
function runScrape() {
  document.querySelector('.meta').textContent = 'Scraping...';
  fetch('/run').then(r => r.json()).then(d => location.reload());
}
</script></body></html>
"""

def get_latest():
    files = sorted(os.listdir(DATA_DIR)) if os.path.exists(DATA_DIR) else []
    csvs = [f for f in files if f.endswith(".csv")]
    if not csvs:
        return None, [], [], []
    latest = os.path.join(DATA_DIR, csvs[-1])
    with open(latest, newline="", encoding="utf-8") as f:
        reader = list(csv.reader(f))
    headers = reader[0] if reader else []
    rows = reader[1:] if len(reader) > 1 else []
    return csvs[-1], headers, rows, csvs

@app.route("/")
def index():
    name, headers, rows, files = get_latest()
    last_scraped = name.replace("militia_holdings_", "").replace(".csv", "") if name else "Never"
    return render_template_string(HTML, headers=headers, rows=rows,
                                  last_scraped=last_scraped, row_count=len(rows), files=files)

@app.route("/run")
def run_now():
    try:
        filepath, headers, rows = scrape()
        return jsonify({"status": "ok", "rows": len(rows), "file": filepath})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/download/latest")
def download_latest():
    name, _, _, _ = get_latest()
    if not name:
        return "No files yet", 404
    return send_file(os.path.join(DATA_DIR, name), as_attachment=True)

@app.route("/download/<filename>")
def download_file(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return "Not found", 404
    return send_file(path, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))