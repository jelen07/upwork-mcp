"""Job search and details tools for Upwork MCP.

Search hits ``https://www.upwork.com/nx/search/jobs/?q=...`` (the real
search endpoint). The previous implementation used
``/nx/find-work/best-matches`` which silently ignored the ``q`` parameter
and returned the personalised feed regardless of query. Tile parsing uses
Upwork's ``data-test`` hooks which are more stable than the generic
``section``/``h3`` selectors that broke on every layout change.

Combined from two upstream forks:
- andyjones789/upwork-mcp@d9e2ad9e — search URL fix and JobTile parser.
- nfsarch33/upwork-mcp@cab7c837 — profile NEXT_DATA fallback (in
  ``profile.py``).
"""

import asyncio
import re
import urllib.parse

from pydantic import BaseModel, Field

from ..browser.client import get_browser
from ..utils.security import validate_upwork_url


class JobSearchParams(BaseModel):
    """Parameters for job search."""

    query: str = Field(description="Search keywords")
    category: str | None = Field(
        default=None,
        description="Job category filter (currently accepted for compatibility but not encoded in the search URL)",
    )
    experience_level: str | None = Field(
        default=None,
        description="Experience level: entry, intermediate, or expert",
    )
    job_type: str | None = Field(
        default=None,
        description="Job type: hourly or fixed",
    )
    budget_min: int | None = Field(
        default=None,
        description="Minimum fixed-price budget in USD",
    )
    budget_max: int | None = Field(
        default=None,
        description="Maximum fixed-price budget in USD",
    )
    hourly_rate_min: int | None = Field(
        default=None,
        description="Minimum hourly rate in USD (applies to hourly jobs)",
    )
    payment_verified: bool | None = Field(
        default=None,
        description="Only return jobs from payment-verified clients",
    )
    limit: int = Field(default=20, ge=1, le=50, description="Maximum number of results")


class JobDetailsParams(BaseModel):
    """Parameters for getting job details."""

    job_url: str = Field(description="Full Upwork job URL or job ID")


SEARCH_BASE_URL = "https://www.upwork.com/nx/search/jobs/"


def _build_search_url(params: JobSearchParams) -> str:
    """Encode params as a real Upwork search URL.

    Upwork's search endpoint is ``/nx/search/jobs/`` — the personalised
    ``best-matches`` feed silently drops ``?q=`` so it cannot be used.
    """

    qp: dict[str, str] = {"q": params.query}

    if params.experience_level:
        tier = {"entry": "1", "intermediate": "2", "expert": "3"}.get(
            params.experience_level.lower()
        )
        if tier:
            qp["contractor_tier"] = tier

    if params.job_type:
        qp["t"] = "0" if params.job_type.lower() == "hourly" else "1"

    if params.budget_min is not None or params.budget_max is not None:
        lo = "" if params.budget_min is None else params.budget_min
        hi = "" if params.budget_max is None else params.budget_max
        qp["amount"] = f"{lo}-{hi}"

    if params.hourly_rate_min is not None:
        qp["hourly_rate"] = f"{params.hourly_rate_min}-"

    if params.payment_verified:
        qp["payment_verified_only"] = "1"

    return f"{SEARCH_BASE_URL}?{urllib.parse.urlencode(qp)}"


async def _inner_text(parent, selector: str) -> str | None:
    if parent is None:
        return None
    el = await parent.query_selector(selector)
    if el is None:
        return None
    text = await el.text_content()
    return text.strip() if text else None


async def _parse_job_tile(tile) -> dict | None:
    """Extract a single job from one ``article[data-test='JobTile']``."""

    job: dict = {}

    job_uid = await tile.get_attribute("data-ev-job-uid")
    if job_uid:
        job["id"] = job_uid

    title_link = await tile.query_selector('a[data-test*="job-tile-title-link"]')
    if title_link is None:
        return None
    title = (await title_link.text_content() or "").strip()
    href = await title_link.get_attribute("href") or ""
    if not title or "/jobs/" not in href:
        return None
    job["title"] = title
    job["url"] = (
        f"https://www.upwork.com{href}" if href.startswith("/") else href
    )

    posted = await _inner_text(tile, '[data-test="job-pubilshed-date"]')
    if posted:
        job["posted"] = posted

    budget = await _inner_text(tile, '[data-test="job-type-label"]')
    if budget:
        job["budget"] = budget

    experience = await _inner_text(tile, '[data-test="experience-level"]')
    if experience:
        job["experience_level"] = experience

    duration = await _inner_text(tile, '[data-test="duration-label"]')
    if duration:
        job["duration"] = duration

    desc_el = await tile.query_selector('[data-test*="JobDescription"]')
    if desc_el:
        desc = (await desc_el.text_content() or "").strip()
        if desc:
            job["description"] = desc[:500]

    skill_els = await tile.query_selector_all(
        '[data-test*="JobAttrs"] [data-test="token"]'
    )
    skills = []
    for el in skill_els:
        text = await el.text_content()
        if text and text.strip():
            skills.append(text.strip())
    if skills:
        job["skills"] = skills

    client: dict = {}

    if await tile.query_selector('[data-test="payment-verified"]'):
        client["payment_verified"] = True

    rating_el = await tile.query_selector('[data-test*="feedback-rating"]')
    if rating_el:
        aria = await rating_el.get_attribute("aria-label")
        rating_text = aria or (await rating_el.text_content() or "")
        match = re.search(r"(\d+(?:\.\d+)?)", rating_text)
        if match:
            try:
                client["rating"] = float(match.group(1))
            except ValueError:
                pass

    spent = await _inner_text(tile, '[data-test="total-spent"]')
    if spent:
        client["total_spent"] = spent

    location = await _inner_text(tile, '[data-test="location"]')
    if location:
        client["location"] = re.sub(r"^Location\s+", "", location).strip()

    proposals = await _inner_text(tile, '[data-test="proposals-tier"]')
    if proposals:
        match = re.search(r"Proposals:\s*(.+)", proposals)
        client["proposals"] = match.group(1).strip() if match else proposals

    if client:
        job["client"] = client

    return job


async def search_jobs(params: JobSearchParams) -> list[dict]:
    """Search for jobs on Upwork matching the specified criteria.

    Returns a list of job summaries with title, budget, client info, and URL.
    """

    browser = get_browser()
    page = await browser.get_page()

    url = _build_search_url(params)
    await page.goto(url, wait_until="domcontentloaded")

    try:
        await page.wait_for_selector('article[data-test="JobTile"]', timeout=15000)
    except Exception:
        return []

    await asyncio.sleep(1)

    tiles = await page.query_selector_all('article[data-test="JobTile"]')
    jobs: list[dict] = []
    for tile in tiles:
        try:
            job = await _parse_job_tile(tile)
            if job:
                jobs.append(job)
            if len(jobs) >= params.limit:
                break
        except Exception:
            continue

    return jobs


async def get_job_details(params: JobDetailsParams) -> dict:
    """Get detailed information about a specific Upwork job posting.

    Returns comprehensive job details including description, client history,
    skills required, and application requirements.
    """

    browser = get_browser()
    page = await browser.get_page()

    raw = params.job_url
    if "://" not in raw:
        raw = f"https://www.upwork.com/jobs/{raw.lstrip('/')}"
    url = validate_upwork_url(raw)

    await page.goto(url, wait_until="networkidle")
    await asyncio.sleep(3)

    job = {"url": url}

    title_el = await page.query_selector("h1, h2")
    if title_el:
        job["title"] = (await title_el.text_content() or "").strip()

    desc_el = await page.query_selector("[data-test='description'], .description, article p")
    if desc_el:
        job["description"] = (await desc_el.text_content() or "").strip()

    all_text = await page.query_selector_all("p, span, div")
    for el in all_text:
        text = await el.text_content()
        if not text:
            continue
        text = text.strip()

        if "$" in text and len(text) < 50 and not job.get("budget"):
            job["budget"] = text

        if any(x in text.lower() for x in ["entry level", "intermediate", "expert"]):
            if not job.get("experience_level"):
                job["experience_level"] = text

        if any(x in text.lower() for x in ["less than", "1 to 3", "3 to 6", "more than"]):
            if "month" in text.lower() and not job.get("project_length"):
                job["project_length"] = text

    skill_els = await page.query_selector_all("[class*='skill'], [class*='token'], button")
    skills = []
    for el in skill_els[:15]:
        text = await el.text_content()
        if text and 2 < len(text.strip()) < 30:
            skills.append(text.strip())
    if skills:
        job["skills"] = list(set(skills))[:10]

    client = {}
    client_section = await page.query_selector("[data-test='client-info'], [class*='client']")
    if client_section:
        client_text = await client_section.text_content()
        if client_text:
            if "Payment" in client_text and "verified" in client_text.lower():
                client["payment_verified"] = True
            spent_match = re.search(r"\$[\d,]+[KMB]?\+?\s*(spent|total)", client_text, re.I)
            if spent_match:
                client["total_spent"] = spent_match.group(0)

    if client:
        job["client"] = client

    connects_els = await page.query_selector_all("span, div")
    for el in connects_els:
        text = await el.text_content()
        if text and "connect" in text.lower():
            numbers = re.findall(r"\d+", text)
            if numbers:
                job["connects_required"] = int(numbers[0])
                break

    return job
