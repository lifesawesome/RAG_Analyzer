import argparse
from datetime import timedelta
import json
from pathlib import Path

import httpx
from databricks.sdk.retries import retried
from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--allow-live", action="store_true", help="Explicitly authorize real cloud calls during the browser check.")
    args = parser.parse_args()

    @retried(on=[httpx.ConnectError], timeout=timedelta(seconds=45))
    def server_status():
        response = httpx.get(f"{args.url}/api/status", timeout=60)
        response.raise_for_status()
        return response.json()

    status = server_status()
    live = status["mode"] != "offline"
    if live and not args.allow_live:
        raise RuntimeError("The browser rehearsal must not make unapproved paid cloud requests.")
    if live and status["mode"] != "foundry":
        raise RuntimeError("Live browser validation requires the full Foundry mode.")
    prefix = "live-" if live else ""
    output = Path(__file__).resolve().parents[1] / "artifacts"
    output.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        for label, viewport in [("desktop", {"width": 1440, "height": 1100}), ("mobile", {"width": 390, "height": 844})]:
            page = browser.new_page(viewport=viewport)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(args.url, wait_until="networkidle")
            expect(page.locator("#mode")).to_contain_text("LIVE" if live else "OFFLINE REHEARSAL")
            page.get_by_role("button", name="Lending approvals", exact=True).click()
            page.locator("#as-of").fill("2026-11-09")
            page.locator("#submit").click()
            expect(page.locator("#answer-meta")).to_contain_text("FOUNDRY" if live else "OFFLINE", timeout=120000)
            if live:
                expect(page.locator("#mode")).to_have_text("LIVE VERIFIED")
            expect(page.locator(".evidence-item")).to_have_count(6)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Horizontal layout overflow"
            page.screenshot(path=str(output / f"{prefix}{label}.png"), full_page=True)
            page.locator(".evidence-item .text-button").first.click()
            expect(page.locator("#source-dialog")).to_be_visible()
            expect(page.locator("#source-image")).to_be_visible()
            page.wait_for_function("document.getElementById('source-image').naturalWidth > 100")
            source_url = page.locator("#source-download").get_attribute("href")
            document = httpx.get(args.url + source_url.split("#")[0], timeout=30)
            assert document.status_code == 200 and document.content.startswith(b"%PDF")
            if label == "desktop":
                page.screenshot(path=str(output / f"{prefix}source-pdf.png"))
            page.locator("#close-source").click()
            page.locator("#trace-shortcut").click()
            expect(page.locator("#trace-events")).to_contain_text("Databricks hybrid search" if live else "Local BM25 search")
            if live:
                expect(page.locator("#trace-events")).to_contain_text("Foundry Agent Service")
            expect(page.locator("#raw-response")).to_contain_text("compliance-analysts")
            if label == "desktop":
                page.screenshot(path=str(output / f"{prefix}execution-trace.png"), full_page=True)
                with page.expect_download() as downloaded:
                    page.locator("#download-receipt").click()
                downloaded.value.save_as(output / f"{prefix}downloaded-receipt.json")
            page.locator('[data-view="corpus"]').click()
            assert page.locator("#corpus-table tr").count() > 0
            assert not errors, errors
            page.close()
            print(f"PASS {label}: question, evidence, PDF, trace, corpus and overflow checks")
        browser.close()
    receipt = httpx.post(f"{args.url}/api/ask", json={"query": "What approvals apply to elevated-risk commercial lending?", "as_of": "2026-11-09"}, timeout=60).json()
    (output / f"{prefix}browser-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"Screenshots and {'actual live' if live else 'offline rehearsal'} receipt: {output}")


if __name__ == "__main__":
    main()
