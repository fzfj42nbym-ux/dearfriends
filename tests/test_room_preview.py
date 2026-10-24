"""Room artwork must survive a raw chat preview without sibling asset files.

Run: python3 -B -m unittest discover -s tests -p 'test_room_preview.py' -v
The canonical index.html is used directly, without export_demo or an asset server.
External requests are blocked; the isolated fake auth starts without a session.
"""

from pathlib import Path
from playwright.sync_api import expect

from test_messenger import NO_SESSION_MOCK, _BrowserCase


class RoomPreviewTests(_BrowserCase):
    def setUp(self):
        self.source = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.context = self.browser.new_context(
            viewport={"width": 1440, "height": 1000}, reduced_motion="reduce",
        )
        self.context.set_default_timeout(5000)
        self.errors, self.asset_requests = [], []
        self.context.add_init_script(NO_SESSION_MOCK)
        self.context.route("**/*", lambda route: route.abort())
        self.context.on("request", lambda request: self.asset_requests.append(request.url)
                        if "assets/room/" in request.url else None)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "The raw preview must not raise JavaScript exceptions")
        self.assertEqual(self.asset_requests, [], "Room artwork must not request sibling asset files")

    def assert_room_works(self, frame):
        expect(frame.locator("#gate")).to_be_visible()
        frame.locator("#demoCode").fill("123")
        frame.locator("#demoCode").press("Enter")
        frame.wait_for_function("document.querySelector('#gate').hidden && !document.documentElement.classList.contains('auth-open')")
        expect(frame.locator("#user")).to_contain_text("Демо")
        expect(frame.locator("html")).to_have_attribute("data-style", "room")
        expect(frame.locator("#homeDashboard")).to_be_visible()

        artwork = frame.evaluate(r"""async () => {
          const images = [...document.querySelectorAll('[data-room-asset]')];
          await Promise.all(images.map(image => image.decode()));
          return {
            images: images.map(image => ({embedded:image.currentSrc.startsWith('data:image/'),
              loaded:image.complete && image.naturalWidth>0 && image.naturalHeight>0}))
          };
        }""")
        self.assertEqual(len(artwork["images"]), 2)
        self.assertTrue(all(item["embedded"] and item["loaded"] for item in artwork["images"]))
        expect(frame.locator(".room-background")).to_be_visible()
        expect(frame.locator(".room-table")).to_be_visible()
        for selector in (".room-photo", ".room-chat", ".room-books-label", ".room-cinema-label"):
            expect(frame.locator(selector)).to_be_visible()
        for kind in ("book", "movie", "series", "game"):
            card = frame.locator(f'#homeMonthPicks [data-home-library-kind="{kind}"]')
            expect(card).to_be_visible()
            expect(card.locator("b")).to_be_visible()
            self.assertTrue(card.get_attribute("data-home-item"))

        frame.locator(".room-chat").click()
        expect(frame.locator("#sectionWindow")).to_be_visible()
        expect(frame.locator("#chat")).to_be_visible()
        frame.locator("#sectionWindowClose").click()
        expect(frame.locator("#sectionWindow")).to_be_hidden()
        book = frame.locator('#homeMonthPicks [data-home-library-kind="book"]')
        title = book.locator("b").inner_text()
        book.click()
        expect(frame.locator("#library")).to_be_visible()
        expect(frame.locator('#libKinds [data-lib-kind="book"]')).to_have_attribute("aria-pressed", "true")
        expect(frame.locator("#libDetailTitle")).to_have_text(title)

    def test_raw_index_room_survives_scripts_only_srcdoc_without_base_url(self):
        self.page.set_content(
            '<iframe id="preview" sandbox="allow-scripts" '
            'style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe>'
        )
        self.page.locator("#preview").evaluate("(node, html) => { node.srcdoc = html; }", self.source)
        frame = self.page.locator("#preview").element_handle().content_frame()
        self.assertIsNotNone(frame)
        frame.wait_for_selector("#demoCode", state="attached")
        self.assertEqual(frame.evaluate("document.URL"), "about:srcdoc")
        self.assertEqual(frame.evaluate("document.baseURI"), "about:blank")
        expect(frame.locator("base")).to_have_count(0)
        self.assert_room_works(frame)


if __name__ == "__main__":
    import unittest
    unittest.main()
