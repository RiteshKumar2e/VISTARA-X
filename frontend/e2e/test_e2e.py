"""End-to-end browser tests (Python Playwright) against the real running apps.

Prerequisites: backend on :8000 and frontend on :5173 (see README), then
    pip install playwright pytest && python -m playwright install chromium
    python -m pytest frontend/e2e -q
Screenshots are written to E2E_SCREENSHOT_DIR (default: frontend/e2e/screenshots).
"""

import os
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect, sync_playwright

FRONTEND = os.getenv("E2E_FRONTEND_URL", "http://localhost:5173")
BACKEND = os.getenv("E2E_BACKEND_URL", "http://localhost:8000")
SHOTS = Path(os.getenv("E2E_SCREENSHOT_DIR", Path(__file__).parent / "screenshots"))
WIDTHS = [320, 375, 390, 768, 1024, 1440]
ROUTES = ["/", "/about", "/privacy", "/terms", "/does-not-exist"]


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and pg.errors.append(m.text))
    yield pg
    ctx.close()


def backend(page: Page, method: str, path: str, data=None):
    req = page.request
    fn = {"get": req.get, "post": req.post, "delete": req.delete}[method]
    return fn(f"{BACKEND}{path}", data=data) if data is not None else fn(f"{BACKEND}{path}")


def telemetry(page):
    return backend(page, "get", "/telemetry").json()


def wait_backend(page, predicate, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        t = telemetry(page)
        if predicate(t):
            return t
        time.sleep(0.2)
    raise AssertionError("backend condition not met in time")


def open_console(page):
    backend(page, "post", "/simulation/reset", {"scenario": "warehouse"})
    page.goto(FRONTEND + "/")
    expect(page.locator(".viewport [data-status]")).to_contain_text("Idle", timeout=15000)


def click_world(page, x, y):
    """Click the canvas at world coordinates (matches SimulationViewport.layout)."""
    box = page.locator(".viewport canvas").bounding_box()
    narrow = box["width"] < 520
    left, right, top = (20 if narrow else 28), 8, 8
    scale = (box["width"] - left - right) / 20
    page.mouse.click(box["x"] + left + x * scale, box["y"] + top + (12 - y) * scale)


def test_full_mission_via_ui(page):
    open_console(page)
    expect(page.get_by_role("button", name="Start mission")).to_be_disabled()
    click_world(page, 18.5, 6.0)
    expect(page.locator(".controls")).to_contain_text("Target set to (18.", timeout=5000)
    t = telemetry(page)
    assert abs(t["target"]["x"] - 18.5) < 0.1 and abs(t["target"]["y"] - 6.0) < 0.1

    page.get_by_role("button", name="Start mission").click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Navigating", timeout=5000)
    assert len(telemetry(page)["path"]) >= 2
    page.screenshot(path=str(SHOTS / "mission-navigating.png"))

    wait_backend(page, lambda t: t["mission"]["distance_travelled"] >= 1.5)
    page.get_by_role("button", name="Drop obstacle on route").click()
    expect(page.locator(".events")).to_contain_text("Replanned around", timeout=5000)
    assert telemetry(page)["mission"]["replans"] >= 1
    page.screenshot(path=str(SHOTS / "mission-replanned.png"))

    expect(page.locator(".viewport [data-status]")).to_contain_text("Goal reached", timeout=90000)
    t = telemetry(page)
    assert t["distance_to_target"] <= 0.2 and t["safety"]["collisions"] == 0
    expect(page.locator(".events")).to_contain_text("Goal reached")
    page.screenshot(path=str(SHOTS / "mission-goal.png"), full_page=True)
    assert not page.errors, page.errors


def test_pause_resume_stop_buttons(page):
    open_console(page)
    page.fill("#target-x", "18.5")
    page.fill("#target-y", "6")
    page.get_by_role("button", name="Set target").click()
    page.get_by_role("button", name="Start mission").click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Navigating", timeout=5000)
    page.get_by_role("button", name="Pause").click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Paused", timeout=5000)
    x = telemetry(page)["robot"]["x"]
    time.sleep(0.5)
    assert telemetry(page)["robot"]["x"] == x
    page.get_by_role("button", name="Resume").click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Navigating", timeout=5000)
    page.get_by_role("button", name="Stop").click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Stopped", timeout=5000)
    # Reset during an active mission requires confirmation; when stopped it is immediate.
    page.get_by_role("button", name="Reset").click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Idle", timeout=5000)
    assert telemetry(page)["target"] is None


def test_guided_demo(page):
    open_console(page)
    page.get_by_role("button", name="Run guided demo").click()
    expect(page.locator(".demo")).to_contain_text("Demo complete", timeout=120000)
    t = telemetry(page)
    assert t["mission"]["status"] == "goal_reached"
    assert t["mission"]["replans"] >= 1
    assert any(o["id"].startswith("user-") for o in t["obstacles"])
    page.screenshot(path=str(SHOTS / "guided-demo-complete.png"), full_page=True)


def test_blocked_is_reported_honestly(page):
    open_console(page)
    page.select_option("#scenario", "enclosed")
    page.get_by_role("button", name="Load").click()
    expect(page.locator(".viewport .mono").first).to_be_visible()
    wait_backend(page, lambda t: t["scenario"] == "enclosed")
    page.fill("#target-x", "16")
    page.fill("#target-y", "6")
    page.get_by_role("button", name="Set target").click()
    expect(page.locator(".controls")).to_contain_text("x 16.00", timeout=5000)
    page.get_by_role("button", name="Start mission").click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Blocked", timeout=5000)
    expect(page.locator(".panel").filter(has_text="Live telemetry")).to_contain_text("No collision-free route")
    assert telemetry(page)["mission"]["status"] == "blocked"
    page.screenshot(path=str(SHOTS / "blocked.png"))


def test_target_form_validation(page):
    open_console(page)
    page.fill("#target-x", "abc")
    page.fill("#target-y", "50")
    page.get_by_role("button", name="Set target").click()
    expect(page.locator("#target-x-error")).to_have_text("Enter a number in metres.")
    expect(page.locator("#target-y-error")).to_contain_text("Must be between")
    expect(page.locator("#target-x")).to_have_attribute("aria-invalid", "true")
    # Server-side validation: a target inside a shelf is rejected with a clear message.
    page.fill("#target-x", "5")
    page.fill("#target-y", "9.5")
    page.get_by_role("button", name="Set target").click()
    expect(page.locator(".feedback-error")).to_contain_text("too close to shelf-1")


def test_pages_titles_links_and_404(page):
    titles = set()
    for route in ROUTES:
        page.goto(FRONTEND + route)
        expect(page.locator("h1")).to_be_visible()
        titles.add(page.title())
        for href in page.eval_on_selector_all("a[href^='/']", "els => els.map(e => e.getAttribute('href'))"):
            assert href in ("/", "/about", "/privacy", "/terms"), f"unexpected internal link {href} on {route}"
    assert len(titles) == len(ROUTES), titles
    page.goto(FRONTEND + "/does-not-exist")
    expect(page.locator("h1")).to_have_text("No route to this page")
    assert page.locator('meta[name="robots"]').get_attribute("content") == "noindex"
    page.get_by_role("link", name="Back to the mission console").click()
    expect(page).to_have_url(FRONTEND + "/")
    expect(page.locator("h1")).to_have_text("Mission console")


def test_back_forward_navigation(page):
    page.goto(FRONTEND + "/")
    page.get_by_role("navigation", name="Main").get_by_role("link", name="How it works").click()
    expect(page).to_have_url(FRONTEND + "/about")
    page.get_by_role("link", name="Privacy").click()
    expect(page).to_have_url(FRONTEND + "/privacy")
    page.go_back()
    expect(page).to_have_url(FRONTEND + "/about")
    page.go_back()
    expect(page).to_have_url(FRONTEND + "/")
    page.go_forward()
    expect(page.locator("h1")).to_contain_text("Beyond seeing")


@pytest.mark.parametrize("width", WIDTHS)
def test_no_horizontal_overflow(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, has_touch=width < 1024)
    page = ctx.new_page()
    for route in ROUTES:
        page.goto(FRONTEND + route)
        expect(page.locator("h1")).to_be_visible()
        if route == "/":
            expect(page.locator(".viewport [data-status]")).to_be_visible(timeout=15000)
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 0, f"{route} overflows by {overflow}px at {width}px"
        wide = page.evaluate(
            """() => [...document.querySelectorAll('body *')]
                 .filter(e => e.getBoundingClientRect().right > window.innerWidth + 1
                         && getComputedStyle(e).position !== 'fixed'
                         && !e.closest('.table-wrap, .sr-only, .skip-link'))
                 .slice(0, 5).map(e => e.className || e.tagName)"""
        )
        assert not wide, f"elements past the right edge on {route} at {width}px: {wide}"
        name = route.strip("/").replace("/", "-") or "console"
        page.screenshot(path=str(SHOTS / f"{name}-{width}.png"), full_page=route == "/")
    ctx.close()


def test_mobile_menu_and_touch_target(browser):
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    backend(page, "post", "/simulation/reset", {"scenario": "warehouse"})
    page.goto(FRONTEND + "/")
    toggle = page.get_by_role("button", name="Menu")
    expect(toggle).to_be_visible()
    expect(page.locator("#site-nav")).to_be_hidden()
    toggle.click()
    expect(page.locator("#site-nav")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#site-nav")).to_be_hidden()
    toggle.click()
    page.locator("#site-nav").get_by_role("link", name="How it works").click()
    expect(page).to_have_url(FRONTEND + "/about")
    expect(page.locator("#site-nav")).to_be_hidden()
    # Tap the map to set a target.
    page.goto(FRONTEND + "/")
    expect(page.locator(".viewport [data-status]")).to_contain_text("Idle", timeout=15000)
    box = page.locator(".viewport canvas").bounding_box()
    scale = (box["width"] - 28) / 20
    page.touchscreen.tap(box["x"] + 20 + 10 * scale, box["y"] + 8 + (12 - 6) * scale)
    expect(page.locator(".controls")).to_contain_text("Target set to", timeout=5000)
    ctx.close()


def test_backend_unreachable_state(browser):
    ctx = browser.new_context(viewport={"width": 1024, "height": 900})
    page = ctx.new_page()
    page.route(f"{BACKEND}/**", lambda route: route.abort())
    page.route_web_socket(f"{BACKEND.replace('http', 'ws')}/ws/telemetry", lambda ws: ws.close())
    page.goto(FRONTEND + "/")
    expect(page.get_by_role("alert")).to_contain_text("Backend unreachable", timeout=10000)
    expect(page.locator(".viewport-overlay")).to_contain_text("Simulation unavailable", timeout=10000)
    expect(page.get_by_role("button", name="Run guided demo")).to_be_disabled()
    expect(page.locator(".system")).to_contain_text("Unavailable")
    page.screenshot(path=str(SHOTS / "backend-down.png"))
    ctx.close()


def test_keyboard_focus_visible(page):
    open_console(page)
    page.keyboard.press("Tab")
    expect(page.locator(".skip-link")).to_be_focused()
    page.keyboard.press("Tab")
    shadow = page.evaluate("getComputedStyle(document.activeElement).boxShadow")
    assert shadow and shadow != "none"


SHOTS.mkdir(parents=True, exist_ok=True)
