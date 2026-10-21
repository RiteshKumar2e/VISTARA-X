"""End-to-end browser tests (Python Playwright) against the real running apps.

Prerequisites: backend and frontend running (see README; URLs via E2E_BACKEND_URL /
E2E_FRONTEND_URL, defaults :8000 and :5173). Then
    pip install playwright pytest && python -m playwright install chromium
    python -m pytest frontend/e2e -q
Screenshots are written to E2E_SCREENSHOT_DIR (default: frontend/e2e/screenshots).
"""

import os
import re
import time
from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page, expect, sync_playwright

# Software-rendered headless Chromium is slower than a real browser; give UI checks room.
expect.set_options(timeout=10_000)

FRONTEND = os.getenv("E2E_FRONTEND_URL", "http://localhost:5173")
BACKEND = os.getenv("E2E_BACKEND_URL", "http://localhost:8000")
SHOTS = Path(os.getenv("E2E_SCREENSHOT_DIR", Path(__file__).parent / "screenshots"))
WIDTHS = [320, 375, 390, 768, 1024, 1440]
ROUTES = ["/", "/mission", "/architecture", "/technology", "/privacy", "/terms", "/does-not-exist"]
INTERNAL = {"/", "/mission", "/architecture", "/technology", "/privacy", "/terms"}


@pytest.fixture
def browser():
    # A fresh browser per test: a long-lived software-WebGL browser degrades over a run.
    with sync_playwright() as p:
        # Software WebGL so the 3D viewport renders in headless CI.
        b = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        yield b
        b.close()


FIXTURE_WAV = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures" / "tts_en_storage_room.wav"


@pytest.fixture
def browser_with_mic():
    """Chromium with a fake microphone that plays a synthetic-speech WAV (Windows TTS)."""
    with sync_playwright() as p:
        b = p.chromium.launch(args=[
            "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-audio-capture={FIXTURE_WAV}",
        ])
        ctx = b.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        ctx.grant_permissions(["microphone"], origin=FRONTEND)
        ctx.add_init_script("try { localStorage.setItem('vistara.view', 'plan') } catch (e) {}")
        pg = ctx.new_page()
        pg.errors = []
        yield pg
        b.close()


@pytest.fixture
def page(browser):
    # Reduced motion: keeps headless software rendering light and exercises the
    # prefers-reduced-motion path. The 3D test below runs with full motion.
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    # Coordinate-exact tests use the 2D plan view; the 3D view has its own test below.
    ctx.add_init_script("try { localStorage.setItem('vistara.view', 'plan') } catch (e) {}")
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and pg.errors.append(m.text))
    yield pg
    ctx.close()


_http = requests.Session()


def backend(page: Page, method: str, path: str, data=None):
    """Direct HTTP to the backend, independent of the browser (whose request client can
    be starved while software WebGL renders). `page` is kept for call-site symmetry."""
    return _http.request(method.upper(), f"{BACKEND}{path}", json=data, timeout=30)


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
    for _ in range(3):  # the reset must succeed; never test against leftover state
        if backend(page, "post", "/simulation/reset", {"scenario": "warehouse"}).ok:
            break
        time.sleep(1)
    else:
        raise AssertionError("backend reset failed")
    page.goto(FRONTEND + "/mission")
    expect(page.locator(".viewport [data-status]")).to_contain_text("Idle", timeout=15000)


def click_world(page, x, y):
    """Click the plan-view canvas at world coordinates (matches renderer.makeView)."""
    page.locator(".plan-view canvas").scroll_into_view_if_needed()
    box = page.locator(".plan-view canvas").bounding_box()
    narrow = box["width"] < 520
    left, right, top = (20 if narrow else 28), 10, 10
    scale = (box["width"] - left - right) / 20
    page.mouse.click(box["x"] + left + x * scale, box["y"] + top + (12 - y) * scale)


@pytest.fixture
def demo_speed(page):
    """Run at a realistic demo speed so a slow headless browser can act mid-mission."""
    backend(page, "post", "/simulation/config", {"max_speed": 0.6})
    yield
    backend(page, "post", "/simulation/config", {"max_speed": 1.5})


def test_full_mission_via_ui(page, demo_speed):
    open_console(page)
    expect(page.get_by_role("button", name="Start mission")).to_be_disabled()
    click_world(page, 18.5, 6.0)
    expect(page.locator(".controls")).to_contain_text("Target set to (18.")
    t = telemetry(page)
    assert abs(t["target"]["x"] - 18.5) < 0.1 and abs(t["target"]["y"] - 6.0) < 0.1

    page.get_by_role("button", name="Start mission").click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Navigating")
    assert len(telemetry(page)["path"]) >= 2
    page.screenshot(path=str(SHOTS / "mission-navigating.png"))

    wait_backend(page, lambda t: t["mission"]["distance_travelled"] >= 1.5)
    page.get_by_role("button", name="Drop obstacle on route").click()
    expect(page.locator(".events")).to_contain_text("Replanned around")
    assert telemetry(page)["mission"]["replans"] >= 1
    # The replan is recorded with its cause and a validated route.
    hist = telemetry(page)["replan_history"]
    assert hist[-1]["cause"] == "obstruction" and hist[-1]["validated"] is True
    expect(page.locator("#navigation")).to_contain_text("Route obstructed")
    expect(page.locator("#navigation canvas.grid-canvas")).to_be_visible()
    # Dismiss the newest notification (older ones may be auto-dismissing after 8 s).
    # New toasts keep arriving (the patrolling person causes replans), so the stack is
    # rarely "stable" for Playwright's click: dispatch the click on the button itself.
    toast = page.locator(".toast").filter(has_text="Route replanned").last
    expect(toast).to_be_visible()
    text = toast.inner_text()
    toast.get_by_role("button", name="Dismiss notification").dispatch_event("click")
    expect(page.locator(".toast").filter(has_text=text.splitlines()[-1])).to_have_count(0)
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
    expect(page.locator(".viewport [data-status]")).to_contain_text("Navigating")
    page.locator("#controls").get_by_role("button", name="Pause").click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Paused")
    x = telemetry(page)["robot"]["x"]
    time.sleep(0.5)
    assert telemetry(page)["robot"]["x"] == x
    page.locator("#controls").get_by_role("button", name="Resume").click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Navigating")
    page.get_by_role("button", name="Stop", exact=True).click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Stopped")
    # Reset during an active mission requires confirmation; when stopped it is immediate.
    page.get_by_role("button", name="Reset", exact=True).click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Idle")
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
    expect(page.locator(".controls")).to_contain_text("x 16.00")
    page.get_by_role("button", name="Start mission").click()
    expect(page.locator(".viewport [data-status]")).to_contain_text("Blocked")
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
            assert href in INTERNAL, f"unexpected internal link {href} on {route}"
    assert len(titles) == len(ROUTES), titles
    page.goto(FRONTEND + "/does-not-exist")
    expect(page.locator("h1")).to_have_text("No route to this page")
    assert page.locator('meta[name="robots"]').get_attribute("content") == "noindex"
    page.get_by_role("link", name="Back to the mission console").click()
    expect(page).to_have_url(FRONTEND + "/mission")
    expect(page.locator("h1")).to_have_text("Live mission")


def test_back_forward_navigation(page):
    page.goto(FRONTEND + "/")
    page.get_by_role("navigation", name="Main").get_by_role("link", name="Architecture").click()
    expect(page).to_have_url(FRONTEND + "/architecture")
    page.get_by_role("link", name="Privacy").click()
    expect(page).to_have_url(FRONTEND + "/privacy")
    page.go_back()
    expect(page).to_have_url(FRONTEND + "/architecture")
    page.go_back()
    expect(page).to_have_url(FRONTEND + "/")
    expect(page.locator("h1")).to_have_text("VISTARA-X")
    page.go_forward()
    expect(page.locator("h1")).to_contain_text("Perception, planning")


@pytest.mark.parametrize("width", WIDTHS)
def test_no_horizontal_overflow(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, has_touch=width < 1024, reduced_motion="reduce")
    page = ctx.new_page()
    for route in ROUTES:
        page.goto(FRONTEND + route)
        expect(page.locator("h1")).to_be_visible()
        if route == "/mission":
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
        page.screenshot(path=str(SHOTS / f"{name}-{width}.png"), full_page=route in ("/", "/mission"))
    ctx.close()


def test_mobile_menu_and_touch_target(browser):
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, has_touch=True, is_mobile=True, reduced_motion="reduce")
    ctx.add_init_script("try { localStorage.setItem('vistara.view', 'plan') } catch (e) {}")
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
    page.locator("#site-nav").get_by_role("link", name="Architecture").click()
    expect(page).to_have_url(FRONTEND + "/architecture")
    expect(page.locator("#site-nav")).to_be_hidden()
    # Tap the map to set a target.
    page.goto(FRONTEND + "/mission")
    expect(page.locator(".viewport [data-status]")).to_contain_text("Idle", timeout=15000)
    page.locator(".plan-view canvas").scroll_into_view_if_needed()
    box = page.locator(".plan-view canvas").bounding_box()
    scale = (box["width"] - 30) / 20
    page.touchscreen.tap(box["x"] + 20 + 10 * scale, box["y"] + 10 + (12 - 6) * scale)
    expect(page.locator(".controls")).to_contain_text("Target set to")
    ctx.close()


def test_backend_unreachable_state(browser):
    ctx = browser.new_context(viewport={"width": 1024, "height": 900}, reduced_motion="reduce")
    ctx.add_init_script("try { localStorage.setItem('vistara.view', 'plan') } catch (e) {}")
    page = ctx.new_page()
    # Block the backend port for both localhost and 127.0.0.1 (the app may use either).
    port = BACKEND.rsplit(":", 1)[-1]
    page.route(re.compile(rf"^https?://[^/]+:{port}/"), lambda route: route.abort())
    # Telemetry socket never reaches the backend (mock that stays silent).
    page.route_web_socket(re.compile(rf"^wss?://[^/]+:{port}/ws/telemetry"), lambda ws: None)
    page.goto(FRONTEND + "/mission")
    expect(page.get_by_role("alert")).to_contain_text("Backend unreachable", timeout=10000)
    expect(page.locator(".viewport-overlay")).to_be_visible(timeout=10000)  # no telemetry: no map state shown
    expect(page.get_by_role("button", name="Run guided demo")).to_be_disabled()
    expect(page.locator(".system")).to_contain_text("Unavailable")
    page.screenshot(path=str(SHOTS / "backend-down.png"))
    ctx.close()


def test_reduced_motion_disables_effects(page):
    open_console(page)
    expect(page.get_by_label("Motion effects")).not_to_be_checked()  # follows prefers-reduced-motion


def test_keyboard_focus_visible(page):
    open_console(page)
    page.keyboard.press("Tab")
    expect(page.locator(".skip-link")).to_be_focused()
    page.keyboard.press("Tab")
    shadow = page.evaluate("getComputedStyle(document.activeElement).boxShadow")
    assert shadow and shadow != "none"



def test_architecture_explorer_shows_live_status(page):
    backend(page, "post", "/simulation/reset", {"scenario": "warehouse"})
    page.goto(FRONTEND + "/architecture")
    detail = page.locator("#arch-detail")
    expect(detail).to_contain_text("Path planning")
    page.get_by_role("button", name="1.3 YOLO detection").click()
    expect(detail).to_contain_text("YOLO detection")
    expect(detail).to_contain_text("With labelled fallback")
    expect(detail).to_contain_text("Simulated (ground truth)", timeout=10000)  # live detector label
    # Keyboard: arrow keys move between stages.
    page.keyboard.press("ArrowDown")
    expect(detail).to_contain_text("Scene understanding")
    expect(page.get_by_role("button", name="1.4 Scene understanding")).to_be_focused()
    page.get_by_role("button", name="3.3 Environment feedback").click()
    physics = telemetry(page)["safety"]["physics"]
    expect(detail).to_contain_text("PyBullet" if physics == "pybullet" else "analytic 2D", timeout=10000)
    page.locator("details summary", has_text="A* path planning").click()
    expect(page.locator("details[open]")).to_contain_text("octile distance")


def test_overview_process_and_tooltips(page):
    page.goto(FRONTEND + "/")
    expect(page.locator("h1")).to_have_text("VISTARA-X")
    page.get_by_role("button", name="06 Path automatically replanned").click()
    expect(page.locator("#process-detail")).to_contain_text("new A* plan")
    expect(page.get_by_role("link", name="Open the live mission")).to_have_attribute("href", "/mission")
    open_console(page)
    term = page.get_by_role("button", name="Replans")
    term.focus()
    tip = page.locator(".term", has=term).locator("[role=tooltip]")
    expect(tip).to_be_visible()
    page.keyboard.press("Escape")



def test_3d_view_renders_and_selects_target(browser):
    # Reduced motion makes the 3D view render on demand, which keeps software WebGL usable.
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    backend(page, "post", "/simulation/reset", {"scenario": "warehouse"})
    page.goto(FRONTEND + "/mission")
    page.evaluate("try { localStorage.removeItem('vistara.view') } catch (e) {}")
    page.reload()
    canvas = page.locator(".view-3d canvas")
    expect(canvas).to_be_visible(timeout=20000)
    expect(page.get_by_role("button", name="3D", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.locator(".viewport")).not_to_contain_text("3D view unavailable")
    # The orbit camera looks at the map centre, so a click in the middle of the canvas
    # lands on the floor near (10, 6): the backend target must match.
    page.wait_for_timeout(1500)
    box = canvas.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(page.locator(".controls")).to_contain_text("Target set to")
    t = telemetry(page)["target"]
    assert abs(t["x"] - 10) < 0.6 and abs(t["y"] - 6) < 0.6, t
    for name in ("Top", "Follow robot", "Orbit"):
        page.get_by_role("button", name=name, exact=True).click()
        expect(page.get_by_role("button", name=name, exact=True)).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Zoom in").click()
    page.get_by_role("button", name="Reset view").click()
    page.get_by_role("button", name="Plan", exact=True).click()
    expect(page.locator(".plan-view canvas")).to_be_visible()
    page.get_by_role("button", name="3D", exact=True).click()
    expect(canvas).to_be_visible(timeout=20000)
    page.screenshot(path=str(SHOTS / "viewport-3d.png"))
    assert not errors, errors
    ctx.close()



def test_sensors_models_and_obstacle_removal(page):
    open_console(page)
    for name in ("lidar", "ultrasonic"):
        backend(page, "post", "/sensors/configure", {"sensor": name, "enabled": True})
    sensors = page.locator(".sensors")
    expect(sensors).to_contain_text("All simulated")
    expect(sensors).to_contain_text("2D LiDAR (simulated)")
    expect(sensors.locator(".prox")).to_contain_text("Clear", timeout=10000)
    # Turn both proximity sensors off: the UI must show the fail-safe state from the backend.
    # Controlled checkboxes: click, then wait for the backend-confirmed state.
    lidar_box = sensors.get_by_label("Enable 2D LiDAR (simulated)")
    us_box = sensors.get_by_label("Enable Ultrasonic ring (simulated)")
    lidar_box.click()
    expect(lidar_box).not_to_be_checked()
    us_box.click()
    expect(us_box).not_to_be_checked()
    page.fill("#target-x", "18.5")
    page.fill("#target-y", "6")
    page.get_by_role("button", name="Set target").click()
    page.get_by_role("button", name="Start mission").click()
    expect(sensors.locator(".prox")).to_contain_text("Fail-safe speed", timeout=10000)
    lidar_box.click()
    expect(lidar_box).to_be_checked()
    expect(sensors.locator(".prox")).not_to_contain_text("Fail-safe", timeout=10000)
    page.get_by_role("button", name="Stop", exact=True).click()
    # Model registry lists the simulated detector and is driven by the backend.
    models = page.locator("section", has=page.locator("#models-title"))
    expect(models).to_contain_text("Ground truth, not a model")
    assert backend(page, "get", "/models").json()["models"][0]["key"] == "simulated"
    # Add, select and remove an obstacle through the UI.
    page.locator(".segmented label", has_text="Place obstacle").click()
    click_world(page, 3.0, 9.0)
    expect(page.locator(".controls")).to_contain_text("placed")
    oid = next(o["id"] for o in telemetry(page)["obstacles"] if o["id"].startswith("user-"))
    page.wait_for_timeout(600)
    click_world(page, 3.0, 9.0)
    page.get_by_role("button", name=f"Remove {oid}").click()
    expect(page.locator(".controls")).to_contain_text(f"Obstacle {oid} removed")
    assert not any(o["id"] == oid for o in telemetry(page)["obstacles"])
    backend(page, "post", "/sensors/configure", {"sensor": "ultrasonic", "enabled": True})



def test_add_walking_person(page):
    open_console(page)
    page.locator(".segmented label", has_text="Place obstacle").click()
    page.select_option("#object-type", "person-walking")
    click_world(page, 12.0, 6.0)
    expect(page.locator(".viewport-foot")).to_contain_text("click where the person should walk to")
    click_world(page, 12.0, 5.0)
    expect(page.locator(".controls")).to_contain_text("Walking person", timeout=10000)
    person = next(o for o in telemetry(page)["obstacles"] if o["id"].startswith("user-"))
    assert person["label"] == "person" and person["moving"] is True
    # Invalid walking route (through a shelf) is rejected with a clear message.
    click_world(page, 10.0, 6.0)
    click_world(page, 10.0, 9.0)
    expect(page.locator(".feedback-error")).to_contain_text("passes through shelf-3", timeout=10000)



def test_blocked_route_demo_button(page):
    open_console(page)
    page.get_by_role("button", name="Run blocked-route demo").click()
    expect(page.locator(".blocked-demo")).to_contain_text("Verified from telemetry: status BLOCKED", timeout=20000)
    t = telemetry(page)
    assert t["scenario"] == "enclosed" and t["mission"]["status"] == "blocked"
    assert t["mission"]["distance_travelled"] == 0.0
    expect(page.locator(".overview-strip [data-status]")).to_contain_text("Blocked")


SHOTS.mkdir(parents=True, exist_ok=True)


def test_viewport_zoom_effects_and_obstacle_move(page):
    open_console(page)
    stage = page.locator(".viewport")
    zoom_in = stage.get_by_role("button", name="Zoom in")
    zoom_in.click()
    zoom_in.click()
    expect(page.locator(".plan-view canvas")).to_have_class("sim-canvas zoomed")
    stage.get_by_role("button", name="Reset view").click()
    expect(page.locator(".plan-view canvas")).to_have_class("sim-canvas")
    effects = stage.get_by_label("Motion effects")
    effects.uncheck()
    expect(effects).not_to_be_checked()
    effects.check()
    # Place an obstacle, select it, then move it - all confirmed by the backend.
    page.locator(".segmented label", has_text="Place obstacle").click()
    click_world(page, 3.0, 9.0)
    expect(page.locator(".controls")).to_contain_text("Obstacle user-1 placed")
    page.wait_for_timeout(600)  # let telemetry deliver the new obstacle before selecting it
    click_world(page, 3.0, 9.0)
    expect(page.locator(".viewport-foot")).to_contain_text("move user-1")
    click_world(page, 3.0, 10.5)
    expect(page.locator(".controls")).to_contain_text("Moved user-1")
    ob = next(o for o in telemetry(page)["obstacles"] if o["id"] == "user-1")
    assert abs(ob["y"] - 10.5) < 0.1
    # Invalid target: inside a shelf -> backend rejects, UI says why.
    page.locator(".segmented label", has_text="Set target").click()
    click_world(page, 5.0, 10.0)
    expect(page.locator(".feedback-error")).to_contain_text("too close to shelf-1")


def test_system_status_and_restart_demo(page):
    open_console(page)
    status = page.locator(".system")
    for name in ("Backend API", "Simulation", "Telemetry stream", "Navigation planner", "Robot controller", "Vision detector"):
        expect(status).to_contain_text(name)
    expect(status).to_contain_text("A* ready", timeout=10000)
    page.get_by_role("button", name="Restart guided demo").click()
    expect(page.locator(".demo")).to_contain_text("Running")
    expect(page.locator(".viewport [data-status]")).to_contain_text("Navigating", timeout=20000)
    page.get_by_role("button", name="Pause walkthrough").click()
    page.screenshot(path=str(SHOTS / "viewport-demo-running.png"))


def test_demo_mode_lowers_speed_and_restores_it(page):
    open_console(page)
    before = telemetry(page)["params"]["max_speed"]
    toggle = page.locator(".overview-strip").get_by_label("Demo mode")
    toggle.check()
    wait_backend(page, lambda t: abs(t["params"]["max_speed"] - min(0.6, before)) < 1e-6, timeout=10)
    # The preference survives a reload; the 3D quality setting is local to the browser.
    page.reload()
    expect(page.locator(".overview-strip").get_by_label("Demo mode")).to_be_checked()
    page.locator(".overview-strip").get_by_label("Demo mode").uncheck()
    wait_backend(page, lambda t: abs(t["params"]["max_speed"] - before) < 1e-6, timeout=10)
    assert not page.errors, page.errors


def test_trap_the_robot_challenge(page):
    open_console(page)
    speed = telemetry(page)["params"]["max_speed"]
    panel = page.locator("#challenge")
    panel.get_by_role("button", name="Start challenge").click()
    expect(panel).to_contain_text("5 of 5 barriers left")
    wait_backend(page, lambda t: t["mission"]["status"] == "navigating", timeout=20)
    # Pause while placing so a slow headless browser cannot fall behind the robot
    # (a player may pause too), then seal the gap between the racks at x = 15.
    page.locator("#controls").get_by_role("button", name="Pause").click()
    wait_backend(page, lambda t: t["mission"]["status"] == "paused", timeout=10)
    for i, y in enumerate((4.3, 6.0, 7.7), start=1):
        click_world(page, 15.0, y)
        expect(panel).to_contain_text(f"{5 - i} of 5 barriers left")
    page.locator("#controls").get_by_role("button", name="Resume").click()
    expect(panel.locator(".ch-result")).to_contain_text("You trapped it", timeout=60000)
    expect(panel.locator(".ch-result")).to_contain_text("collisions 0")
    t = telemetry(page)
    assert t["mission"]["status"] == "blocked" and t["safety"]["collisions"] == 0
    wait_backend(page, lambda t: abs(t["params"]["max_speed"] - speed) < 1e-6, timeout=10)  # speed restored
    assert not page.errors, page.errors


# ------------------------------------------------------------ commands, mapping, accessibility
def test_hindi_text_command_confirm_and_history(page):
    open_console(page)
    console = page.locator("#commands")
    console.locator("#cmd-text").fill("रोबोट को रिसेप्शन तक ले जाओ")
    console.locator("#cmd-text").press("Enter")  # keyboard submit
    card = console.locator(".cmd-card")
    expect(card).to_contain_text("Waiting for your confirmation")
    expect(card).to_contain_text("Hindi")
    expect(card).to_contain_text("रिसेप्शन तक जाएँ?")
    assert telemetry(page)["mission"]["status"] == "idle"  # nothing moves before confirmation
    card.get_by_role("button", name="Confirm and go").click()
    expect(card).to_contain_text("Executed")
    t = wait_backend(page, lambda t: t["mission"]["status"] == "navigating", timeout=20)
    assert t["target"] == {"x": 2.0, "y": 10.5}
    expect(console.locator(".cmd-history")).to_contain_text("रोबोट को रिसेप्शन तक ले जाओ")
    console.get_by_role("button", name="Emergency stop").click()
    wait_backend(page, lambda t: t["mission"]["status"] == "stopped", timeout=10)
    # Pressed again while stopped: still succeeds (no error, no 409).
    console.get_by_role("button", name="Emergency stop").click()
    expect(page.locator(".controls")).to_contain_text("the robot was not moving")
    assert not page.errors, page.errors


def test_unknown_place_and_example_chip(page):
    open_console(page)
    console = page.locator("#commands")
    console.get_by_role("button", name="Take the robot to the cafeteria").click()
    expect(console.locator(".cmd-card")).to_contain_text("Needs clarification")
    expect(console.locator(".cmd-card")).to_contain_text("I don't know that place")
    assert telemetry(page)["target"] is None
    console.locator("#cmd-place").select_option("exit")
    console.get_by_role("button", name="Go", exact=True).click()
    expect(console.locator(".cmd-card")).to_contain_text("Route found")


def test_voice_command_through_fake_microphone(browser_with_mic):
    page = browser_with_mic
    open_console(page)
    console = page.locator("#commands")
    console.locator("#speech-lang").select_option("en")
    console.get_by_role("button", name="Speak a command").click()
    expect(console.get_by_role("button", name="Stop recording")).to_be_visible()
    time.sleep(3.5)  # the fake microphone plays the WAV fixture
    console.get_by_role("button", name="Stop recording").click()
    card = console.locator(".cmd-card")
    expect(card).to_contain_text("storage room", timeout=90000)
    expect(card).to_contain_text("faster-whisper")
    expect(card).to_contain_text("Waiting for your confirmation")


def test_mapping_panel_explore_save_and_planner(page):
    open_console(page)
    panel = page.locator("#mapping")
    expect(panel).to_contain_text("Simulation-generated")
    panel.get_by_role("button", name="Explore and map automatically").click()
    wait_backend(page, lambda t: t["mapping"]["exploring"] and t["mission"]["status"] == "navigating", timeout=20)
    expect(panel.locator("#planner-map")).to_have_value("slam")
    wait_backend(page, lambda t: t["mapping"]["known_fraction"] > 0.4, timeout=60)
    page.locator("#commands").get_by_role("button", name="Emergency stop").click()
    wait_backend(page, lambda t: t["mission"]["status"] == "stopped", timeout=10)
    panel.locator("summary").filter(has_text="Save, load").click()
    panel.locator("#map-name").fill("e2e_map")
    panel.get_by_role("button", name="Save", exact=True).click()
    expect(panel.locator(".map-list")).to_contain_text("e2e_map", timeout=10000)
    panel.locator(".map-list li").filter(has_text="e2e_map").get_by_role("button", name="Load").click()
    expect(panel.get_by_role("button", name="Imported map: e2e_map")).to_be_visible(timeout=10000)
    panel.locator("#planner-map").select_option("imported")
    wait_backend(page, lambda t: t["mapping"]["planner_map"] == "imported", timeout=10)
    panel.locator("#planner-map").select_option("simulator")
    wait_backend(page, lambda t: t["mapping"]["planner_map"] == "simulator", timeout=10)
    assert not page.errors, page.errors


def test_accessible_mode_and_visual_blocked_alert(page):
    open_console(page)
    page.locator(".alert-settings summary").click()
    page.get_by_label("Accessible mode").check()
    assert page.evaluate("document.documentElement.classList.contains('a11y-large')")
    assert page.evaluate("document.documentElement.classList.contains('a11y-contrast')")
    expect(page.locator("#alert-duration")).to_have_value("0")
    # A blocked mission is announced visually with text, not by colour or sound alone.
    page.get_by_role("button", name="Run blocked-route demo").click()
    banner = page.locator(".alert-centre .alert-danger").first
    expect(banner).to_contain_text("blocked", ignore_case=True, timeout=20000)
    page.get_by_label("Accessible mode").uncheck()
    assert not page.evaluate("document.documentElement.classList.contains('a11y-large')")
