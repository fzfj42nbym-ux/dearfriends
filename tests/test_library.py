"""Library regressions against the real UI and isolated, deterministic fixtures.

Run: python3 -B -m unittest discover -s tests -p 'test_library.py' -v
No production requests, login emails, private data, or external scripts are used.
The exported HTML is also exercised inside sandbox="allow-scripts", matching
the chat preview where native form submissions and origin storage are blocked.
"""

import importlib.util
from pathlib import Path
import unittest

from playwright.sync_api import expect

from test_messenger import MOCK_SUPABASE, _BrowserCase


BOOK = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MOVIE = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
GAME = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
UNRATED = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
SERIES = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

# Extend this test's fake adapter without changing the messenger's fixture
# semantics. Real access control is exercised separately against PostgreSQL.
LIBRARY_MOCK = MOCK_SUPABASE.replace(
    "    delete() { this.op = 'delete'; return this; }",
    "    upsert(value) { this.op = 'upsert'; this.values = [value]; return this; }\n"
    "    delete() { this.op = 'delete'; return this; }",
).replace(
    "      if (this.op === 'insert') {",
    """      if (this.op === 'upsert') {
        data = this.values.map(value => {
          const previous = table.find(row => row.item_id === value.item_id && row.email === value.email);
          if (previous) { Object.assign(previous, clone(value)); return previous; }
          const row = clone(value); table.push(row); return row;
        });
      } else if (this.op === 'insert') {""",
).replace(
    "      if (name !== 'create_conversation') throw new Error('Unexpected RPC: ' + name);",
    """      if (name === 'borrow_library_item') {
        if (state.rpcFailure) { state.rpcFailure = false; return {data: null, error: {code: '55000', message: 'Тест: экземпляр уже занят'}}; }
        const loans = state.tables.library_loans;
        const index = loans.findIndex(row => row.item_id === args.p_item);
        if (args.p_action === 'borrow') {
          if (index >= 0) return {data: null, error: {code: '55000', message: 'Тест: экземпляр уже занят'}};
          loans.push({item_id: args.p_item, borrower_email: me, borrowed_at: new Date().toISOString()});
        } else if (args.p_action === 'return' && index >= 0) loans.splice(index, 1);
        return {data: null, error: null};
      }
      if (name !== 'create_conversation') throw new Error('Unexpected RPC: ' + name);""",
) + r"""
Object.assign(__mock.tables, {
  library_items: [
    {id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', kind: 'book', title: 'Пикник на обочине', creator: 'Стругацкие', genre: 'Фантастика', blurb: 'Зона и её сталкеры.', duration_minutes: null, players_min: null, players_max: null, shareable: true, added_by: 'alice@example.invalid', created_at: '2026-10-01T00:00:00Z'},
    {id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', kind: 'movie', title: 'Уже просмотренный фильм', creator: 'Тестовый режиссёр', genre: 'Приключения', blurb: 'Тестовая история.', duration_minutes: 100, players_min: null, players_max: null, shareable: false, added_by: 'bob@example.invalid', created_at: '2026-10-02T00:00:00Z'},
    {id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', kind: 'game', title: 'Каркассон', creator: 'Клаус-Юрген Вреде', genre: 'Стратегия', blurb: 'Собираем свой город.', duration_minutes: 45, players_min: 2, players_max: 5, shareable: true, added_by: 'alice@example.invalid', created_at: '2026-10-03T00:00:00Z'},
    {id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', kind: 'book', title: 'Книга без оценок', creator: '', genre: '', blurb: '', duration_minutes: null, players_min: null, players_max: null, shareable: false, added_by: 'bob@example.invalid', created_at: '2026-10-04T00:00:00Z'},
    {id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', kind: 'series', title: 'Сериал для друзей', creator: 'Студия клуба', genre: 'Комедия', blurb: 'Смотрим по серии вечером.', duration_minutes: 30, players_min: null, players_max: null, shareable: false, added_by: 'alice@example.invalid', created_at: '2026-09-30T00:00:00Z'}
  ],
  library_marks: [
    {item_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', email: 'alice@example.invalid', rating: 5, status: 'done', review: 'Читается на одном дыхании.'},
    {item_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', email: 'bob@example.invalid', rating: 4, status: 'done', review: ''},
    {item_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', email: 'alice@example.invalid', rating: 5, status: 'done', review: ''},
    {item_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', email: 'tester@example.invalid', rating: 5, status: 'done', review: ''},
    {item_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', email: 'bob@example.invalid', rating: 5, status: 'done', review: ''},
    {item_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', email: 'tester@example.invalid', rating: null, status: 'want', review: ''},
    {item_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', email: 'alice@example.invalid', rating: 5, status: 'done', review: 'Для совместного просмотра.'}
  ],
  library_loans: []
});
"""


class LibraryTests(_BrowserCase):
    def setUp(self):
        self.errors = []
        self.open_fixture()

    def open_fixture(self, script=LIBRARY_MOCK):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        self.context.set_default_timeout(5000)
        self.context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.base_url) else route.abort())
        self.context.add_init_script(script)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.base_url, wait_until="load")
        expect(self.page.locator("#gate")).to_be_hidden()
        self.open_section("library")
        self.select_kind("all")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(5)

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "Unexpected JavaScript exception in the real library")

    def open_item(self, item_id=BOOK):
        self.page.locator(f'#libGrid [data-open="{item_id}"]').click()
        expect(self.page.locator("#libDetail")).to_be_visible()

    def select_kind(self, kind):
        self.page.locator(f'#libKinds [data-lib-kind="{kind}"]').click()
        expect(self.page.locator(f'#libKinds [data-lib-kind="{kind}"]')).to_have_attribute("aria-pressed", "true")

    def test_search_category_and_personal_shelf_combine(self):
        self.select_kind("book")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(2)
        self.page.locator("#libSearch").fill("СТРУГАЦКИЕ")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(1)
        expect(self.page.locator("#libGrid")).to_contain_text("Пикник на обочине")
        self.page.locator("#libShelf").select_option("done")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(0)
        self.page.locator("#libShelf").select_option("want")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(1)

    def test_four_separate_shelves_start_with_films_and_series_stay_separate(self):
        self.page.reload(wait_until="load")
        self.open_section("library")
        expect(self.page.locator('#libKinds [data-lib-kind="movie"]')).to_have_attribute("aria-pressed", "true")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(1)
        expect(self.page.locator(f'#libGrid [data-item="{MOVIE}"]')).to_have_count(1)
        self.select_kind("series")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(1)
        expect(self.page.locator(f'#libGrid [data-item="{SERIES}"]')).to_have_count(1)
        expect(self.page.locator(f'#libGrid [data-item="{MOVIE}"]')).to_have_count(0)
        expect(self.page.locator('#libKinds [data-lib-kind="movie"]')).to_have_attribute("aria-pressed", "false")
        self.page.locator("#libRandom").click()
        expect(self.page.locator("#libDetailTitle")).to_have_text("Сериал для друзей")
        expect(self.page.locator("#libDetailKind")).to_contain_text("Сериал")
        expect(self.page.locator("#libLoan")).to_be_hidden()

    def test_series_creation_uses_episode_minutes_without_players_or_copy(self):
        self.select_kind("series")
        self.page.locator("#libAdd").click()
        expect(self.page.locator("#libType")).to_have_value("series")
        expect(self.page.locator("label").filter(has=self.page.locator("#libDuration"))).to_contain_text("Минут на серию")
        expect(self.page.locator("#libDuration")).to_be_enabled()
        expect(self.page.locator("#libMinPlayers")).to_be_disabled()
        expect(self.page.locator("#libMaxPlayers")).to_be_disabled()
        expect(self.page.locator("#libShareable")).to_be_disabled()
        self.page.locator("#libTitle").fill("Ещё один сериал клуба")
        self.page.locator("#libDuration").fill("35")
        self.page.locator("#libAddSave").click()
        expect(self.page.locator("#libAddDialog")).to_be_hidden()
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(2)
        row = self.page.evaluate("__mock.tables.library_items.find(row => row.title === 'Ещё один сериал клуба')")
        self.assertEqual(row["kind"], "series")
        self.assertEqual(row["duration_minutes"], 35)
        self.assertFalse(row["shareable"])
        self.assertIsNone(row["players_min"])
        self.assertIsNone(row["players_max"])
        self.select_kind("movie")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(1)
        expect(self.page.locator("#libGrid")).not_to_contain_text("Ещё один сериал клуба")

    def test_recommendations_respect_selected_series_search_and_personal_shelf(self):
        self.select_kind("series")
        expect(self.page.locator("#libRecs [data-open]")).to_have_count(1)
        expect(self.page.locator(f'#libRecs [data-open="{SERIES}"]')).to_have_count(1)
        self.page.locator("#libSearch").fill("Каркассон")
        expect(self.page.locator("#libRecs [data-open]")).to_have_count(0)
        self.page.locator("#libSearch").fill("")
        self.page.locator("#libShelf").select_option("want")
        expect(self.page.locator("#libRecs [data-open]")).to_have_count(0)
        self.page.locator("#libShelf").select_option("all")
        expect(self.page.locator("#libRecs [data-open]")).to_have_count(1)
        self.select_kind("book")
        expect(self.page.locator(f'#libRecs [data-open="{BOOK}"]')).to_have_count(1)
        expect(self.page.locator(f'#libRecs [data-open="{SERIES}"]')).to_have_count(0)

    def test_recommendations_exclude_completed_items_and_explain_score(self):
        expect(self.page.locator(f'#libRecs [data-open="{MOVIE}"]')).to_have_count(0)
        expect(self.page.locator("#libRecs")).to_contain_text("Пикник на обочине")
        expect(self.page.locator("#libRecs")).to_contain_text("4,5")

    def test_one_rating_per_person_updates_and_review_is_plain_text(self):
        self.open_item()
        self.page.locator("#libRating").select_option("2")
        self.page.locator("#libStatus").select_option("done")
        self.page.locator("#libReview").fill("Мой отзыв <img src=x onerror=alert(1)>")
        self.page.locator("#libSave").click()
        self.page.wait_for_function("__mock.tables.library_marks.some(row => row.email === 'tester@example.invalid' && row.rating === 2 && row.status === 'done')")
        self.page.locator("#libRating").select_option("4")
        self.page.locator("#libSave").click()
        self.page.wait_for_function("__mock.tables.library_marks.some(row => row.email === 'tester@example.invalid' && row.rating === 4 && row.status === 'done')")
        self.assertEqual(self.page.evaluate("__mock.tables.library_marks.filter(row => row.item_id === 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' && row.email === 'tester@example.invalid').length"), 1)
        expect(self.page.locator("#libDetail img[src=x]")).to_have_count(0)
        self.page.locator("#libDetailClose").click()
        self.open_item()
        expect(self.page.locator("#libRating")).to_have_value("4")
        expect(self.page.locator("#libStatus")).to_have_value("done")
        expect(self.page.locator("#libReview")).to_have_value("Мой отзыв <img src=x onerror=alert(1)>")

    def test_failed_rating_save_keeps_draft_and_retry_works(self):
        self.open_item()
        self.page.evaluate("__mock.failNext('library_marks', 'upsert')")
        self.page.locator("#libRating").select_option("3")
        self.page.locator("#libReview").fill("Не теряем этот отзыв")
        self.page.locator("#libSave").click()
        expect(self.page.locator("#libDetailMsg")).not_to_be_empty()
        expect(self.page.locator("#libReview")).to_have_value("Не теряем этот отзыв")
        expect(self.page.locator("#libRating")).to_have_value("3")
        self.assertFalse(self.page.evaluate("__mock.tables.library_marks.some(row => row.email === 'tester@example.invalid' && row.rating === 3)"))
        self.page.locator("#libSave").click()
        self.page.wait_for_function("__mock.tables.library_marks.some(row => row.email === 'tester@example.invalid' && row.rating === 3)")

    def test_failed_add_keeps_fields_and_escaped_title_can_be_retried(self):
        self.page.locator("#libAdd").click()
        self.page.locator("#libTitle").fill("Книга <b>друзей</b>")
        self.page.locator("#libType").select_option("book")
        self.page.evaluate("__mock.failNext('library_items')")
        self.page.locator("#libAddSave").click()
        expect(self.page.locator("#libAddMsg")).not_to_be_empty()
        expect(self.page.locator("#libTitle")).to_have_value("Книга <b>друзей</b>")
        expect(self.page.locator("#libAddDialog")).to_be_visible()
        self.page.locator("#libAddSave").click()
        expect(self.page.locator("#libAddDialog")).to_be_hidden()
        expect(self.page.locator('#libKinds [data-lib-kind="book"]')).to_have_attribute("aria-pressed", "true")
        self.select_kind("all")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(6)
        expect(self.page.locator("#libGrid")).to_contain_text("Книга <b>друзей</b>")
        expect(self.page.locator("#libGrid h3 b")).to_have_count(0)

    def test_add_requires_title_and_valid_player_range(self):
        self.page.locator("#libAdd").click()
        self.page.locator("#libAddSave").click()
        expect(self.page.locator("#libAddDialog")).to_be_visible()
        self.assertFalse(self.page.evaluate("__mock.calls.some(call => call.table === 'library_items' && call.op === 'insert')"))
        self.page.locator("#libTitle").fill("Игра с друзьями")
        self.page.locator("#libType").select_option("game")
        self.page.locator("#libMinPlayers").fill("5")
        self.page.locator("#libMaxPlayers").fill("2")
        self.page.locator("#libAddSave").click()
        expect(self.page.locator("#libAddDialog")).to_be_visible()
        self.assertFalse(self.page.evaluate("__mock.calls.some(call => call.table === 'library_items' && call.op === 'insert')"))

    def test_borrow_and_return_refresh_without_realtime(self):
        self.open_item(GAME)
        self.page.locator("#libLoan").click()
        self.page.wait_for_function("__mock.tables.library_loans.length === 1")
        expect(self.page.locator("#libLoan")).to_contain_text("Вернуть")
        self.page.locator("#libLoan").click()
        self.page.wait_for_function("__mock.tables.library_loans.length === 0")
        expect(self.page.locator("#libLoan")).to_be_enabled()
        self.assertEqual(self.page.evaluate("__mock.calls.filter(call => call.rpc === 'borrow_library_item').map(call => call.args.p_action)"), ["borrow", "return"])

    def test_borrow_failure_does_not_claim_success(self):
        self.open_item(GAME)
        self.page.evaluate("__mock.rpcFailure = true")
        self.page.locator("#libLoan").click()
        expect(self.page.locator("#libDetailMsg")).not_to_be_empty()
        expect(self.page.locator("#libLoan")).to_be_enabled()
        self.assertEqual(self.page.evaluate("__mock.tables.library_loans.length"), 0)

    def test_random_choice_obeys_filters_and_skips_completed(self):
        self.select_kind("game")
        self.page.locator("#libRandom").click()
        expect(self.page.locator("#libDetailTitle")).to_have_text("Каркассон")
        self.page.locator("#libDetailClose").click()
        self.select_kind("movie")
        self.page.locator("#libRandom").click()
        expect(self.page.locator("#libDetail")).to_be_hidden()
        expect(self.page.locator("#libMsg")).not_to_be_empty()

    def test_load_error_is_visible_and_retry_restores_catalog(self):
        self.page.evaluate("__mock.failNext('library_items', 'select')")
        self.page.evaluate("__mock.emit('library_items')")
        expect(self.page.locator("#libRetry")).to_be_visible()
        expect(self.page.locator("#libMsg")).not_to_be_empty()
        self.page.locator("#libRetry").click()
        expect(self.page.locator("#libRetry")).to_be_hidden()
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(5)

    def test_catalog_reads_all_pages_instead_of_truncating_the_shelf(self):
        self.page.evaluate("""() => {
          const base = __mock.tables.library_items[0];
          __mock.tables.library_items = Array.from({length: 501}, (_, i) => ({
            ...base, id: 'bulk-' + String(i).padStart(4, '0'), title: 'Полка ' + i
          }));
          __mock.emit('library_items');
        }""")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(501)
        self.page.locator("#libSearch").fill("Полка 500")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(1)

    def test_newest_sort_keeps_unrated_entries_discoverable(self):
        self.page.locator("#libSort").select_option("new")
        expect(self.page.locator("#libGrid .lib-card").first).to_contain_text("Книга без оценок")

    def test_canonical_member_email_is_used_for_own_marks_and_upsert(self):
        self.context.close()
        self.open_fixture(LIBRARY_MOCK + """
const canonicalEmail = 'Tester@Example.Invalid';
__mock.tables.members.find(row => row.email === 'tester@example.invalid').email = canonicalEmail;
__mock.tables.library_marks.forEach(row => {
  if (row.email === 'tester@example.invalid') row.email = canonicalEmail;
});
""")
        self.page.locator("#libShelf").select_option("want")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(1)
        self.open_item()
        expect(self.page.locator("#libStatus")).to_have_value("want")
        self.page.locator("#libRating").select_option("4")
        self.page.locator("#libSave").click()
        self.page.wait_for_function("__mock.tables.library_marks.some(row => row.item_id === 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' && row.email === 'Tester@Example.Invalid' && row.rating === 4)")
        self.assertEqual(self.page.evaluate("__mock.tables.library_marks.filter(row => row.item_id === 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' && row.email.toLowerCase() === 'tester@example.invalid').length"), 1)

    def test_inflight_rating_cannot_restore_private_state_or_disable_demo(self):
        self.open_item()
        self.page.evaluate("__mock.holdNext('library_marks', {}, 'upsert')")
        self.page.locator("#libReview").fill("Приватный отзыв клуба")
        self.page.locator("#libSave").click()
        self.page.wait_for_function("__mock.holds[0].matched")
        self.page.locator("#libDetailClose").click()
        self.page.evaluate("showGate()")
        self.page.locator("#demoCode").fill("123")
        self.page.locator('#demoForm button[type="submit"]').click()
        expect(self.page.locator("#gate")).to_be_hidden()
        self.page.evaluate("__mock.release(0)")
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        expect(self.page.locator("#homeMonthPicks")).not_to_contain_text("Пикник на обочине")
        self.open_section("library")
        self.select_kind("all")
        expect(self.page.locator("#libGrid .lib-card")).to_have_count(8)
        expect(self.page.locator(f'#libGrid [data-item="{BOOK}"]')).to_have_count(0)
        expect(self.page.locator("#libDetail")).to_be_hidden()
        self.page.locator("#libGrid [data-open]").first.click()
        expect(self.page.locator("#libReview")).to_have_value("")
        expect(self.page.locator("#libReview")).to_be_enabled()
        expect(self.page.locator("#libStatus")).to_be_enabled()
        expect(self.page.locator("#libRating")).to_be_enabled()


class LibraryOfflinePreviewTests(_BrowserCase):
    def test_exported_library_works_in_chat_sandbox_on_mobile_without_network(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("dearfriends_export_demo", root / "scripts" / "export_demo.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        document = module.export_demo((root / "index.html").read_text(encoding="utf-8"))
        context = self.browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        context.set_default_timeout(5000)
        requests, errors, console_errors = [], [], []
        try:
            context.route("**/*", lambda route: route.abort())
            context.on("request", lambda request: requests.append(request.url) if request.url.startswith(("http://", "https://", "ws://", "wss://")) else None)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page.set_content('<iframe id="preview" sandbox="allow-scripts" style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe>')
            page.locator("#preview").evaluate("(element, document) => { element.srcdoc = document; }", document)
            frame = page.locator("#preview").element_handle().content_frame()
            self.assertIsNotNone(frame)
            frame.locator("#demoCode").fill("123")
            frame.locator("#demoCode").press("Enter")
            expect(frame.locator("#gate")).to_be_hidden()
            self.open_section("library", frame)
            expect(frame.locator("#libHeading")).to_be_visible()
            expect(frame.locator("#user")).to_contain_text("Демо")
            expect(frame.locator('#libKinds [data-lib-kind="movie"]')).to_have_attribute("aria-pressed", "true")
            expect(frame.locator("#libGrid .lib-card")).to_have_count(2)
            frame.locator('#libKinds [data-lib-kind="series"]').click()
            expect(frame.locator("#libGrid .lib-card")).to_have_count(2)
            expect(frame.locator("#libMode")).to_contain_text("Демо")
            first = frame.locator("#libGrid [data-open]").first
            first.click()
            expect(frame.locator("#libLoan")).to_be_hidden()
            frame.locator("#libStatus").select_option("want")
            frame.locator("#libRating").select_option("5")
            frame.locator("#libReview").fill("Работает в предпросмотре")
            frame.locator("#libSave").click()
            frame.locator("#libDetailClose").click()
            frame.locator("#libShelf").select_option("want")
            expect(frame.locator("#libGrid .lib-card")).to_have_count(1)
            frame.locator("#libShelf").select_option("all")
            frame.locator("#libAdd").click()
            expect(frame.locator("#libType")).to_have_value("series")
            frame.locator("#libTitle").fill("Наш новый сериал")
            frame.locator("#libDuration").fill("25")
            expect(frame.locator("#libShareable")).to_be_disabled()
            frame.locator("#libAddSave").click()
            expect(frame.locator("#libAddDialog")).to_be_hidden()
            expect(frame.locator("#libGrid .lib-card")).to_have_count(3)
            frame.locator('#libKinds [data-lib-kind="all"]').click()
            expect(frame.locator("#libGrid .lib-card")).to_have_count(9)
            frame.locator('#libKinds [data-lib-kind="book"]').click()
            expect(frame.locator("#libGrid .lib-card")).to_have_count(2)
            frame.locator("#libAdd").click()
            frame.locator("#libTitle").fill("Наша новая книга")
            frame.locator("#libType").select_option("book")
            frame.locator("#libShareable").check()
            frame.locator("#libAddSave").click()
            expect(frame.locator("#libAddDialog")).to_be_hidden()
            expect(frame.locator("#libGrid .lib-card")).to_have_count(3)
            frame.locator("#libSearch").fill("Наша новая книга")
            frame.locator("#libRandom").click()
            expect(frame.locator("#libDetailTitle")).to_have_text("Наша новая книга")
            frame.locator("#libLoan").click()
            expect(frame.locator("#libLoan")).to_contain_text("Вернуть")
            frame.locator("#libLoan").click()
            expect(frame.locator("#libLoan")).to_be_enabled()
            frame.locator("#libDetailClose").click()
            self.open_section("chat", frame)
            expect(frame.locator("#msgr")).to_be_visible()
            frame.locator("#msgrT").fill("Навигация сохраняет локальный чат")
            frame.locator("#msgrT").press("Enter")
            expect(frame.locator("#msgrMsgs")).to_contain_text("Навигация сохраняет локальный чат")
            self.open_section("library", frame)
            expect(frame.locator("#gate")).to_be_hidden()
            expect(frame.locator("#user")).to_contain_text("Демо")
            expect(frame.locator("#libSearch")).to_have_value("Наша новая книга")
            expect(frame.locator("#libGrid .lib-card")).to_have_count(1)
            expect(frame.locator("#libGrid")).to_contain_text("Наша новая книга")
            for scheme in ("dark", "light"):
                page.emulate_media(color_scheme=scheme)
                self.assertTrue(frame.locator("#library").evaluate("element => element.getBoundingClientRect().right <= innerWidth + 1"))
            self.assertEqual(requests, [], "The chat artifact must stay entirely offline")
            self.assertEqual(errors, [])
            self.assertFalse(any("Blocked form submission" in message for message in console_errors), console_errors)
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
