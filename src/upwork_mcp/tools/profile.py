"""Profile and connects tools for Upwork MCP.

Profile scraping reads ``window.__NEXT_DATA__`` first because Upwork is a
Next.js app and the SSR payload is far more reliable than CSS selectors.
We also iterate a list of candidate profile URLs because the previous
single-URL scrape landed on the Settings edit page and the bug surfaced
as ``{"name": "Settings", "skills": ["..."]}`` (issue #1).

Adapted from nfsarch33/upwork-mcp@cab7c837.
"""

import json
import re
from typing import Any

from ..browser.client import get_browser

_PROFILE_URLS = [
    "https://www.upwork.com/freelancers/profile/edit",
    "https://www.upwork.com/nx/profile/main",
    "https://www.upwork.com/nx/profile",
    "https://www.upwork.com/freelancers/me",
    "https://www.upwork.com/freelancers/settings/profile",
]


def _looks_like_settings_page(name: str | None, title: str | None) -> bool:
    """Detect the false-positive case where the scraper landed on an edit page."""

    for value in (name, title):
        if value and value.strip().lower() in {"settings", "profile"}:
            return True
    return False


async def _read_next_data(page: Any) -> dict | None:
    """Read ``window.__NEXT_DATA__`` JSON if present."""

    try:
        raw = await page.evaluate(
            "() => { const el = document.getElementById('__NEXT_DATA__');"
            " return el ? el.textContent : null; }"
        )
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _extract_profile_from_next_data(data: dict) -> dict:
    """Best-effort extraction of profile fields from a Next.js page payload."""

    page_props = (
        data.get("props", {}).get("pageProps", {})
        if isinstance(data, dict)
        else {}
    )

    candidates: list[dict] = []
    for key in ("freelancer", "profile", "userProfile", "user", "viewer"):
        value = page_props.get(key)
        if isinstance(value, dict):
            candidates.append(value)

    profile: dict[str, Any] = {}
    for source in candidates:
        name = source.get("name") or " ".join(
            part for part in (source.get("firstName"), source.get("lastName")) if part
        )
        if name and not profile.get("name"):
            profile["name"] = name.strip()

        for key, target in (
            ("title", "title"),
            ("description", "overview"),
            ("overview", "overview"),
            ("jobTitle", "title"),
        ):
            value = source.get(key)
            if isinstance(value, str) and value.strip() and not profile.get(target):
                profile[target] = value.strip()

        rate = source.get("hourlyRate") or source.get("hourly_rate")
        if isinstance(rate, dict):
            amount = rate.get("amount") or rate.get("value")
            currency = rate.get("currency") or rate.get("currencyCode") or "USD"
            if amount and not profile.get("hourly_rate"):
                profile["hourly_rate"] = f"{amount} {currency}"
        elif isinstance(rate, (int, float, str)) and not profile.get("hourly_rate"):
            profile["hourly_rate"] = str(rate)

        skills = source.get("skills") or source.get("skillTags")
        if isinstance(skills, list) and not profile.get("skills"):
            cleaned: list[str] = []
            for item in skills:
                if isinstance(item, str):
                    cleaned.append(item.strip())
                elif isinstance(item, dict):
                    label = item.get("name") or item.get("preferredLabel")
                    if isinstance(label, str):
                        cleaned.append(label.strip())
            cleaned = [s for s in cleaned if s]
            if cleaned:
                profile["skills"] = cleaned

        jss = source.get("jobSuccessScore") or source.get("jss")
        if jss is not None and not profile.get("job_success_score"):
            profile["job_success_score"] = (
                f"{jss}%" if isinstance(jss, (int, float)) else str(jss)
            )

    return profile


async def get_my_profile() -> dict:
    """Get your Upwork freelancer profile information.

    Tries ``window.__NEXT_DATA__`` first across a list of candidate profile
    URLs because it is more reliable than CSS selectors and avoids the
    ``Settings`` edit-page false positive.
    """

    browser = get_browser()
    await browser.ensure_logged_in()
    page = await browser.get_page()

    profile: dict[str, Any] = {}
    last_url = ""

    for url in _PROFILE_URLS:
        try:
            await page.goto(url, wait_until="networkidle")
        except Exception:
            continue
        last_url = page.url

        next_data = await _read_next_data(page)
        if next_data:
            extracted = _extract_profile_from_next_data(next_data)
            if extracted.get("name") and not _looks_like_settings_page(
                extracted.get("name"), extracted.get("title")
            ):
                profile.update(extracted)
                break

        # DOM fallback. Skip h1 as a name source: it fires "Settings" on the
        # edit page and was the original cause of the bad scrape.
        name_el = await page.query_selector('[data-test="profile-name"], .profile-name')
        if name_el:
            text = (await name_el.text_content() or "").strip()
            if text and not _looks_like_settings_page(text, None):
                profile["name"] = text

        title_el = await page.query_selector(
            '[data-test="profile-title"], .profile-title, [data-cy="title"]'
        )
        if title_el and not profile.get("title"):
            text = (await title_el.text_content() or "").strip()
            if text and not _looks_like_settings_page(None, text):
                profile["title"] = text

        rate_el = await page.query_selector(
            '[data-test="hourly-rate"], .hourly-rate, [data-cy="rate"]'
        )
        if rate_el and not profile.get("hourly_rate"):
            profile["hourly_rate"] = (await rate_el.text_content() or "").strip()

        overview_el = await page.query_selector(
            '[data-test="profile-overview"], .profile-overview, [data-cy="overview"]'
        )
        if overview_el and not profile.get("overview"):
            profile["overview"] = (await overview_el.text_content() or "").strip()

        skill_els = await page.query_selector_all(
            '[data-test="skill"], .skill-badge, .air3-token'
        )
        if skill_els and not profile.get("skills"):
            collected: list[str] = []
            for el in skill_els:
                text = (await el.text_content() or "").strip()
                if text and text.lower() not in {"settings", "profile"}:
                    collected.append(text)
            if collected:
                profile["skills"] = collected

        if profile.get("name") or profile.get("overview") or profile.get("skills"):
            break

    if not profile.get("name") or _looks_like_settings_page(
        profile.get("name"), profile.get("title")
    ):
        return {
            "error": "profile_scrape_unavailable",
            "message": (
                "Upwork did not return a freelancer profile via known URLs. "
                "Re-authenticate or open the profile page manually to verify."
            ),
            "last_url": last_url,
        }

    profile["last_url"] = last_url

    try:
        connects = await get_connects_balance()
        if connects:
            profile["connects"] = connects
    except Exception:
        pass

    return profile


async def get_connects_balance() -> dict:
    """Get current Upwork Connects balance and usage."""

    browser = get_browser()
    await browser.ensure_logged_in()
    page = await browser.get_page()

    await page.goto("https://www.upwork.com/nx/plans/connects/balance", wait_until="networkidle")

    connects = {}

    available_el = await page.query_selector(
        '[data-test="connects-available"], .connects-balance, [data-cy="available-connects"]'
    )
    if available_el:
        text = (await available_el.text_content() or "").strip()
        numbers = re.findall(r"\d+", text)
        if numbers:
            connects["available"] = int(numbers[0])

    if "available" not in connects:
        await page.goto("https://www.upwork.com/nx/find-work/", wait_until="networkidle")
        connects_el = await page.query_selector(
            '[data-test="connects-count"], .connects-count'
        )
        if connects_el:
            text = (await connects_el.text_content() or "").strip()
            numbers = re.findall(r"\d+", text)
            if numbers:
                connects["available"] = int(numbers[0])

    pending_el = await page.query_selector('[data-test="pending-connects"]')
    if pending_el:
        text = (await pending_el.text_content() or "").strip()
        numbers = re.findall(r"\d+", text)
        if numbers:
            connects["pending"] = int(numbers[0])

    return connects


async def get_profile_stats() -> dict:
    """Get profile statistics including earnings and work history."""

    browser = get_browser()
    await browser.ensure_logged_in()
    page = await browser.get_page()

    await page.goto("https://www.upwork.com/nx/wm/contracts", wait_until="networkidle")

    stats = {}

    earnings_el = await page.query_selector('[data-test="total-earnings"], .earnings-total')
    if earnings_el:
        stats["total_earnings"] = (await earnings_el.text_content() or "").strip()

    active_el = await page.query_selector('[data-test="active-contracts"], .active-count')
    if active_el:
        stats["active_contracts"] = (await active_el.text_content() or "").strip()

    hours_el = await page.query_selector('[data-test="total-hours"], .hours-total')
    if hours_el:
        stats["total_hours"] = (await hours_el.text_content() or "").strip()

    jobs_el = await page.query_selector('[data-test="jobs-completed"], .jobs-count')
    if jobs_el:
        stats["jobs_completed"] = (await jobs_el.text_content() or "").strip()

    return stats
