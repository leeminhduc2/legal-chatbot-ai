"""
Script to crawl legal documents from thuvienphapluat.vn and save as PDF.
Uses Playwright with a visible Chromium browser.
Strategy: Navigate to each page, wait for content to load, then click the "In" (Print) 
button which uses jquery.PrintArea to show a clean printable version of the document,
then capture that as PDF via CDP.
"""

import base64
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

CITATIONS_FILE = Path("data/citations.md")
OUTPUT_DIR = Path("data/raw")
BROWSER_PROFILE = Path("data/.browser_profile")


def extract_info_from_url(url: str) -> dict | None:
    """Extract document number, type, and short name from a thuvienphapluat.vn URL."""
    path = url.split("thuvienphapluat.vn")[-1]
    slug_match = re.search(r"/([^/]+?)(?:\.\w+)?(?:\?.*)?$", path)
    if not slug_match:
        return None
    slug = slug_match.group(1)

    so_hieu_match = re.search(
        r"(?:Nghi-dinh|Thong-tu|Nghi-quyet|Quyet-dinh)-"
        r"(\d+-\d{4}-(?:ND-CP|TT-\w+|QH\d+|QD-\w+|NQ-\w+))",
        slug,
    )
    if not so_hieu_match:
        so_hieu_match = re.search(
            r"(?:Nghi-dinh|Thong-tu|Nghi-quyet|Quyet-dinh)-"
            r"(\d+-(?:QD|ND|TT|NQ)-\w+-\d{4})",
            slug,
        )
    if not so_hieu_match:
        so_hieu_match = re.search(
            r"(?:Nghi-dinh|Thong-tu|Nghi-quyet|Quyet-dinh)-"
            r"(\d+-(?:QD|ND|TT|NQ)-\w+)",
            slug,
        )
    if not so_hieu_match:
        luat_match = re.search(r"^(.+?)-(\d{4})-(\d+)$", slug)
        if luat_match:
            name_part, year, doc_id = luat_match.groups()
            so_hieu = f"{year}-{doc_id}"
            short_name = name_part.lower()
            filename = f"{so_hieu}_{short_name}.pdf"
            return {"so_hieu": so_hieu, "short_name": short_name, "filename": filename, "url": url}
        else:
            print(f"  [WARN] Cannot extract so-hieu from: {slug}")
            return None

    so_hieu = so_hieu_match.group(1)
    desc_start = slug.find(so_hieu) + len(so_hieu)
    desc_part = slug[desc_start:].lstrip("-")
    desc_part = re.sub(r"-\d{5,}$", "", desc_part)
    desc_words = [w.lower() for w in desc_part.split("-") if w]
    short_name = "-".join(desc_words[:6]) if desc_words else "van-ban"
    filename = f"{so_hieu}_{short_name}.pdf"

    return {"so_hieu": so_hieu, "short_name": short_name, "filename": filename, "url": url}


def read_urls(filepath: Path) -> list[str]:
    urls = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("http"):
                urls.append(line)
    return urls


def wait_for_content(page, timeout=120):
    """Wait for Cloudflare challenge to pass and real content to appear."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            content = page.content()
            title = page.title().lower()
            if "security verification" in content.lower() or "just a moment" in title:
                print("    Waiting for Cloudflare challenge...", end="\r")
                time.sleep(3)
                continue
            # Check for the document content div
            if "divContentDoc" in content or "content1" in content:
                if len(content) > 10000:
                    print("    Content loaded successfully.           ")
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def crawl_pdfs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)

    urls = read_urls(CITATIONS_FILE)
    print(f"Found {len(urls)} URLs to process.")

    tasks = []
    for url in urls:
        info = extract_info_from_url(url)
        if info:
            tasks.append(info)
            existing = (OUTPUT_DIR / info["filename"]).exists()
            status = "SKIP (exists)" if existing else "WILL DOWNLOAD"
            print(f"  [{status}] {info['filename']}")
        else:
            print(f"  [ERROR] Could not parse: {url}")

    to_download = [t for t in tasks if not (OUTPUT_DIR / t["filename"]).exists()]
    print(f"\n{len(to_download)} files to download, {len(tasks) - len(to_download)} already exist.")

    if not to_download:
        print("Nothing to download. All files already exist.")
        return

    print("\n[INFO] A browser window will open.")
    print("       If Cloudflare shows a CAPTCHA, please solve it manually.")
    print("       The script will detect when it passes and continue.\n")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE.absolute()),
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )

        # Get or create the page
        if context.pages:
            page = context.pages[0]
        else:
            page = context.new_page()

        # Remove webdriver detection
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        for i, task in enumerate(to_download, 1):
            url = task["url"]
            filename = task["filename"]
            output_path = OUTPUT_DIR / filename

            print(f"[{i}/{len(to_download)}] Downloading: {filename}")
            print(f"  URL: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                if not wait_for_content(page, timeout=120):
                    print("  [FAIL] Content did not load within timeout")
                    continue

                # Wait for full rendering
                page.wait_for_timeout(5000)

                # First, click "Noi dung" tab to ensure content is loaded
                try:
                    page.click("#aNoiDungVB", timeout=5000)
                    page.wait_for_timeout(3000)
                except Exception:
                    pass

                # Extract #divContentDoc HTML and create a standalone printable page
                content_html = page.evaluate("""
                    () => {
                        const el = document.querySelector('#divContentDoc');
                        if (el) return el.innerHTML;
                        // Fallback to content1
                        const el2 = document.querySelector('.content1');
                        if (el2) return el2.innerHTML;
                        return null;
                    }
                """)

                if not content_html or len(content_html) < 500:
                    print(f"  [FAIL] Content too short ({len(content_html) if content_html else 0} chars)")
                    continue

                # Get the document title
                doc_title = page.evaluate("""
                    () => {
                        const el = document.querySelector('.doc-title, h1, .tenvb');
                        if (el) return el.innerText;
                        return document.title;
                    }
                """)

                # Create a clean printable page
                print_html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <title>{doc_title}</title>
                    <style>
                        body {{
                            font-family: 'Times New Roman', Times, serif;
                            font-size: 14px;
                            line-height: 1.6;
                            padding: 20px;
                            max-width: 100%;
                        }}
                        table {{
                            border-collapse: collapse;
                            width: 100%;
                        }}
                        td, th {{
                            border: 1px solid #ccc;
                            padding: 5px;
                        }}
                        a {{
                            text-decoration: none;
                            color: black;
                        }}
                        img {{
                            max-width: 100%;
                        }}
                    </style>
                </head>
                <body>
                    {content_html}
                </body>
                </html>
                """

                # Navigate to the printable content as a data URL
                page.set_content(print_html)
                page.wait_for_timeout(2000)

                # Print to PDF via CDP
                cdp = context.new_cdp_session(page)
                result = cdp.send("Page.printToPDF", {
                    "printBackground": True,
                    "preferCSSPageSize": False,
                    "paperWidth": 8.27,
                    "paperHeight": 11.69,
                    "marginTop": 0.59,  # ~15mm
                    "marginBottom": 0.59,
                    "marginLeft": 0.59,
                    "marginRight": 0.59,
                })

                pdf_data = base64.b64decode(result["data"])
                with open(output_path, "wb") as f:
                    f.write(pdf_data)

                file_size = output_path.stat().st_size
                print(f"  [OK] Saved ({file_size / 1024:.0f} KB)")

                cdp.detach()
                time.sleep(2)

            except Exception as e:
                print(f"  [FAIL] Error: {e}")

        context.close()

    print("\n=== Done! ===")
    all_files = sorted(OUTPUT_DIR.glob("*.pdf"))
    print(f"Total PDF files in {OUTPUT_DIR}: {len(all_files)}")
    for f in all_files:
        print(f"  {f.name} ({f.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    crawl_pdfs()
