import asyncio
import requests
import io
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
from PyPDF2 import PdfReader
from bs4 import BeautifulSoup


# -----------------------------------
# CONFIGURATION
# -----------------------------------

IMPORTANT_PATHS = [
    "courses",
    "departments",
    "admissions",
    "placements",
    "fee",
    "academics",
    "hostel",
]

MAX_PAGES = 400   # Increase for deeper crawl
MAX_OUTPUT_CHARS = 300000


# -----------------------------------
# Clean HTML Content
# -----------------------------------

def clean_html(html):
    soup = BeautifulSoup(html, "html.parser")

    # Remove unwanted elements
    for tag in soup(["script", "style", "footer", "header", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)

    # Remove excessive whitespace
    return " ".join(text.split())


# -----------------------------------
# PDF Extraction
# -----------------------------------

def extract_pdf_text(pdf_url):
    try:
        print("Extracting PDF:", pdf_url)
        response = requests.get(pdf_url, timeout=20)
        reader = PdfReader(io.BytesIO(response.content))

        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""

        return text

    except Exception as e:
        print("PDF extraction failed:", e)
        return ""


# -----------------------------------
# Async Official Crawl
# -----------------------------------

async def crawl_official(page, base_url):
    visited = set()
    to_visit = [base_url]
    collected_text = []
    pdf_links = []

    domain = urlparse(base_url).netloc

    # Force important sections first
    for path in IMPORTANT_PATHS:
        to_visit.append(urljoin(base_url, path))

    while to_visit and len(visited) < MAX_PAGES:
        url = to_visit.pop(0)

        parsed = urlparse(url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        if clean_url in visited:
            continue

        try:
            print("Crawling:", clean_url)

            await page.goto(clean_url, timeout=60000)
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(2000)

            html = await page.content()
            text = clean_html(html)

            if len(text) > 500:
                collected_text.append(text)

            visited.add(clean_url)

            # Extract all links
            links = await page.query_selector_all("a")

            for link in links:
                href = await link.get_attribute("href")
                if not href:
                    continue

                full_url = urljoin(base_url, href)
                parsed_link = urlparse(full_url)

                # Collect PDFs
                if full_url.lower().endswith(".pdf"):
                    pdf_links.append(full_url)

                # Crawl only same domain
                if parsed_link.netloc == domain:
                    normalized = f"{parsed_link.scheme}://{parsed_link.netloc}{parsed_link.path}"

                    if (
                        normalized not in visited
                        and normalized not in to_visit
                        and normalized.startswith("http")
                    ):
                        to_visit.append(normalized)

        except Exception as e:
            print("Skipping:", e)
            continue

    return collected_text, pdf_links


# -----------------------------------
# External Crawl (Wiki / Aggregators)
# -----------------------------------

async def crawl_external(page, url):
    try:
        print("External crawl:", url)

        await page.goto(url, timeout=60000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)

        html = await page.content()
        return clean_html(html)

    except Exception:
        return ""


# -----------------------------------
# Main Async Multi-Source Crawl
# -----------------------------------

async def async_crawl_all(college_info):
    master_text = []

    official_url = college_info["official"]
    wiki_url = college_info.get("wiki")
    aggregator_urls = college_info.get("aggregators", [])

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 1️⃣ Official Deep Crawl
        official_pages, pdf_links = await crawl_official(page, official_url)
        master_text.extend(official_pages)

        # 2️⃣ Extract PDFs
        seen_pdfs = set()
        seen_text_hashes = set()

        for pdf in pdf_links:

            # Avoid duplicate URLs
            if pdf in seen_pdfs:
                continue

            seen_pdfs.add(pdf)

            pdf_text = extract_pdf_text(pdf)

            if len(pdf_text) > 500:

                # Avoid duplicate content
                text_hash = hash(pdf_text)

                if text_hash not in seen_text_hashes:
                    master_text.append(pdf_text)
                    seen_text_hashes.add(text_hash)


        # 3️⃣ Wikipedia
        if wiki_url:
            wiki_text = await crawl_external(page, wiki_url)
            if len(wiki_text) > 500:
                master_text.append(wiki_text)

        # 4️⃣ Aggregator Sites
        for url in aggregator_urls:
            ext_text = await crawl_external(page, url)
            if len(ext_text) > 500:
                master_text.append(ext_text)

        await browser.close()

    combined = " ".join(master_text)
    return combined[:MAX_OUTPUT_CHARS]


# -----------------------------------
# Django Safe Wrapper
# -----------------------------------

def crawl_college_sources(college_info):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            async_crawl_all(college_info)
        )

        loop.close()

        return result

    except Exception as e:
        print("Crawl failed:", e)
        return ""
