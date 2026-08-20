"""Naukri resume headline auto-refresh helper.

Usage:
    python naukari_update.py --login
    python naukari_update.py --refresh

First run: opens a real browser so you can log in and save the session cookie.
Subsequent runs: reuses the saved session to update the headline.

Notes:
- Naukri's "My home" dashboard (mnjuser/profile) does NOT contain the resume
  headline editor directly anymore -- you have to click through "View profile"
  first to land on the actual profile page where it lives. This script does
  that click automatically.
- If it still can't find the editor, it saves a screenshot + HTML dump to
  ./debug/ so you can inspect what it actually landed on, instead of failing blind.
"""

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SESSION_FILE = Path(__file__).parent / "naukri_session.json"
DEBUG_DIR = Path(__file__).parent / "debug"
DASHBOARD_URL = "https://www.naukri.com/mnjuser/profile"
LOGIN_URL = "https://www.naukri.com/nlogin/login"

# Two similar headlines so the script can make a real visible change.
HEADLINE_A = "Data Engineer | PySpark | Certified in Azure & Databricks | DataOps | Databricks | Kafka | Azure DevOps | Terraform | Azure | GCP | Skilled in Python, Linux | Cloud Automation"
HEADLINE_B = "Data Engineer | PySpark | Certified in Azure & Databricks | DataOps | Databricks | Kafka | Azure DevOps | Terraform | Azure | GCP | Cloud Automation"  # extra space


def build_context(browser, *, storage_state=None):
    context_args = {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "viewport": {"width": 1440, "height": 1200},
        "locale": "en-US",
        "timezone_id": "Asia/Kolkata",
    }
    if storage_state:
        context_args["storage_state"] = storage_state
    return browser.new_context(**context_args)


def login_and_save_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = build_context(browser)
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

        print("\nOpen the browser window and log in manually.")
        print("Handle OTP/CAPTCHA if Naukri asks for it.")
        print("After login, press Enter here to save the session.")
        input()

        context.storage_state(path=str(SESSION_FILE))
        print(f"Session saved to: {SESSION_FILE}")
        browser.close()


def go_to_full_profile(page):
    """The dashboard (mnjuser/profile) is just a home feed now. The actual
    editable profile -- with the Resume headline section -- is reached by
    clicking the 'View profile' button on that dashboard."""
    page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

    view_profile = page.get_by_text("View profile", exact=False).first
    if view_profile.count() > 0:
        view_profile.click(timeout=15000)
        page.wait_for_load_state("domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
    else:
        print("Warning: 'View profile' button not found -- may already be on the full profile page.")


def dump_debug_info(page, label):
    DEBUG_DIR.mkdir(exist_ok=True)
    screenshot_path = DEBUG_DIR / f"{label}.png"
    html_path = DEBUG_DIR / f"{label}.html"
    page.screenshot(path=str(screenshot_path), full_page=True)
    html_path.write_text(page.content(), encoding="utf-8")
    print(f"Saved debug screenshot: {screenshot_path}")
    print(f"Saved debug HTML: {html_path}")
    print("Current URL:", page.url)


def open_headline_editor(page):
    """
    Locate the Resume headline section and click the pencil/edit control
    next to the heading.

    Naukri's profile page has TWO elements containing "Resume headline":
    1. A sidebar/quick-links <li class="collection-item"> -- just a jump
       target, no pencil nearby.
    2. The actual section header further down the page -- this one has
       the edit pencil beside it.
    We skip <li class="collection-item"> matches and use the first
    non-nav match instead.
    """

    matches = page.get_by_text("Resume headline", exact=True)
    total = matches.count()
    print(f"Found {total} element(s) matching 'Resume headline'.")

    heading = None
    for i in range(total):
        candidate = matches.nth(i)
        try:
            is_nav_item = candidate.evaluate(
                "(el) => !!el.closest('li.collection-item')"
            )
        except Exception:
            is_nav_item = False

        if is_nav_item:
            print(f"Match {i}: sidebar nav item, skipping.")
            continue

        print(f"Match {i}: using as section header.")
        heading = candidate
        break

    if heading is None:
        print("No non-nav 'Resume headline' match found.")
        return False

    heading.scroll_into_view_if_needed(timeout=10000)

    # The screenshot shows the pencil immediately beside the heading.
    # Start with the heading's immediate parent.
    parent = heading.locator("xpath=..")

    # Search progressively wider ancestor containers (immediate parent,
    # then grandparent, then great-grandparent) since the pencil icon
    # may live a level or two up from the heading, not as a direct sibling.
    for level in range(1, 4):
        container = heading.locator("xpath=" + "/..".join([".."] * level) if level > 1 else "..")
        # simpler/clearer xpath build:
        container = heading.locator("xpath=" + "/".join([".."] * level))

        edit_controls = container.locator("button, [role='button']")
        for i in range(edit_controls.count()):
            control = edit_controls.nth(i)
            try:
                if control.is_visible():
                    print(f"Clicking edit control near Resume headline (ancestor level {level})...")
                    control.click(timeout=10000)
                    page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue

        svg = container.locator("svg").first
        if svg.count() > 0:
            try:
                if svg.is_visible():
                    print(f"Clicking Resume headline pencil SVG (ancestor level {level})...")
                    svg.click(timeout=10000)
                    page.wait_for_timeout(1500)
                    return True
            except Exception as e:
                print(f"SVG click failed at level {level}:", e)

        edit_candidates = container.locator(
            "[aria-label*='edit' i], [title*='edit' i], [class*='edit' i]"
        )
        for i in range(edit_candidates.count()):
            control = edit_candidates.nth(i)
            try:
                if control.is_visible():
                    print(f"Clicking edit-labelled control (ancestor level {level})...")
                    control.click(timeout=10000)
                    page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue

    print("Could not identify the Resume headline pencil.")

    # Very useful diagnostic -- dump HTML around the heading, going up 3 levels.
    try:
        container = heading.locator("xpath=" + "/".join([".."] * 3))
        print("\n===== Resume headline ancestor(3) HTML =====")
        print(container.evaluate("(el) => el.outerHTML")[:10000])
        print("===== END HTML =====\n")
    except Exception:
        pass

    return False


def find_headline_editor(page):
    """
    Find the actual editable Resume Headline control.

    Naukri may use textarea, input, contenteditable, or role=textbox
    depending on the current UI implementation.
    """

    selectors = [
        "textarea[name*='headline' i]",
        "textarea[id*='headline' i]",
        "textarea[class*='headline' i]",

        "input[name*='headline' i]",
        "input[id*='headline' i]",
        "input[class*='headline' i]",

        "[contenteditable='true']",
        "[role='textbox']",
    ]

    for selector in selectors:
        loc = page.locator(selector)

        for i in range(loc.count()):
            candidate = loc.nth(i)

            try:
                if candidate.is_visible():
                    print(f"Found headline editor using: {selector}")
                    return candidate
            except Exception:
                continue

    return None

def find_save_button(page, editor):
    """
    Find the correct Save button for the headline editor -- NOT the
    hidden 'Save photo' button that also exists elsewhere in the DOM.

    Strategy: scope the search to the nearest form/modal/dialog ancestor
    of the editor itself, and require an EXACT 'Save' text match that is
    currently visible. Only fall back to a page-wide search if nothing
    scoped is found.
    """
    # 1) Look within the editor's own modal/form ancestor first.
    container = editor.locator(
        "xpath=ancestor::*[self::form or "
        "contains(@class,'modal') or contains(@class,'dialog') or "
        "contains(@class,'popup') or contains(@class,'drawer')][1]"
    )

    candidates_sources = []
    if container.count() > 0:
        candidates_sources.append(container)
    candidates_sources.append(page)  # fallback: whole page

    for source in candidates_sources:
        exact_matches = source.get_by_role("button", name="Save", exact=True)
        n = exact_matches.count()
        for i in range(n):
            btn = exact_matches.nth(i)
            try:
                if btn.is_visible():
                    return btn
            except Exception:
                continue

        # Some Naukri buttons aren't real <button role> but divs/spans.
        text_matches = source.locator("text='Save'")
        n = text_matches.count()
        for i in range(n):
            btn = text_matches.nth(i)
            try:
                if btn.is_visible():
                    return btn
            except Exception:
                continue

    return None


def refresh_headline():
    if not SESSION_FILE.exists():
        raise FileNotFoundError(f"Session file not found: {SESSION_FILE}. Run with --login first.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = build_context(browser, storage_state=str(SESSION_FILE))
        page = context.new_page()

        print("Navigating to full profile page (via 'View profile')...")
        go_to_full_profile(page)

        if not open_headline_editor(page):
            print("Could not find the 'Resume headline' section on this page.")
            dump_debug_info(page, "no_headline_section")
            browser.close()
            raise RuntimeError("Resume headline section not found -- check ./debug/ for screenshot + HTML.")

        editor = find_headline_editor(page)
        if editor is None:
            print("Found the headline section but no editable control appeared.")
            dump_debug_info(page, "no_headline_editor")
            browser.close()
            raise RuntimeError("Headline editor not found -- check ./debug/no_headline_editor.")

        try:
            current = editor.input_value(timeout=10000)
        except Exception:
            try:
                current = editor.text_content(timeout=10000) or ""
            except Exception:
                current = ""

        print(f"Current headline: {current!r}")

        new_value = HEADLINE_B if current.strip() == HEADLINE_A else HEADLINE_A
        print(f"Updating to: {new_value!r}")

        try:
            editor.fill(new_value, timeout=10000)
        except Exception:
            editor.click(timeout=10000)
            page.keyboard.press("Control+A")
            page.keyboard.type(new_value, delay=15)

        save_button = find_save_button(page, editor)
        if save_button is None:
            print("Could not find a visible, exact-'Save' button near the editor.")
            dump_debug_info(page, "no_save_button")
            browser.close()
            raise RuntimeError("Save button not found -- check ./debug/no_save_button.")

        save_button.click(timeout=20000)

        page.wait_for_timeout(3000)
        print("Headline refreshed and save action sent.")
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update the Naukri resume headline using a saved auth session.")
    parser.add_argument("--login", action="store_true", help="One-time login to save a browser session.")
    parser.add_argument("--refresh", action="store_true", help="Refresh the headline using the saved session.")
    args = parser.parse_args()

    if args.login:
        login_and_save_session()
    elif args.refresh or SESSION_FILE.exists():
        refresh_headline()
    else:
        print("No session file found. Run: python naukari_update.py --login")
        print("Then run: python naukari_update.py --refresh")