"""Window navigation against the actual offline preview and isolated fake SDK.

Run: python3 -B -m unittest discover -s tests -p 'test_navigation.py' -v
Every remote request is aborted. Viewport resizing does not emulate an OS keyboard.
"""

import importlib.util
from pathlib import Path
import re
import unittest

from playwright.sync_api import expect

from test_messenger import MOCK_SUPABASE, _BrowserCase


SECTIONS = ("chat", "library", "gallery", "events", "help")
FUTURE_SECTIONS = ("challenges", "wishlists", "birthdays", "fund", "sticker-studio", "receipts", "club-room")
READY_CLUB_SECTIONS = {"challenges": "chForm", "birthdays": "bdForm", "fund": "fdForm", "receipts": "rcForm"}
WINDOW_SECTIONS = SECTIONS + ("more",) + FUTURE_SECTIONS
TITLES = {"chat": "Чат", "library": "Библиотека", "gallery": "Галерея",
          "events": "События", "help": "Помощь и сборы", "more": "Ещё",
          "challenges": "Челленджи", "wishlists": "Виш-листы", "birthdays": "Дни рождения",
          "fund": "Общий фонд", "sticker-studio": "Мастерская стикеров",
          "receipts": "Чеки", "club-room": "Комната клуба"}


class NavigationTests(_BrowserCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("dearfriends_navigation_export", root / "scripts" / "export_demo.py")
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)
        self.document = exporter.export_demo((root / "index.html").read_text(encoding="utf-8"))
        self.context = self.browser.new_context(
            viewport={"width": 375, "height": 812}, is_mobile=True,
            has_touch=True, reduced_motion="reduce",
        )
        self.context.set_default_timeout(5000)
        self.errors, self.requests, self.allowed_requests = [], [], set()
        self.context.route("**/*", lambda route: route.abort())
        self.context.on("request", lambda request: self.requests.append(request.url)
                        if request.url.startswith(("http://", "https://", "ws://", "wss://"))
                        and request.url not in self.allowed_requests else None)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.set_content(
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<iframe id="preview" sandbox="allow-scripts" '
            'style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe>'
        )
        self.page.locator("#preview").evaluate("(frame, document) => { frame.srcdoc = document; }", self.document)
        self.frame = self.page.locator("#preview").element_handle().content_frame()
        self.assertIsNotNone(self.frame)
        expect(self.frame.locator("#gate")).to_be_visible()
        self.preview_url = self.frame.url

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "Window navigation must not raise JavaScript exceptions")
        self.assertEqual(self.requests, [], "Preview and fixtures must stay offline")

    def enter_demo(self):
        self.frame.locator("#demoCode").fill("123")
        self.frame.locator("#demoCode").press("Enter")
        self.frame.wait_for_function("document.querySelector('#gate').hidden && !document.documentElement.classList.contains('auth-open')")
        expect(self.frame.locator("#homeDashboard")).to_be_visible()
        expect(self.frame.locator("#sectionWindow")).to_be_hidden()
        expect(self.frame.locator("#homeMonthPicks [data-home-library-kind]")).to_have_count(4)

    def go(self, section, trigger=None):
        self.frame.locator(trigger or f'#sectionNav a[href="#{section}"]').click()
        self.assert_open(section)

    def assert_open(self, section):
        expect(self.frame.locator("#sectionWindow")).to_be_visible()
        if section in TITLES:
            expect(self.frame.locator("#sectionWindowTitle")).to_have_text(TITLES[section])
        else:
            expect(self.frame.locator("#sectionWindowTitle")).to_have_text(re.compile(r"\S"))
        expect(self.frame.locator("html")).to_have_attribute("data-section", section)
        expect(self.frame.locator(f"#sectionWindowBody > #{section}")).to_be_visible()
        if section in SECTIONS:
            expect(self.frame.locator('#sectionNav a[aria-current="location"]')).to_have_count(1)
            expect(self.frame.locator(f'#sectionNav a[href="#{section}"]')).to_have_attribute("aria-expanded", "true")
        else:
            expect(self.frame.locator('#sectionNav a[aria-current="location"]')).to_have_count(0)
            expect(self.frame.locator("#moreOpen")).to_have_attribute("aria-expanded", "true")
            expect(self.frame.locator("#moreOpen")).to_have_attribute("aria-current", "location")
        for other in WINDOW_SECTIONS:
            if other != section:
                expect(self.frame.locator("#" + other)).to_be_hidden()
        self.assertTrue(self.frame.locator("#homeDashboard").evaluate("node => node.inert"))
        self.assertTrue(self.frame.locator("#mainNav").evaluate("node => node.inert"))

    def close(self):
        self.frame.locator("#sectionWindowClose").click()
        expect(self.frame.locator("#sectionWindow")).to_be_hidden()
        expect(self.frame.locator('#sectionNav a[aria-current="location"]')).to_have_count(0)
        self.assertFalse(self.frame.locator("#homeDashboard").evaluate("node => node.inert"))
        self.assertFalse(self.frame.locator("#mainNav").evaluate("node => node.inert"))

    def resize(self, width, height):
        self.page.set_viewport_size({"width": width, "height": height})
        self.frame.wait_for_function("size => innerWidth === size.width && innerHeight === size.height",
                                     arg={"width": width, "height": height})
        self.frame.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")

    def assert_no_outer_overflow(self):
        dimensions = self.frame.evaluate("""() => ({width:innerWidth,height:innerHeight,
          scrollWidth:document.documentElement.scrollWidth,
          scrollHeight:document.documentElement.scrollHeight})""")
        self.assertLessEqual(dimensions["scrollWidth"], dimensions["width"] + 1)
        self.assertLessEqual(dimensions["scrollHeight"], dimensions["height"] + 1)

    def test_home_boards_and_four_month_categories_fit_small_phone_to_desktop(self):
        expect(self.frame.locator("#sectionNav")).to_be_hidden()
        self.enter_demo()
        expect(self.frame.locator("html")).to_have_attribute("data-style", "room")
        assets = self.frame.evaluate(r"""async () => {
          const native = [...document.querySelectorAll('[data-room-asset]')];
          await Promise.all(native.map(node => node.decode()));
          return {native:native.map(node => ({embedded:node.currentSrc.startsWith('data:image/'),
            loaded:node.complete && node.naturalWidth>0 && node.naturalHeight>0}))};
        }""")
        self.assertEqual(len(assets["native"]), 2)
        self.assertTrue(all(item["embedded"] and item["loaded"] for item in assets["native"]))
        for width, height in ((320, 568), (375, 812), (667, 375), (768, 1024), (812, 375), (1101, 651), (1201, 801), (1366, 768), (1440, 1000)):
            with self.subTest(width=width, height=height):
                self.resize(width, height)
                for selector in ("#homeAnnouncements", "#homeHelp", "#homeHelpList", ".home-month"):
                    expect(self.frame.locator(selector)).to_be_visible()
                count = self.frame.locator("#homeHelpCount")
                expect(count).to_have_attribute("aria-label", "Просьб: 0, срочных: 0")
                expect(count).to_be_visible()
                for kind in ("book", "movie", "series", "game"):
                    card = self.frame.locator(f'#homeMonthPicks [data-home-library-kind="{kind}"]')
                    expect(card).to_be_visible()
                    title = card.locator("b")
                    expect(title).to_be_visible()
                    card_bounds, title_bounds = card.bounding_box(), title.bounding_box()
                    self.assertGreaterEqual(title_bounds["y"], card_bounds["y"] - 1,
                                            "The recommendation title must start inside its card")
                    self.assertLessEqual(title_bounds["y"] + title_bounds["height"],
                                         card_bounds["y"] + card_bounds["height"] + 1,
                                         "The recommendation title must fit inside its card")
                    self.assertTrue(card.get_attribute("data-home-item"))
                for section in WINDOW_SECTIONS:
                    expect(self.frame.locator("#" + section)).to_be_hidden()
                self.assert_no_outer_overflow()
                for board in self.frame.locator("#homeDashboard > section").all():
                    bounds = board.bounding_box()
                    self.assertGreaterEqual(bounds["y"], 0)
                    self.assertLessEqual(bounds["y"] + bounds["height"], height + 1,
                                         "Every home board and its actions must fit the viewport")
                    footer = board.locator(".home-board-footer")
                    if footer.count() and footer.is_visible():
                        action = footer.bounding_box()
                        self.assertGreaterEqual(action["y"], bounds["y"] - 1)
                        self.assertLessEqual(action["y"] + action["height"],
                                             bounds["y"] + bounds["height"] + 1,
                                             "The board action must fit inside its own panel")
                        self.assertTrue(footer.evaluate("""node => {
                          const r=node.getBoundingClientRect();
                          const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
                          return node===hit||node.contains(hit);
                        }"""), "The board action must remain reachable by touch or pointer")
                links = self.frame.locator("#sectionNav a:visible")
                expect(links).to_have_count(5 if width <= 800 else 6)
                for section in SECTIONS:
                    expect(self.frame.locator(f'#sectionNav a[href="#{section}"]')).to_have_count(1)

        # The small paper board must show the request itself when it is urgent.
        self.resize(1201, 801)
        self.go("help", '#homeHelp [data-open-section="help"]')
        self.frame.locator("#hpT").fill("Тест: помощь с переездом")
        self.frame.locator("#hpD").fill("В субботу нужны друзья")
        self.frame.locator("#hpU").check()
        self.frame.locator("#hpForm button").click()
        self.close()
        body = self.frame.locator("#homeHelpList").bounding_box()
        title = self.frame.locator("#homeHelpList .urgent b").bounding_box()
        self.assertIsNotNone(title)
        self.assertGreaterEqual(title["y"], body["y"] - 1)
        self.assertLessEqual(title["y"] + title["height"], body["y"] + body["height"] + 1,
                             "The urgent request title must remain readable on the paper board")

        # A populated announcement must fit its paper as well as the empty state.
        self.go("events", '[data-open-section="events"].home-board-footer')
        self.frame.locator("#evT").fill("Вечер настолок у друзей")
        future = self.frame.evaluate("new Date(Date.now()+7*86400000).toISOString().slice(0,10)")
        self.frame.locator("#evD").fill(future)
        self.frame.locator("#evP").fill("Наша комната")
        self.frame.locator("#evForm button").click()
        self.close()
        body = self.frame.locator("#homeAnnouncements").bounding_box()
        title = self.frame.locator("#homeAnnouncements .home-event-copy b").first.bounding_box()
        self.assertIsNotNone(title)
        self.assertGreaterEqual(title["y"], body["y"] - 1)
        self.assertLessEqual(title["y"] + title["height"], body["y"] + body["height"] + 1,
                             "The two-line event title must remain readable on its paper")

    def test_every_section_opens_original_dom_with_single_current_link_and_focus_restore(self):
        self.enter_demo()
        self.frame.evaluate("window.__originalSections = Object.fromEntries(['chat','library','gallery','events','help'].map(id => [id,document.getElementById(id)]))")
        for section in SECTIONS:
            with self.subTest(section=section):
                self.go(section)
                expect(self.frame.locator("#sectionWindowClose")).to_be_focused()
                self.assertTrue(self.frame.evaluate("id => window.__originalSections[id] === document.getElementById(id)", section))
                self.close()
                expect(self.frame.locator(f'#sectionNav a[href="#{section}"]')).to_be_focused()
                expect(self.frame.locator(f'#sectionNav a[href="#{section}"]')).to_have_attribute("aria-expanded", "false")

    def test_scripts_only_switches_preserve_chat_drafts_messages_and_library_marks(self):
        self.enter_demo()
        month_items = self.frame.locator("#homeMonthPicks [data-home-library-kind]").evaluate_all("nodes => nodes.map(node => [node.dataset.homeLibraryKind,node.dataset.homeItem])")
        self.go("chat")
        self.frame.locator("#msgrT").fill("Черновик остаётся в том же поле")
        self.frame.locator("#msgrT").evaluate("node => {window.__originalComposer = node}")
        self.close()
        self.go("help")
        self.close()
        self.go("chat")
        expect(self.frame.locator("#msgrT")).to_have_value("Черновик остаётся в том же поле")
        self.assertTrue(self.frame.evaluate("window.__originalComposer === document.querySelector('#msgrT')"))
        self.frame.locator("#msgrT").press("Enter")
        expect(self.frame.locator("#msgrMsgs")).to_contain_text("Черновик остаётся в том же поле")
        self.close()
        self.go("library")
        self.frame.locator('#libKinds [data-lib-kind="book"]').click()
        self.frame.locator('#libGrid [data-open="demo-prince"]').click()
        self.frame.locator("#libStatus").select_option("want")
        self.frame.locator("#libRating").select_option("4")
        self.frame.locator("#libReview").fill("На следующий книжный вечер")
        self.frame.locator("#libSave").click()
        self.frame.locator("#libDetailClose").click()
        self.frame.locator("#libShelf").select_option("want")
        self.frame.locator("#libSearch").fill("Маленький принц")
        self.close()
        self.go("gallery")
        self.close()
        self.go("library")
        expect(self.frame.locator("#libShelf")).to_have_value("want")
        expect(self.frame.locator("#libSearch")).to_have_value("Маленький принц")
        expect(self.frame.locator("#libGrid .lib-card")).to_have_count(1)
        self.frame.locator('#libGrid [data-open="demo-prince"]').click()
        expect(self.frame.locator("#libRating")).to_have_value("4")
        expect(self.frame.locator("#libReview")).to_have_value("На следующий книжный вечер")
        self.frame.locator("#libDetailClose").click()
        self.close()
        self.go("chat")
        expect(self.frame.locator("#msgrMsgs")).to_contain_text("Черновик остаётся в том же поле")
        expect(self.frame.locator("#gate")).to_be_hidden()
        self.assertEqual(self.frame.url, self.preview_url)
        self.assertEqual(self.frame.locator("#homeMonthPicks [data-home-library-kind]").evaluate_all("nodes => nodes.map(node => [node.dataset.homeLibraryKind,node.dataset.homeItem])"), month_items)

    def test_library_scroll_is_local_and_restored_without_scrolling_home(self):
        self.enter_demo()
        self.resize(320, 568)
        self.go("library")
        self.frame.locator('#libKinds [data-lib-kind="all"]').click()
        body = self.frame.locator("#sectionWindowBody")
        scroll = body.evaluate("node => {node.scrollTop=180;return node.scrollTop}")
        self.assertGreater(scroll, 100)
        self.frame.locator("#sectionWindowClose").focus()
        self.page.keyboard.press("Shift+Tab")
        self.assertTrue(self.frame.evaluate("document.querySelector('#sectionWindow').contains(document.activeElement)"))
        self.page.keyboard.press("Tab")
        expect(self.frame.locator("#sectionWindowClose")).to_be_focused()
        scroll = body.evaluate("node => {node.scrollTop=180;return node.scrollTop}")
        self.close()
        self.assertEqual(self.frame.evaluate("scrollY"), 0)
        self.go("library")
        self.assertAlmostEqual(body.evaluate("node => node.scrollTop"), scroll, delta=1)
        self.assert_no_outer_overflow()

    def test_nested_dialog_escape_and_bestiary_return_to_the_right_surface(self):
        self.enter_demo()
        self.go("library")
        self.frame.locator("#libAdd").click()
        self.frame.locator("#libTitle").fill("Не теряем незавершённую запись")
        self.page.keyboard.press("Escape")
        expect(self.frame.locator("#libAddDialog")).to_be_hidden()
        self.assert_open("library")
        expect(self.frame.locator("#libAdd")).to_be_focused()
        self.page.keyboard.press("Escape")
        expect(self.frame.locator("#sectionWindow")).to_be_hidden()
        expect(self.frame.locator('#sectionNav a[href="#library"]')).to_be_focused()
        self.frame.locator('[data-open-section="beast"]').click()
        expect(self.frame.locator("#beast")).to_be_visible()
        self.assertTrue(self.frame.locator("#homeDashboard").evaluate("node => node.inert"))
        self.page.keyboard.press("Escape")
        expect(self.frame.locator("#beast")).to_be_hidden()
        expect(self.frame.locator('[data-open-section="beast"]')).to_be_focused()

    def test_home_calls_to_action_open_full_sections_and_month_item(self):
        self.enter_demo()
        self.go("gallery", ".room-photo")
        self.close()
        expect(self.frame.locator(".room-photo")).to_be_focused()
        self.go("chat", ".room-chat")
        self.close()
        expect(self.frame.locator(".room-chat")).to_be_focused()
        self.go("events", '[data-open-section="events"].home-board-footer')
        self.close()
        expect(self.frame.locator('[data-open-section="events"].home-board-footer')).to_be_focused()
        self.go("help", '#homeHelp [data-open-section="help"]')
        expect(self.frame.locator("#hpForm")).to_be_visible()
        self.close()
        expect(self.frame.locator('#homeHelp [data-open-section="help"]')).to_be_focused()
        for kind in ("book", "movie", "series", "game"):
            with self.subTest(kind=kind):
                card = self.frame.locator(f'#homeMonthPicks [data-home-library-kind="{kind}"]')
                title = card.locator("b").inner_text()
                card.click()
                self.assert_open("library")
                expect(self.frame.locator(f'#libKinds [data-lib-kind="{kind}"]')).to_have_attribute("aria-pressed", "true")
                expect(self.frame.locator("#libDetail")).to_be_visible()
                expect(self.frame.locator("#libDetailTitle")).to_have_text(title)
                self.page.keyboard.press("Escape")
                self.assert_open("library")
                self.close()
                self.frame.wait_for_function("document.activeElement.matches('#mainNav .logo,[data-home-library-kind]')")
        self.resize(1440, 1000)
        for selector, kind in ((".room-books-label", "book"), (".room-cinema-label", "movie")):
            with self.subTest(shelf=kind):
                self.frame.locator(selector).focus()
                self.frame.locator(selector).press("Enter")
                self.assert_open("library")
                expect(self.frame.locator(f'#libKinds [data-lib-kind="{kind}"]')).to_have_attribute("aria-pressed", "true")
                expect(self.frame.locator("#libSearch")).to_have_value("")
                expect(self.frame.locator("#libShelf")).to_have_value("all")
                expect(self.frame.locator("#libDetail")).to_be_hidden()
                expect(self.frame.locator("#libGrid .lib-card")).to_have_count(2)
                self.close()
                expect(self.frame.locator(selector)).to_be_focused()

    def test_chat_window_fits_resized_mobile_viewport_and_backdrop_closes_desktop(self):
        self.enter_demo()
        for width, height in ((320, 568), (375, 812), (768, 1024), (1440, 1000)):
            with self.subTest(width=width):
                self.resize(width, height)
                self.go("chat")
                composer = self.frame.locator("#msgrT")
                expect(composer).to_be_visible()
                box = composer.bounding_box()
                self.assertGreaterEqual(box["x"], 0)
                self.assertLessEqual(box["x"] + box["width"], width + 1)
                self.assertLessEqual(box["y"] + box["height"], height + 1)
                self.assert_no_outer_overflow()
                self.close()
        self.resize(375, 812)
        self.go("chat")
        self.frame.locator("#msgrT").fill("Черновик при уменьшении окна")
        self.resize(375, 480)
        self.frame.wait_for_function("document.documentElement.classList.contains('app-keyboard')")
        box = self.frame.locator("#msgrT").bounding_box()
        self.assertLessEqual(box["y"] + box["height"], 480)
        self.resize(375, 812)
        expect(self.frame.locator("#msgrT")).to_have_value("Черновик при уменьшении окна")
        self.close()
        self.resize(1440, 1000)
        self.go("events")
        self.page.mouse.click(4, 400)
        expect(self.frame.locator("#sectionWindow")).to_be_hidden()
        expect(self.frame.locator('#sectionNav a[href="#events"]')).to_be_focused()

    def test_more_catalog_opens_ready_and_planned_windows_and_preserves_existing_draft(self):
        self.enter_demo()
        self.go("chat")
        self.frame.locator("#msgrT").fill("Черновик до будущих разделов")
        self.close()
        self.go("more", "#moreOpen")
        cards = self.frame.locator("#more [data-open-section]")
        self.assertEqual(set(cards.evaluate_all("nodes => nodes.map(node => node.dataset.openSection)")),
                         set(FUTURE_SECTIONS))
        expect(cards).to_have_count(7)
        for section in FUTURE_SECTIONS:
            with self.subTest(section=section):
                self.go(section, f'#more [data-open-section="{section}"]')
                window = self.frame.locator("#" + section)
                if section in READY_CLUB_SECTIONS:
                    expect(window.locator("#" + READY_CLUB_SECTIONS[section])).to_be_visible()
                    expect(window).not_to_contain_text("Раздел готовим")
                    expect(self.frame.locator(f'#more [data-open-section="{section}"]')).not_to_contain_text("Скоро")
                elif section == 'club-room':
                    expect(window.locator('#clubRoomFrame')).to_be_visible()
                    expect(window).not_to_contain_text('Раздел готовим')
                    expect(self.frame.locator('#more [data-open-section="club-room"]')).not_to_contain_text('Скоро')
                else:
                    expect(window).to_contain_text("Скоро")
                    expect(window.locator("form,input,textarea,select")).to_have_count(0)
                    expect(window.locator("button")).to_have_count(1)
                expect(window.locator("button[data-return-more]")).to_have_count(1)
                self.go("more", f'#{section} [data-return-more]')
        self.page.keyboard.press("Escape")
        expect(self.frame.locator("#sectionWindow")).to_be_hidden()
        expect(self.frame.locator("#moreOpen")).to_be_focused()
        expect(self.frame.locator("#moreOpen")).to_have_attribute("aria-expanded", "false")
        self.go("chat")
        expect(self.frame.locator("#msgrT")).to_have_value("Черновик до будущих разделов")
        self.close()
        self.assertEqual(self.frame.url, self.preview_url)

    def test_native_history_between_more_and_planned_window_and_deep_link(self):
        url = self.base_url + "future-navigation.html"
        self.allowed_requests.add(url)
        native = self.context.new_page()
        native.on("pageerror", lambda error: self.errors.append(str(error)))
        native.set_viewport_size({"width": 1440, "height": 1000})
        native.route(url, lambda route: route.fulfill(content_type="text/html; charset=utf-8",
                                                     body=self.document.replace(" data-demo-preview", "", 1)))
        try:
            native.goto(url, wait_until="load")
            native.wait_for_function("document.documentElement.classList.contains('app-ready') && document.querySelector('#gate').hidden")
            expect(native.locator("#moreOpen")).to_be_visible()
            native.locator("#moreOpen").click()
            expect(native).to_have_url(url + "#more")
            native.locator('#more [data-open-section="challenges"]').click()
            expect(native).to_have_url(url + "#challenges")
            expect(native.locator("#challenges")).to_be_visible()
            native.go_back()
            expect(native).to_have_url(url + "#more")
            expect(native.locator("#more")).to_be_visible()
            expect(native.locator("#challenges")).to_be_hidden()
            native.go_forward()
            expect(native).to_have_url(url + "#challenges")
            expect(native.locator("#challenges")).to_be_visible()
            native.keyboard.press("Escape")
            expect(native).to_have_url(url)
            expect(native.locator("#sectionWindow")).to_be_hidden()
            expect(native.locator("#moreOpen")).to_be_focused()
            native.goto(url + "#birthdays", wait_until="load")
            expect(native.locator("#sectionWindow")).to_be_visible()
            expect(native.locator("#birthdays")).to_be_visible()
            expect(native.locator("#moreOpen")).to_have_attribute("aria-expanded", "true")
            native.locator("#sectionWindowClose").click()
            expect(native.locator("#sectionWindow")).to_be_hidden()
            expect(native).to_have_url(url)
        finally:
            native.close()

    def test_native_back_and_gallery_nested_lightbox_keep_the_outer_window_consistent(self):
        # A fulfilled local HTTP document exercises actual history and the fake SDK.
        # No SDK URL, image host, or real account is contacted.
        url = self.base_url + "window-fixture.html"
        self.allowed_requests.add(url)
        image = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='60'%3E%3Crect width='80' height='60' fill='teal'/%3E%3C/svg%3E"
        mock = MOCK_SUPABASE.replace(
            "async createSignedUrl() { return {data: null, error: null}; }",
            "async createSignedUrl() { return {data: {signedUrl:window.__fixtureImage}, error:null}; }",
        )
        mock += "\nwindow.__fixtureImage=" + repr(image) + ";window.__mock.tables.photos=[{id:1,path:'fixture/photo.svg',ts:1}];"
        self.context.add_init_script(mock)
        native = self.context.new_page()
        native.on("pageerror", lambda error: self.errors.append(str(error)))
        native.set_viewport_size({"width": 1440, "height": 1000})
        native.route(url, lambda route: route.fulfill(content_type="text/html; charset=utf-8",
                                                     body=self.document.replace(" data-demo-preview", "", 1)))
        try:
            native.goto(url, wait_until="load")
            native.wait_for_function("document.querySelector('#gate').hidden && !document.documentElement.classList.contains('auth-open')")
            link = native.locator('#sectionNav a[href="#gallery"]')
            link.click()
            expect(native).to_have_url(url + "#gallery")
            photo = native.locator("#gal button.gal-shot")
            expect(photo).to_have_count(1)
            photo.focus()
            photo.press("Enter")
            expect(native.locator("#lb")).to_be_visible()
            expect(native.locator("#lbClose")).to_be_focused()
            self.assertTrue(native.locator("#lbClose").evaluate("node => {const r=node.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===node||node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}"))
            native.keyboard.press("Escape")
            expect(native.locator("#lb")).to_be_hidden()
            expect(native.locator("#sectionWindow")).to_be_visible()
            expect(photo).to_be_focused()
            photo.press("Enter")
            expect(native.locator("#lb")).to_be_visible()
            native.go_back()
            expect(native).to_have_url(url)
            expect(native.locator("#sectionWindow")).to_be_hidden()
            expect(native.locator("#lb")).to_be_hidden()
            expect(native.locator('#sectionNav a[aria-current="location"]')).to_have_count(0)
            expect(link).to_be_focused()
            native.go_forward()
            expect(native).to_have_url(url + "#gallery")
            expect(native.locator("#sectionWindow")).to_be_visible()
            expect(link).to_have_attribute("aria-current", "location")
        finally:
            native.close()


if __name__ == "__main__":
    unittest.main()
