"""Browser regression tests. Run with: python -m unittest discover -s tests -v."""
import os
from pathlib import Path
import re
import subprocess
import unittest

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]


class ForestBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = subprocess.Popen(
            ["node", "server.mjs"], cwd=ROOT,
            env={**os.environ, "PORT": "0"},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8",
        )
        try:
            line = cls.server.stdout.readline()
            match = re.search(r"http://localhost:(\d+)", line)
            if not match:
                raise RuntimeError(f"Server did not start: {line}")
            cls.url = f"http://127.0.0.1:{match.group(1)}"
            cls.playwright = sync_playwright().start()
            channel = os.environ.get("FOREST_BROWSER_CHANNEL") or None
            cls.browser = cls.playwright.chromium.launch(channel=channel, headless=True)
        except Exception:
            if hasattr(cls, "playwright"):
                cls.playwright.stop()
            cls.server.terminate()
            cls.server.wait(timeout=10)
            cls.server.stdout.close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.server.stdout.close()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.page = self.context.new_page()
        self.errors = []
        self.requests = []
        self.failures = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda request: self.requests.append(request.url))
        self.page.on("response", lambda response: self.failures.append(response.url) if response.status >= 400 else None)
        self.page.goto(self.url, wait_until="networkidle")
        self.page.clock.install()

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.failures, [])
        self.assertTrue(all(url.startswith(self.url) for url in self.requests), self.requests)

    def click(self, selector):
        if selector.startswith('[data-practice='):
            if self.page.locator('#focus-dialog').is_visible():
                self.page.locator('#focus-mode').click()
                expect(self.page.locator('#focus-dialog')).not_to_be_visible()
            self.page.locator(selector).click()
            expect(self.page.locator('#focus-dialog')).to_be_visible()
            return
        if selector.startswith(('[data-duration=', '[data-pace=')):
            self.page.locator('.motion-settings').evaluate('e => e.open = true')
        self.page.locator(selector).click()

    def state(self, value):
        expect(self.page.locator("#practice-player")).to_have_attribute("data-state", value)

    def test_paced_breathing_duration_pause_and_completion(self):
        self.click('[data-practice="breathing"]')
        self.click('[data-duration="180"]')
        expect(self.page.locator("#session-time")).to_have_text("3:00")
        self.click("#session-start")
        expect(self.page.locator('[data-duration="60"]')).to_be_disabled()
        expect(self.page.locator('[data-pace="natural"]')).to_be_disabled()
        expect(self.page.locator("#practice-orb")).to_have_attribute("data-phase", "in")
        self.page.clock.run_for(4200)
        expect(self.page.locator("#practice-orb")).to_have_attribute("data-phase", "out")
        self.click("#session-start")
        self.state("paused")
        remaining = self.page.locator("#session-time").inner_text()
        self.page.clock.fast_forward(30000)
        expect(self.page.locator("#session-time")).to_have_text(remaining)
        self.click("#session-start")
        self.page.clock.fast_forward(180000)
        self.state("finished")
        expect(self.page.locator("#session-track")).to_have_attribute("aria-valuenow", "100")
        expect(self.page.locator("#rest-reflection")).to_be_visible()

    def test_natural_breathing_does_not_impose_a_visual_pace(self):
        self.click('[data-practice="breathing"]')
        self.click('[data-pace="natural"]')
        self.click("#session-start")
        self.page.clock.run_for(10200)
        self.state("running")
        expect(self.page.locator("#practice-orb")).to_have_attribute("data-phase", "idle")
        self.assertEqual(self.page.locator("#practice-orb").evaluate("e => getComputedStyle(e).animationName"), "none")
        self.click("#session-stop")
        self.state("finished")
        self.click('[data-reflection="same"]')
        expect(self.page.locator('[data-reflection="same"]')).to_have_attribute("aria-pressed", "true")

    def test_three_stage_meditation_and_all_durations(self):
        self.click('[data-practice="meditation"]')
        expect(self.page.locator("#session-time")).to_have_text("3:00")
        self.click("#session-start")
        self.assertTrue(self.page.locator("#step-label").inner_text().startswith("1 / 3"))
        self.page.clock.fast_forward(60200)
        self.assertTrue(self.page.locator("#step-label").inner_text().startswith("2 / 3"))
        self.page.clock.fast_forward(60000)
        self.assertTrue(self.page.locator("#step-label").inner_text().startswith("3 / 3"))
        self.page.clock.fast_forward(60000)
        self.state("finished")
        for seconds in [60, 300]:
            self.click(f'[data-duration="{seconds}"]')
            self.click("#session-start")
            self.page.clock.fast_forward(seconds * 1000 + 200)
            self.state("finished")
            expect(self.page.locator("#session-time")).to_have_text("0:00")

    def test_external_anchor_manual_steps_and_focus_restore(self):
        self.click('[data-practice="breathing"]')
        self.click("#session-start")
        expect(self.page.locator("#focus-dialog #practice-player")).to_have_count(1)
        self.click("#external-anchor")
        self.state("idle")
        expect(self.page.locator("#practice-player")).to_have_attribute("data-kind", "grounding")
        self.click("#session-start")
        self.page.keyboard.press("Escape")
        expect(self.page.locator('#focus-dialog')).not_to_be_visible()
        self.state('paused')
        self.click('[data-practice="grounding"]')
        self.click('#session-start')
        self.state("running")
        for kind in ["grounding", "body"]:
            if kind == "body":
                self.click('[data-practice="body"]')
                self.click("#session-start")
            self.click("#session-start")
            expect(self.page.locator("#session-next")).to_be_disabled()
            self.click("#session-start")
            for _ in range(5):
                self.click("#session-next")
            self.state("finished")

    def test_audio_discomfort_and_visibility_pause(self):
        self.click("#sound-toggle")
        expect(self.page.locator("#sound")).to_have_attribute("aria-pressed", "true")
        for sound in ["rain", "stream", "wind"]:
            self.click(f'[data-sound="{sound}"]')
            expect(self.page.locator("#sound-toggle")).to_have_attribute("aria-pressed", "true")
        self.page.locator("#volume").fill("15")
        self.click('[data-practice="breathing"]')
        self.click("#session-start")
        self.click("#session-stop")
        self.click('[data-reflection="uncomfortable"]')
        expect(self.page.locator("#sound")).to_have_attribute("aria-pressed", "false")
        self.click("#session-start")
        expect(self.page.locator("#rest-reflection")).not_to_be_visible()
        self.click('#focus-mode')
        expect(self.page.locator('#focus-dialog')).not_to_be_visible()
        self.click("#sound-toggle")
        self.click('[data-practice="breathing"]')
        self.click('#session-start')
        self.page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
        self.state("paused")
        expect(self.page.locator("#sound-toggle")).to_have_attribute("aria-pressed", "false")

    def test_evidence_links_responsiveness_and_reduced_motion(self):
        expected = {"breathing": "30245619", "meditation": "24554970", "grounding": "nhsinform.scot", "body": "uclahealth.org"}
        for kind, source in expected.items():
            self.click(f'[data-practice="{kind}"]')
            self.click('#practice-help')
            self.assertIn(source, self.page.locator("#evidence-source").get_attribute("href"))
            self.assertGreater(len(self.page.locator("#evidence-application").inner_text()), 25)
            self.click('#close-guidance')
            expect(self.page.locator('#guidance-dialog')).not_to_be_visible()
        self.assertEqual(self.page.locator('a[href*="youtube.com/watch"]').count(), 2)
        self.assertEqual(self.page.locator("iframe").count(), 0)
        self.assertEqual(self.page.locator('a[target="_blank"]:not([rel="noopener noreferrer"])').count(), 0)
        for width in [320, 375, 620, 768, 1024, 1440]:
            self.page.set_viewport_size({"width": width, "height": 900})
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width)
            self.assertTrue(self.page.locator('#focus-dialog').evaluate('e => e.scrollWidth <= e.clientWidth'), width)
        self.page.emulate_media(reduced_motion="reduce")
        self.click("#session-start")
        self.assertEqual(self.page.locator("#practice-orb").evaluate("e => getComputedStyle(e).animationName"), "none")

    def test_writing_erasure_navigation_and_no_persistence(self):
        self.click("#writing-space summary")
        self.page.locator("#thought").fill("Private draft")
        self.click('[data-practice="meditation"]')
        expect(self.page.locator("#thought")).to_have_value("Private draft")
        self.click('#focus-mode')
        expect(self.page.locator('#focus-dialog')).not_to_be_visible()
        self.click("#next-prompt")
        expect(self.page.locator("#thought")).to_have_value("Private draft")
        self.click("#release")
        expect(self.page.locator("#thought")).to_have_value("")
        self.page.clock.run_for(1000)
        self.page.locator("#thought").fill("Never stored")
        self.page.goto(self.url + "/index.html")
        self.page.go_back()
        expect(self.page.locator("#thought")).to_have_value("")
        self.assertEqual(self.page.evaluate("localStorage.length"), 0)
        self.assertEqual(self.page.evaluate("sessionStorage.length"), 0)
        self.assertEqual(self.context.cookies(), [])

    def test_line_person_follows_timer_and_freezes_when_paused(self):
        expect(self.page.locator('#focus-dialog')).not_to_be_visible()
        expect(self.page.locator('.rest-library')).not_to_be_visible()
        self.click('[data-practice="breathing"]')
        expect(self.page.locator('#practice-title')).to_have_text('\uc2ec\ud638\ud761\ud558\uae30')
        self.assertFalse(self.page.locator('.motion-settings').evaluate('e => e.open'))
        rest = float(self.page.locator('#breath-halo').get_attribute('rx'))
        self.click('#session-start')
        self.page.clock.run_for(2000)
        expanded = float(self.page.locator('#breath-halo').get_attribute('rx'))
        self.assertGreater(expanded, rest)
        self.page.clock.run_for(2200)
        expect(self.page.locator('#practice-orb')).to_have_attribute('data-phase','out')
        self.click('#session-start')
        frozen = self.page.locator('#person-torso').get_attribute('d')
        self.page.clock.run_for(5000)
        self.assertEqual(self.page.locator('#person-torso').get_attribute('d'), frozen)
        self.click('#focus-mode')
        expect(self.page.locator('#focus-dialog')).not_to_be_visible()
        expect(self.page.locator('[data-practice="breathing"]')).to_be_focused()
        self.click('[data-practice="breathing"]')
        self.state('paused')
        self.click('#session-start')
        self.page.clock.run_for(800)
        self.assertNotEqual(self.page.locator('#person-torso').get_attribute('d'), frozen)
        self.page.emulate_media(reduced_motion='reduce')
        self.page.clock.run_for(1000)
        self.assertEqual(float(self.page.locator('#breath-halo').get_attribute('rx')), rest)


if __name__ == "__main__":
    unittest.main()
