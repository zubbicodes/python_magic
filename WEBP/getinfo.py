import argparse
from collections import deque
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright


DEFAULT_URL = "https://adsons.net/"
DEFAULT_OUTPUT_FILE = "info.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl a website and save visible text to Markdown.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Start URL (e.g. https://example.com/).")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE, help="Output markdown file path.")
    return parser.parse_args()


def extract_page_data(page, url: str) -> dict[str, str]:
    title = page.title()
    body_text = page.locator("body").inner_text()
    return {"url": url, "title": title, "text": body_text.strip()[:6000]}


def extract_internal_links(page, current_url: str, base_netloc: str) -> set[str]:
    links: set[str] = set()
    anchors = page.locator("a").all()

    for a in anchors:
        try:
            href = a.get_attribute("href")
            if not href:
                continue
            full_url = urljoin(current_url, href)
            parsed = urlparse(full_url)
            if parsed.netloc != base_netloc:
                continue
            clean = full_url.split("#")[0]
            links.add(clean)
        except Exception:
            continue

    return links


def crawl_site(start_url: str) -> list[dict[str, str]]:
    parsed_start = urlparse(start_url)
    base_netloc = parsed_start.netloc
    if not base_netloc:
        raise ValueError(f"Invalid URL: {start_url}")

    visited: set[str] = set()
    queue: deque[str] = deque([start_url])
    all_pages: list[dict[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        while queue:
            url = queue.popleft()
            if url in visited:
                continue

            visited.add(url)
            try:
                page.goto(url, timeout=20000)
                page.wait_for_timeout(1500)
                all_pages.append(extract_page_data(page, url))

                for link in extract_internal_links(page, url, base_netloc=base_netloc):
                    if link not in visited:
                        queue.append(link)
            except Exception:
                continue

        browser.close()

    return all_pages


def generate_markdown(base_url: str, pages: list[dict[str, str]], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Full Website Extract Report (Playwright)\n\n")
        f.write(f"## Domain\n{base_url}\n\n")
        f.write(f"### Total Pages Extracted: {len(pages)}\n\n")
        f.write("---\n\n")

        for page in pages:
            f.write(f"## URL\n{page['url']}\n\n")
            f.write(f"### Title\n{page['title']}\n\n")
            f.write("### Extracted Visible Text\n")
            f.write("```text\n")
            f.write(page["text"])
            f.write("\n```\n\n")
            f.write("---\n\n")


def main() -> int:
    args = parse_args()
    url = str(args.url).strip()
    output_path = str(args.output).strip() or DEFAULT_OUTPUT_FILE
    pages = crawl_site(url)
    generate_markdown(url, pages, output_path=output_path)
    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
