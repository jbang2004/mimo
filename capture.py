"""Capture the public MiMo RL dashboard without login or private credentials.
Only source-capture.json is written. This script does not infer training metrics
or modify editorial conclusions. Historical captures remain in Git history.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from playwright.sync_api import sync_playwright

SOURCE = "https://mimo.xiaomi.com/rl/"
OUT = Path("source-capture.json")
MAX_RESPONSE_BYTES = 1_500_000
MAX_TOTAL_BYTES = 4_000_000

def main() -> None:
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": SOURCE,
        "capture_ok": False,
        "note": "Public browser capture; source material, not verified analysis.",
        "http_status": None,
        "visible_text": "",
        "public_json_responses": [],
        "errors": [],
    }
    used = 0
    seen: set[str] = set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="en-US")
            page = context.new_page()
            def capture_response(response) -> None:
                nonlocal used
                try:
                    u = urlsplit(response.url)
                    path = u.path.lower()
                    if u.hostname != "mimo.xiaomi.com" or response.request.method != "GET":
                        return
                    if any(x in path for x in ("auth", "login", "account", "secret", "session")):
                        return
                    if not any(x in path for x in ("/rl", "metric", "overview", "series", "training", "benchmark")):
                        return
                    if response.status != 200 or "json" not in response.headers.get("content-type", ""):
                        return
                    url = urlunsplit((u.scheme, u.netloc, u.path, "", ""))
                    if url in seen or len(seen) >= 12:
                        return
                    body = response.body()
                    if len(body) > MAX_RESPONSE_BYTES or used + len(body) > MAX_TOTAL_BYTES:
                        return
                    payload = json.loads(body)
                    result["public_json_responses"].append({"url": url, "data": payload})
                    used += len(body)
                    seen.add(url)
                except Exception:
                    # A response may be detached or not actually contain valid JSON.
                    return
            page.on("response", capture_response)
            response = page.goto(SOURCE, wait_until="domcontentloaded", timeout=90000)
            result["http_status"] = response.status if response else None
            # Live dashboards may never become network-idle. Allow bounded hydration.
            for _ in range(10):
                page.wait_for_timeout(2500)
                text = page.locator("body").inner_text(timeout=10000)
                if len(text) > 1000 and re.search(r"step\s*[:#]?\s*\d+", text, re.I):
                    page.wait_for_timeout(2500)
                    break
            text = page.locator("body").inner_text(timeout=10000)
            result["visible_text"] = text[:160000]
            result["visible_text_truncated"] = len(text) > 160000
            result["capture_ok"] = result["http_status"] == 200 and (
                len(text) > 600 or bool(result["public_json_responses"])
            )
            result["page_title"] = page.title()
            if not result["capture_ok"]:
                result["errors"].append("No substantial dashboard content captured; do not infer training failure.")
            browser.close()
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {str(exc)[:500]}")
    result["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    temporary = OUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUT)
    print(json.dumps({"capture_ok": result["capture_ok"], "http_status": result["http_status"],
                      "text_length": len(result["visible_text"]),
                      "json_responses": len(result["public_json_responses"]), "errors": result["errors"]},
                     ensure_ascii=False))

if __name__ == "__main__":
    main()
