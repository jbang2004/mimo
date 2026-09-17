"""Capture only public dashboard evidence, never inferred training conclusions.
No login, API key, or private account data is used. Git history retains captures.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from playwright.sync_api import sync_playwright

SOURCE = "https://mimo.xiaomi.com/rl/"
OUT = Path("source-capture.json")
MAX_RESPONSE_BYTES = 1_500_000
MAX_TOTAL_BYTES = 4_000_000

def main() -> None:
    result = {"captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "source_url": SOURCE, "capture_ok": False,
              "note": "Public browser capture; source material, not verified analysis.",
              "http_status": None, "summary": {}, "visible_text": "",
              "public_json_responses": [], "errors": []}
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
                    # Keep model/tag selectors; discard cache busters and credential-like parameters.
                    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
                             if k.lower() not in {"_", "t", "ts", "_ts", "nocache"}
                             and not any(x in k.lower() for x in ("token", "secret", "auth", "cookie", "session", "password"))]
                    url = urlunsplit((u.scheme, u.netloc, u.path, urlencode(query), ""))
                    if url in seen or len(seen) >= 24:
                        return
                    seen.add(url)
                    body = response.body()
                    if len(body) > MAX_RESPONSE_BYTES or used + len(body) > MAX_TOTAL_BYTES:
                        return
                    payload = json.loads(body)
                    result["public_json_responses"].append({"url": url, "data": payload})
                    used += len(body)
                except Exception:
                    return
            page.on("response", capture_response)
            response = page.goto(SOURCE, wait_until="domcontentloaded", timeout=90000)
            result["http_status"] = response.status if response else None
            for _ in range(10):
                page.wait_for_timeout(2500)
                text = page.locator("body").inner_text(timeout=10000)
                if len(text) > 1000 and re.search(r"step\s*[:#]?\s*\d+", text, re.I):
                    page.wait_for_timeout(5000)
                    break
            text = page.locator("body").inner_text(timeout=10000)
            result["visible_text"] = text[:160000]
            result["visible_text_truncated"] = len(text) > 160000
            result["capture_ok"] = result["http_status"] == 200 and (len(text) > 600 or bool(result["public_json_responses"]))
            result["page_title"] = page.title()
            if not result["capture_ok"]:
                result["errors"].append("No substantial dashboard content; do not infer training failure.")
            try:
                probe = context.new_page()
                pr = probe.goto("https://mimo.waveshift.net/", wait_until="domcontentloaded", timeout=30000)
                probe.wait_for_timeout(2000)
                result["site_check"] = {"http_status": pr.status if pr else None, "title": probe.title(),
                    "headline": probe.locator("#headline").inner_text(timeout=10000),
                    "status": probe.locator("#status-label").inner_text(timeout=3000) if probe.locator("#status-label").count() else "legacy page"}
            except Exception as exc:
                result["site_check"] = {"error": str(exc)[:250]}
            browser.close()
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {str(exc)[:500]}")
    summary = {"runs": {}, "series": {}, "benchmarks": [], "notices": [], "descriptions": {}}
    for response in result["public_json_responses"]:
        body = response["data"]
        path = urlsplit(response["url"]).path
        if not isinstance(body, dict):
            continue
        if path.endswith("/status") and isinstance(body.get("run"), dict):
            key = body["run"].get("key")
            summary["runs"][key] = {k: body.get(k) for k in ("run", "clock", "version", "step", "totals", "headline", "cost", "events")}
        elif path.endswith("/series") and isinstance(body.get("run"), str):
            key = body["run"]
            previous = summary["series"].get(key)
            if previous and previous.get("steps") == body.get("steps"):
                previous["series"].update(body.get("series", {}))
            else:
                summary["series"][key] = body
        elif path.endswith("/benchmarks"):
            summary["benchmarks"] = body.get("benchmarks", [])
        elif path.endswith("/notices"):
            summary["notices"] = body.get("notices", [])
        elif path.endswith("/runs"):
            summary["descriptions"] = body.get("descriptions", {})
    result["summary"] = summary
    result["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    temporary = OUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUT)
    print(json.dumps({"capture_ok": result["capture_ok"], "http_status": result["http_status"],
                      "text_length": len(result["visible_text"]), "runs": list(summary["runs"]),
                      "series": list(summary["series"]), "site_check": result.get("site_check"),
                      "errors": result["errors"]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
