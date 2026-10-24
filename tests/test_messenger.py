"""Browser regressions for the real messenger UI, with an isolated fake backend.

Run: python3 -B -m unittest discover -s tests -p 'test_messenger.py' -v
Requires Python Playwright and /usr/bin/chromium. No production API calls, login
emails, credentials, or private user data are used. The server binds loopback on
an ephemeral port; every request outside that server is aborted.
"""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from pathlib import Path
import threading
import unittest

from playwright.sync_api import expect, sync_playwright


CHAT_ALICE = "11111111-1111-4111-8111-111111111111"
CHAT_GROUP = "22222222-2222-4222-8222-222222222222"

MOCK_SUPABASE = r"""
(() => {
  const me = 'tester@example.invalid';
  const alice = 'alice@example.invalid';
  const bob = 'bob@example.invalid';
  const chatAlice = '11111111-1111-4111-8111-111111111111';
  const chatGroup = '22222222-2222-4222-8222-222222222222';
  const state = window.__mock = {
    calls: [], failures: [], holds: [], listeners: [], nextId: 1000, rpcFailure: false,
    session: {user: {email: me}}, authListeners: [], removedChannels: 0,
    tables: {
      members: [
        {email: me, name: 'Тестировщик', char: 'kazar'},
        {email: alice, name: 'Алиса', char: 'alice'},
        {email: bob, name: 'Борис', char: 'misha'}
      ],
      conversations: [
        {id: chatAlice, kind: 'dm', pair_key: [me, alice].sort().join('|'), created_by: me, created_at: '2026-10-01T00:00:00Z'},
        {id: chatGroup, kind: 'group', title: 'Поход в субботу', created_by: me, created_at: '2026-10-02T00:00:00Z'}
      ],
      conversation_members: [
        {conversation_id: chatAlice, email: me}, {conversation_id: chatAlice, email: alice},
        {conversation_id: chatGroup, email: me}, {conversation_id: chatGroup, email: alice},
        {conversation_id: chatGroup, email: bob}
      ],
      chat: Array.from({length: 105}, (_, i) => ({id: i + 1, name: 'Алиса', text: 'Общий ' + String(i + 1).padStart(3, '0'), ts: 1792400000000 + i * 1000})),
      messages: [
        {id: 201, conversation_id: chatAlice, author_email: alice, author_name: 'Алиса', text: 'Личное сообщение Алисы', ts: 1792400100000},
        {id: 202, conversation_id: chatGroup, author_email: bob, author_name: 'Борис', text: 'Встречаемся в субботу', ts: 1792400200000}
      ],
      message_reactions: [], events: [], photos: [], help: [], help_resp: [],
      library_items: [], library_marks: [], library_loans: []
    },
    failNext(table, op = 'insert', rejection = false) {
      state.failures.push({table, op, rejection});
    },
    holdNext(table, equals = {}, op = 'select') {
      const hold = {table, equals, op, matched: false, resolve: null};
      state.holds.push(hold);
      return state.holds.length - 1;
    },
    release(index) {
      const hold = state.holds[index];
      if (!hold || !hold.resolve) throw new Error('Query was not held');
      hold.resolve();
      hold.resolve = null;
    },
    emit(table, row = {}) {
      state.listeners.filter(x => x.config.table === table).forEach(x => x.callback({eventType: 'INSERT', new: row, old: {}}));
    },
    emitAuth(session) {
      state.session = session;
      state.authListeners.slice().forEach(callback => callback('SIGNED_IN', session));
    }
  };
  const clone = value => JSON.parse(JSON.stringify(value));
  class Query {
    constructor(table) { this.table = table; this.op = 'select'; this.filters = []; this.orders = []; this.maximum = Infinity; this.one = false; }
    select() { return this; }
    eq(key, value) { this.filters.push({key, value, kind: 'eq'}); return this; }
    in(key, values) { this.filters.push({key, values, kind: 'in'}); return this; }
    order(key, options = {}) { this.orders.push({key, ascending: options.ascending !== false}); return this; }
    limit(value) { this.maximum = value; return this; }
    range(first, last) { this.offset = first; this.maximum = last - first + 1; return this; }
    maybeSingle() { this.one = true; return this; }
    single() { this.one = true; return this; }
    insert(value) { this.op = 'insert'; this.values = Array.isArray(value) ? value : [value]; return this; }
    delete() { this.op = 'delete'; return this; }
    matches(row) { return this.filters.every(f => f.kind === 'eq' ? row[f.key] === f.value : f.values.includes(row[f.key])); }
    then(resolve, reject) { return this.execute().then(resolve, reject); }
    async execute() {
      state.calls.push({table: this.table, op: this.op, filters: clone(this.filters), orders: clone(this.orders), maximum: this.maximum});
      const failureIndex = state.failures.findIndex(f => f.table === this.table && f.op === this.op);
      if (failureIndex >= 0) {
        const failure = state.failures.splice(failureIndex, 1)[0];
        if (failure.rejection) throw new Error('Тест: сеть недоступна');
        return {data: null, error: {code: 'TEST_FAILURE', message: 'Тест: сеть недоступна'}};
      }
      const table = state.tables[this.table];
      if (!table) throw new Error('Unexpected table: ' + this.table);
      let data;
      if (this.op === 'insert') {
        data = this.values.map(value => ({id: ++state.nextId, ts: Date.now(), ...clone(value)}));
        table.push(...data);
      } else if (this.op === 'delete') {
        data = table.filter(row => this.matches(row));
        state.tables[this.table] = table.filter(row => !this.matches(row));
      } else {
        data = table.filter(row => this.matches(row));
        if (this.orders.length) data = data.slice().sort((a, b) => {
          for (const {key, ascending} of this.orders) {
            if (a[key] === b[key]) continue;
            return (a[key] > b[key] ? 1 : -1) * (ascending ? 1 : -1);
          }
          return 0;
        });
        data = data.slice(this.offset || 0, (this.offset || 0) + this.maximum);
      }
      const result = {data: clone(this.one ? (data[0] || null) : data), error: null};
      const hold = state.holds.find(h => !h.matched && h.table === this.table && h.op === this.op && Object.entries(h.equals).every(([key, value]) => this.filters.some(f => f.key === key && f.value === value)));
      if (hold) {
        hold.matched = true;
        await new Promise(resolve => { hold.resolve = resolve; });
      }
      return result;
    }
  }
  const client = {
    from(table) { return new Query(table); },
    auth: {
      onAuthStateChange(callback) {
        state.authListeners.push(callback);
        return {data: {subscription: {unsubscribe() { state.authListeners = state.authListeners.filter(item => item !== callback); }}}};
      },
      async getSession() { return {data: {session: clone(state.session)}, error: null}; },
      async signInWithOtp() { throw new Error('Tests must not send login emails'); },
      async signOut() { return {error: null}; }
    },
    channel() {
      const channel = {on(_event, config, callback) { state.listeners.push({channel, config, callback}); return channel; }, subscribe() { return channel; }, async unsubscribe() { state.listeners = state.listeners.filter(item => item.channel !== channel); return 'ok'; }};
      return channel;
    },
    async removeChannel(channel) { state.removedChannels++; return channel.unsubscribe(); },
    async removeAllChannels() { state.removedChannels++; state.listeners = []; return []; },
    storage: {from() { return {async createSignedUrl() { return {data: null, error: null}; }}; }},
    async rpc(name, args) {
      state.calls.push({rpc: name, args: clone(args)});
      if (name !== 'create_conversation') throw new Error('Unexpected RPC: ' + name);
      if (state.rpcFailure) {
        state.rpcFailure = false;
        return {data: null, error: {code: 'PGRST202', message: 'Test: create_conversation RPC is unavailable'}};
      }
      const emails = [...new Set([me, ...args.p_emails.map(value => value.trim().toLowerCase())])];
      const pair_key = args.p_kind === 'dm' ? emails.slice().sort().join('|') : null;
      let row = pair_key && state.tables.conversations.find(c => c.pair_key === pair_key);
      if (!row) {
        row = {id: '33333333-3333-4333-8333-' + String(++state.nextId).padStart(12, '0'), kind: args.p_kind, title: args.p_title, pair_key, created_by: me, created_at: new Date().toISOString()};
        state.tables.conversations.push(row);
        state.tables.conversation_members.push(...emails.map(email => ({conversation_id: row.id, email})));
      }
      return {data: row.id, error: null};
    }
  };
  window.supabase = {createClient: () => client};
})();
"""

NO_SESSION_MOCK = MOCK_SUPABASE + "\n__mock.session = null;"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class _BrowserCase(unittest.TestCase):
    def open_section(self, section, page=None):
        """Open a real section window through the same controls as a member."""
        page = page or self.page
        # The gate fades out before its inert background is released.
        page.wait_for_function("document.querySelector('#gate').hidden")
        window = page.locator("#sectionWindow")
        if window.is_visible():
            if page.locator("#" + section).is_visible():
                return
            page.locator("#sectionWindowClose").click()
            expect(window).to_be_hidden()
        page.locator(f'nav a[href="#{section}"]').click()
        expect(window).to_be_visible()
        expect(page.locator("#" + section)).to_be_visible()

    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)


class MessengerTests(_BrowserCase):
    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        self.context.set_default_timeout(5000)
        self.context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.base_url) else route.abort())
        self.context.add_init_script(MOCK_SUPABASE)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.base_url, wait_until="load")
        expect(self.page.locator("#convList .mv")).to_have_count(3)
        expect(self.page.locator("#gate")).to_be_hidden()
        expect(self.page.locator("#load")).to_be_hidden()
        self.open_section("chat")

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "Unexpected JavaScript exception in the real page")

    def open_chat(self, chat_id):
        self.page.locator(f'#convList [data-cid="{chat_id}"]').click()

    def test_latest_history_is_displayed_in_chronological_order(self):
        messages = self.page.locator("#msgrMsgs .mm")
        expect(messages).to_have_count(100)
        expect(messages.first).to_contain_text("Общий 006")
        expect(messages.last).to_contain_text("Общий 105")

    def test_failed_send_keeps_text_and_reports_error(self):
        self.page.evaluate("__mock.failNext('chat')")
        self.page.locator("#msgrT").fill("Сообщение, которое нельзя потерять")
        self.page.locator("#msgrSend").click()
        expect(self.page.locator("#msgrT")).to_have_value("Сообщение, которое нельзя потерять")
        expect(self.page.locator("#msgrStatus")).not_to_be_empty()
        expect(self.page.locator("#msgrSend")).to_be_enabled()
        self.assertFalse(self.page.evaluate("__mock.tables.chat.some(row => row.text === 'Сообщение, которое нельзя потерять')"))

    def test_successful_send_updates_without_realtime(self):
        self.page.locator("#msgrT").fill("Отправлено без realtime <b>текст</b>")
        self.page.locator("#msgrSend").click()
        expect(self.page.locator("#msgrMsgs .mm").last).to_contain_text("Отправлено без realtime <b>текст</b>")
        expect(self.page.locator("#msgrT")).to_have_value("")
        self.assertEqual(self.page.locator("#msgrMsgs .mm").last.locator("b").count(), 1, "User markup must stay escaped")

    def test_repeated_enter_does_not_duplicate_pending_send(self):
        self.page.evaluate("__mock.holdNext('chat', {}, 'insert')")
        self.page.locator("#msgrT").fill("Одно сообщение")
        self.page.locator("#msgrT").press("Enter")
        self.page.wait_for_function("__mock.holds[0].matched")
        self.page.keyboard.press("Enter")
        self.assertEqual(self.page.evaluate("__mock.calls.filter(call => call.table === 'chat' && call.op === 'insert').length"), 1)
        self.page.evaluate("__mock.release(0)")
        expect(self.page.locator("#msgrT")).to_have_value("")
        expect(self.page.locator("#msgrMsgs .mm").last).to_contain_text("Одно сообщение")

    def test_network_rejection_keeps_the_draft(self):
        self.page.evaluate("__mock.failNext('chat', 'insert', true)")
        self.page.locator("#msgrT").fill("Черновик при обрыве сети")
        self.page.locator("#msgrSend").click()
        expect(self.page.locator("#msgrStatus")).not_to_be_empty()
        expect(self.page.locator("#msgrT")).to_have_value("Черновик при обрыве сети")
        expect(self.page.locator("#msgrSend")).to_be_enabled()

    def test_pending_send_does_not_erase_new_text_in_same_chat(self):
        self.page.evaluate("__mock.holdNext('chat', {}, 'insert')")
        self.page.locator("#msgrT").fill("Первое отправляемое сообщение")
        self.page.locator("#msgrSend").click()
        self.page.wait_for_function("__mock.holds[0].matched")
        self.page.locator("#msgrT").fill("Следующий черновик")
        self.page.evaluate("__mock.release(0)")
        expect(self.page.locator("#msgrMsgs .mm").last).to_contain_text("Первое отправляемое сообщение")
        expect(self.page.locator("#msgrT")).to_have_value("Следующий черновик")
        self.open_chat(CHAT_ALICE)
        self.open_chat("all")
        expect(self.page.locator("#msgrT")).to_have_value("Следующий черновик")

    def test_background_refresh_does_not_block_send_or_replace_new_message(self):
        self.page.locator("#msgrT").fill("Сообщение во время фонового обновления")
        self.page.evaluate("__mock.holdNext('chat'); __mock.emit('chat')")
        self.page.wait_for_function("__mock.holds[0].matched")
        expect(self.page.locator("#msgrSend")).to_be_enabled()
        self.page.locator("#msgrT").press("Enter")
        self.page.wait_for_function("__mock.calls.some(call => call.table === 'chat' && call.op === 'insert')")
        expect(self.page.locator("#msgrMsgs .mm").last).to_contain_text("Сообщение во время фонового обновления")
        self.page.evaluate("__mock.release(0)")
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        expect(self.page.locator("#msgrMsgs .mm").last).to_contain_text("Сообщение во время фонового обновления")
        expect(self.page.locator("#msgrT")).to_have_value("")

    def test_pending_send_does_not_clear_other_chat_draft(self):
        self.page.evaluate("__mock.holdNext('chat', {}, 'insert')")
        self.page.locator("#msgrT").fill("Отправляется в общий чат")
        self.page.locator("#msgrSend").click()
        self.page.wait_for_function("__mock.holds[0].matched")
        self.open_chat(CHAT_ALICE)
        self.page.locator("#msgrT").fill("Личный черновик для Алисы")
        self.page.evaluate("__mock.release(0)")
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        expect(self.page.locator("#convTitle")).to_have_text("Алиса")
        expect(self.page.locator("#msgrT")).to_have_value("Личный черновик для Алисы")
        expect(self.page.locator("#msgrMsgs")).not_to_contain_text("Отправляется в общий чат")
        self.open_chat("all")
        expect(self.page.locator("#msgrT")).to_have_value("")
        expect(self.page.locator("#msgrMsgs .mm").last).to_contain_text("Отправляется в общий чат")

    def test_failed_sticker_keeps_panel_and_text_draft_for_retry(self):
        self.page.locator("#msgrT").fill("Сначала стикер, потом этот текст")
        self.page.locator("#stkBtn").click()
        self.page.evaluate("__mock.failNext('chat')")
        self.page.locator('#stkPanel [data-stk="kazar"]').click()
        expect(self.page.locator("#msgrStatus")).to_contain_text("Стикер не отправлен")
        expect(self.page.locator("#stkPanel")).to_be_visible()
        expect(self.page.locator("#msgrT")).to_have_value("Сначала стикер, потом этот текст")
        expect(self.page.locator("#msgrMsgs .stk-chr-w svg")).to_have_count(0)
        self.page.locator('#stkPanel [data-stk="kazar"]').click()
        expect(self.page.locator("#msgrMsgs .stk-chr-w svg")).to_have_count(1)
        expect(self.page.locator("#stkPanel")).to_be_hidden()
        expect(self.page.locator("#msgrT")).to_have_value("Сначала стикер, потом этот текст")

    def test_slow_previous_chat_cannot_overwrite_current_chat(self):
        self.page.evaluate("__mock.holdNext('messages', {conversation_id: '" + CHAT_ALICE + "'})")
        self.open_chat(CHAT_ALICE)
        self.page.wait_for_function("__mock.holds[0].matched")
        self.open_chat(CHAT_GROUP)
        expect(self.page.locator("#msgrMsgs")).to_contain_text("Встречаемся в субботу")
        self.page.evaluate("__mock.release(0)")
        # Give the released promise its next event-loop turn, without a sleep.
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        expect(self.page.locator("#convTitle")).to_have_text("Поход в субботу")
        expect(self.page.locator("#msgrMsgs")).to_contain_text("Встречаемся в субботу")
        expect(self.page.locator("#msgrMsgs")).not_to_contain_text("Личное сообщение Алисы")

    def test_search_filters_chats_and_recovers_from_no_results(self):
        search = self.page.locator("#convSearch")
        search.fill("АЛИСА")
        expect(self.page.locator("#convList .mv")).to_have_count(1)
        expect(self.page.locator("#convList .mv")).to_contain_text("Алиса")
        search.fill("такого чата нет")
        expect(self.page.locator("#convList .mv")).to_have_count(0)
        expect(self.page.locator("#convList")).not_to_be_empty()
        search.clear()
        expect(self.page.locator("#convList .mv")).to_have_count(3)

    def test_member_without_name_uses_searchable_fallback(self):
        context = self.browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        errors = []
        try:
            context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.base_url) else route.abort())
            context.add_init_script(MOCK_SUPABASE + "\n__mock.tables.members.find(row => row.email === 'alice@example.invalid').name = null;")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.base_url, wait_until="load")
            self.open_section("chat", page)
            expect(page.locator(f'#convList [data-cid="{CHAT_ALICE}"] b')).to_have_text("друг")
            page.locator("#convSearch").fill("ДРУГ")
            expect(page.locator("#convList .mv")).to_have_count(1)
            expect(page.locator("#convList .mv")).to_contain_text("друг")
            self.assertEqual(errors, [])
        finally:
            context.close()

    def test_enter_sends_but_shift_enter_adds_newline(self):
        composer = self.page.locator("#msgrT")
        self.assertEqual(composer.evaluate("el => el.tagName"), "TEXTAREA")
        composer.fill("Первая строка")
        composer.press("Shift+Enter")
        composer.press("End")
        composer.type("Вторая строка")
        expect(composer).to_have_value("Первая строка\nВторая строка")
        composer.press("Enter")
        expect(composer).to_have_value("")
        expect(self.page.locator("#msgrMsgs .mm").last).to_contain_text("Вторая строка")
        self.assertIn("Первая строка\nВторая строка", self.page.locator("#msgrMsgs .mm").last.inner_text())

    def test_drafts_belong_to_their_conversation(self):
        self.open_chat(CHAT_ALICE)
        self.page.locator("#msgrT").fill("Черновик для Алисы")
        self.open_chat(CHAT_GROUP)
        expect(self.page.locator("#msgrT")).to_have_value("")
        self.page.locator("#msgrT").fill("Черновик для группы")
        self.open_chat(CHAT_ALICE)
        expect(self.page.locator("#msgrT")).to_have_value("Черновик для Алисы")
        self.open_chat(CHAT_GROUP)
        expect(self.page.locator("#msgrT")).to_have_value("Черновик для группы")

    def test_mobile_realtime_does_not_leave_chat_list(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        if self.page.locator(".msgr-side").is_hidden():
            self.page.locator("#convBack").click()
        self.open_chat(CHAT_ALICE)
        expect(self.page.locator("#msgrMsgs")).to_contain_text("Личное сообщение Алисы")
        self.page.locator("#convBack").click()
        expect(self.page.locator(".msgr-side")).to_be_visible()
        self.page.evaluate("__mock.emit('messages', {conversation_id: '" + CHAT_ALICE + "'})")
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        expect(self.page.locator(".msgr-side")).to_be_visible()
        expect(self.page.locator(".msgr-main")).to_be_hidden()

    def test_realtime_does_not_scroll_reader_to_bottom(self):
        box = self.page.locator("#msgrMsgs")
        expect(self.page.locator("#msgrMsgs .mm")).to_have_count(100)
        box.evaluate("el => el.scrollTop = 120")
        original = box.evaluate("el => el.scrollTop")
        self.assertGreater(original, 0)
        self.page.evaluate("__mock.tables.chat.push({id: 106, name: 'Алиса', text: 'Новое сообщение', ts: 1792409999999}); __mock.emit('chat')")
        expect(self.page.locator("#msgrMsgs .mm").last).to_contain_text("Новое сообщение")
        self.assertAlmostEqual(box.evaluate("el => el.scrollTop"), original, delta=3)

    def test_new_group_uses_atomic_creation_rpc(self):
        self.page.locator("#newGrp").click()
        self.page.locator("#grpT").fill("Воскресный завтрак")
        self.page.locator('#pickGrpList input[value="alice@example.invalid"]').check()
        self.page.locator('#pickGrpF button[type="submit"]').click()
        expect(self.page.locator("#convTitle")).to_have_text("Воскресный завтрак")
        calls = self.page.evaluate("__mock.calls.filter(call => call.rpc)")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["rpc"], "create_conversation")
        self.assertEqual(calls[0]["args"]["p_kind"], "group")
        self.assertEqual(calls[0]["args"]["p_title"], "Воскресный завтрак")
        self.assertEqual(calls[0]["args"]["p_emails"], ["alice@example.invalid"])
        self.assertFalse(self.page.evaluate("__mock.calls.some(call => ['conversations', 'conversation_members'].includes(call.table) && call.op === 'insert')"))

    def test_existing_and_new_dm_use_atomic_rpc_without_duplicate(self):
        for email, name in [("alice@example.invalid", "Алиса"), ("bob@example.invalid", "Борис")]:
            with self.subTest(email=email):
                self.page.locator("#newDm").click()
                self.page.locator(f'#pickDmList button[data-em="{email}"]').click()
                expect(self.page.locator("#pickDm")).to_be_hidden()
                expect(self.page.locator("#convTitle")).to_have_text(name)
        calls = self.page.evaluate("__mock.calls.filter(call => call.rpc)")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call["rpc"] == "create_conversation" and call["args"]["p_kind"] == "dm" for call in calls))
        self.assertEqual([call["args"]["p_emails"] for call in calls], [["alice@example.invalid"], ["bob@example.invalid"]])
        self.assertEqual(self.page.evaluate("__mock.tables.conversations.filter(row => row.kind === 'dm').length"), 2)
        self.assertFalse(self.page.evaluate("__mock.calls.some(call => ['conversations', 'conversation_members'].includes(call.table) && call.op === 'insert')"))

    def test_missing_rpc_keeps_dm_picker_and_does_not_fallback_to_inserts(self):
        self.page.evaluate("__mock.rpcFailure = true")
        self.page.locator("#newDm").click()
        self.page.locator('#pickDmList button[data-em="bob@example.invalid"]').click()
        expect(self.page.locator("#pickDm")).to_be_visible()
        expect(self.page.locator("#toast")).to_contain_text("Не получилось открыть диалог")
        expect(self.page.locator('#pickDmList button[data-em="bob@example.invalid"]')).to_be_enabled()
        self.assertEqual(self.page.evaluate("__mock.tables.conversations.filter(row => row.kind === 'dm').length"), 1)
        self.assertFalse(self.page.evaluate("__mock.calls.some(call => ['conversations', 'conversation_members'].includes(call.table) && call.op === 'insert')"))

    def test_cdn_unavailable_keeps_demo_messenger_working(self):
        context = self.browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        try:
            context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.base_url) else route.abort())
            page = context.new_page()
            page.goto(self.base_url, wait_until="load")
            expect(page.locator("#note")).to_contain_text("Демо-режим")
            self.open_section("chat", page)
            page.locator("#msgrT").fill("Локальная проверка")
            page.locator("#msgrT").press("Enter")
            expect(page.locator("#msgrMsgs")).to_contain_text("Локальная проверка")
            page.locator("#stkBtn").click()
            expect(page.locator("#stkPanel [data-stk]")).to_have_count(27)
            page.locator('#stkPanel [data-stk="kazar"]').click()
            expect(page.locator("#msgrMsgs .stk-chr-w svg")).to_have_count(1)
        finally:
            context.close()


class DemoAccessTests(_BrowserCase):
    """Code 123 selects a local demo; it must never grant club-data access."""

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        self.context.set_default_timeout(5000)
        self.context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.base_url) else route.abort())
        self.context.add_init_script(NO_SESSION_MOCK)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.base_url, wait_until="load")
        expect(self.page.locator("#load")).to_be_hidden()
        expect(self.page.locator("#gate")).to_be_visible()

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "Unexpected JavaScript exception during demo access")

    def enter_demo(self):
        self.page.locator("#demoCode").fill("123")
        self.page.locator("#demoCode").press("Enter")
        expect(self.page.locator("#gate")).to_be_hidden()
        expect(self.page.locator("#user")).to_contain_text("Демо")

    def assert_no_backend_writes(self):
        self.assertFalse(self.page.evaluate("__mock.calls.some(call => ['insert', 'delete', 'update'].includes(call.op) || call.rpc)"))

    def test_wrong_code_stays_at_gate_without_backend_writes(self):
        self.page.locator("#demoCode").fill("000")
        self.page.locator('#demoForm button[type="submit"]').click()
        expect(self.page.locator("#gate")).to_be_visible()
        expect(self.page.locator("#demoMsg")).not_to_be_empty()
        expect(self.page.locator("#demoMsg")).to_have_attribute("role", "status")
        expect(self.page.locator("#demoCode")).to_have_value("000")
        expect(self.page.locator("#demoCode")).to_have_attribute("aria-invalid", "true")
        expect(self.page.locator("#gtForm")).to_be_visible()
        self.assert_no_backend_writes()

    def test_correct_demo_code_enters_on_mouse_click(self):
        self.page.locator("#demoCode").fill("123")
        self.page.locator('#demoForm button[type="submit"]').click()
        expect(self.page.locator("#gate")).to_be_hidden()
        expect(self.page.locator("#user")).to_contain_text("Демо")
        expect(self.page.locator("#note")).to_contain_text("Демо-режим")
        self.assert_no_backend_writes()

    def test_empty_demo_code_click_reports_error_instead_of_appearing_inert(self):
        expect(self.page.locator("#demoCode")).to_have_value("")
        self.page.locator('#demoForm button[type="submit"]').click()
        expect(self.page.locator("#demoMsg")).not_to_be_empty()
        expect(self.page.locator("#demoCode")).to_have_attribute("aria-invalid", "true")
        expect(self.page.locator("#gate")).to_be_visible()
        self.assert_no_backend_writes()

    def test_error_feedback_clears_when_demo_code_is_edited(self):
        self.page.locator("#demoCode").fill("000")
        self.page.locator('#demoForm button[type="submit"]').click()
        expect(self.page.locator("#demoMsg")).not_to_be_empty()
        self.page.locator("#demoCode").fill("1")
        expect(self.page.locator("#demoMsg")).to_be_empty()
        expect(self.page.locator("#demoCode")).not_to_have_attribute("aria-invalid", "true")
        expect(self.page.locator("#gate")).to_be_visible()
        self.assert_no_backend_writes()

    def test_correct_demo_code_enters_on_mobile_touch_tap(self):
        context = self.browser.new_context(
            viewport={"width": 375, "height": 667},
            is_mobile=True,
            has_touch=True,
            device_scale_factor=2,
            reduced_motion="no-preference",
        )
        errors = []
        try:
            context.set_default_timeout(5000)
            context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.base_url) else route.abort())
            context.add_init_script(NO_SESSION_MOCK)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.base_url, wait_until="load")
            expect(page.locator("#load")).to_be_hidden()
            expect(page.locator("#gate")).to_be_visible()
            page.locator("#demoCode").fill("123")
            page.locator('#demoForm button[type="submit"]').tap()
            expect(page.locator("#gate")).to_be_hidden()
            expect(page.locator("#user")).to_contain_text("Демо")
            self.assertFalse(page.evaluate("__mock.calls.some(call => ['insert', 'delete', 'update'].includes(call.op) || call.rpc)"))
            self.assertEqual(errors, [])
        finally:
            context.close()

    def test_123_enters_only_local_chat_and_stickers(self):
        self.enter_demo()
        self.open_section("chat")
        expect(self.page.locator("#note")).to_contain_text("Демо-режим")
        expect(self.page.locator("#msgrMsgs")).not_to_contain_text("Общий 105")
        self.page.locator("#msgrT").fill("Сообщение только в демо")
        self.page.locator("#msgrT").press("Enter")
        expect(self.page.locator("#msgrMsgs")).to_contain_text("Сообщение только в демо")
        self.page.locator("#stkBtn").click()
        expect(self.page.locator("#stkPanel [data-stk]")).to_have_count(27)
        self.page.locator('#stkPanel [data-stk="kazar"]').click()
        expect(self.page.locator("#msgrMsgs .stk-chr-w svg")).to_have_count(1)
        self.assertEqual(self.page.evaluate("__mock.tables.chat.length"), 105)
        self.assert_no_backend_writes()

    def test_demo_exit_returns_to_gate(self):
        self.enter_demo()
        self.page.locator("#out").click()
        self.page.wait_for_load_state("load")
        expect(self.page.locator("#gate")).to_be_visible()
        expect(self.page.locator("#demoCode")).to_have_value("")
        expect(self.page.locator("#gtForm")).to_be_visible()
        self.assert_no_backend_writes()

    def test_refresh_does_not_keep_demo_access(self):
        self.enter_demo()
        self.open_section("chat")
        self.page.locator("#msgrT").fill("Этот черновик не открывает клуб")
        self.page.reload(wait_until="load")
        expect(self.page.locator("#gate")).to_be_visible()
        expect(self.page.locator("#demoCode")).to_have_value("")
        self.assert_no_backend_writes()

    def test_late_auth_and_queued_realtime_do_not_replace_demo(self):
        self.page.evaluate("__mock.pendingAuth = __mock.authListeners.slice(); __mock.pendingRealtime = __mock.listeners.slice()")
        self.enter_demo()
        self.open_section("chat")
        self.page.locator("#msgrT").fill("Личный локальный черновик")
        count = self.page.evaluate("__mock.calls.length")
        self.page.evaluate("""() => {
          const session = {user: {email: 'tester@example.invalid'}};
          __mock.emitAuth(session);
          __mock.pendingAuth.forEach(callback => callback('SIGNED_IN', session));
          __mock.pendingRealtime.forEach(item => item.callback({eventType: 'INSERT', new: {conversation_id: 'all'}, old: {}}));
        }""")
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        expect(self.page.locator("#gate")).to_be_hidden()
        expect(self.page.locator("#user")).to_contain_text("Демо")
        expect(self.page.locator("#msgrT")).to_have_value("Личный локальный черновик")
        expect(self.page.locator("#msgrMsgs")).not_to_contain_text("Общий 105")
        self.assertEqual(self.page.evaluate("__mock.calls.length"), count)
        self.assert_no_backend_writes()

    def test_inflight_club_event_read_cannot_repopulate_demo(self):
        self.page.evaluate("""() => {
          __mock.tables.events = [{id: 1, title: 'Закрытое клубное событие', date: '2026-11-01', place: 'Только участникам'}];
          __mock.holdNext('events');
          window.__pendingClubRead = loadEvents();
        }""")
        self.page.wait_for_function("__mock.holds[0].matched")
        self.enter_demo()
        self.page.evaluate("__mock.release(0)")
        self.page.evaluate("() => window.__pendingClubRead")
        expect(self.page.locator("#evList")).not_to_contain_text("Закрытое клубное событие")
        expect(self.page.locator("#homeAnnouncements")).not_to_contain_text("Закрытое клубное событие")
        expect(self.page.locator("#gate")).to_be_hidden()
        expect(self.page.locator("#user")).to_contain_text("Демо")
        self.assert_no_backend_writes()

    def test_inflight_club_roster_read_cannot_repopulate_demo(self):
        self.page.evaluate("""() => {
          __mock.holdNext('members');
          window.__pendingClubRead = membersMap();
        }""")
        self.page.wait_for_function("__mock.holds[0].matched")
        self.enter_demo()
        self.page.evaluate("__mock.release(0)")
        self.page.evaluate("() => window.__pendingClubRead")
        self.assertEqual(self.page.evaluate("msgr.mem.size"), 0, "A completed club read must not restore the private roster in demo")
        self.assertEqual(self.page.evaluate("msgr.charOf.size"), 0, "Demo must not retain club character-to-member mappings")
        self.open_section("chat")
        expect(self.page.locator("#convList .mv")).to_have_count(1)
        expect(self.page.locator("#newDm")).to_be_hidden()
        self.assert_no_backend_writes()

    def test_email_login_remains_available(self):
        expect(self.page.locator("#gtForm")).to_be_visible()
        email = self.page.locator("#gtE")
        expect(email).to_have_attribute("type", "email")
        email.fill("member@example.invalid")
        expect(email).to_have_value("member@example.invalid")
        expect(self.page.locator("#gtForm button")).to_be_enabled()
        expect(self.page.locator("#demoForm")).to_be_visible()
        self.assert_no_backend_writes()

    def test_scripts_only_chat_preview_supports_demo_and_local_forms(self):
        console_errors = []
        preview_page = self.context.new_page()
        preview_page.on("pageerror", lambda error: self.errors.append(str(error)))
        preview_page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        preview_page.set_content(
            f'<iframe id="restrictedPreview" sandbox="allow-scripts" src="{self.base_url}" style="width:100%;height:900px;border:0"></iframe>',
            wait_until="load",
        )
        frame = preview_page.locator("#restrictedPreview").element_handle().content_frame()
        self.assertIsNotNone(frame)
        expect(frame.locator("#load")).to_be_hidden()
        expect(frame.locator("#gate")).to_be_visible()
        frame.evaluate("""() => {
          window.__formProbe = {clicks: 0, submits: 0};
          document.querySelector('#demoForm').addEventListener('click', () => __formProbe.clicks++);
          document.querySelector('#demoForm').addEventListener('submit', () => __formProbe.submits++);
        }""")
        frame.locator("#demoCode").fill("123")
        frame.locator('#demoForm button[type="submit"]').click()
        try:
            expect(frame.locator("#gate")).to_be_hidden()
        except AssertionError:
            print("Restricted preview form events:", frame.evaluate("__formProbe"), "console:", console_errors, flush=True)
            raise
        self.assertEqual(frame.evaluate("__formProbe"), {"clicks": 1, "submits": 1}, "A click should invoke exactly one application submit handler")
        expect(frame.locator("#user")).to_contain_text("Демо")
        self.open_section("chat", frame)
        frame.locator("#msgrT").fill("Enter в предпросмотре")
        frame.locator("#msgrT").press("Enter")
        expect(frame.locator("#msgrMsgs")).to_contain_text("Enter в предпросмотре")
        frame.locator("#msgrT").fill("Кнопка в предпросмотре")
        frame.locator("#msgrSend").click()
        expect(frame.locator("#msgrMsgs")).to_contain_text("Кнопка в предпросмотре")
        expect(frame.locator("#msgrMsgs .mm")).to_have_count(2)
        self.open_section("events", frame)
        frame.locator("#evForm button").click()
        expect(frame.locator("#evList h3")).to_have_count(0)
        frame.locator("#evT").fill("Событие в предпросмотре")
        frame.locator("#evD").fill("2026-11-01")
        frame.locator("#evP").fill("Локально")
        frame.locator("#evForm button").click()
        expect(frame.locator("#evList h3")).to_have_text("Событие в предпросмотре")
        expect(frame.locator("#homeAnnouncements")).to_contain_text("Событие в предпросмотре")
        self.open_section("help", frame)
        frame.locator("#hpT").fill("Помочь привезти стулья")
        frame.locator("#hpD").fill("Проверка помощи без подключения к клубу")
        frame.locator("#hpU").check()
        frame.locator("#hpForm button").click()
        expect(frame.locator("#hpList h3")).to_have_text("Помочь привезти стулья")
        expect(frame.locator("#hpList .urg")).to_have_count(1)
        response = frame.locator("#hpList .hbtn")
        expect(response).to_contain_text("Могу помочь")
        response.click()
        expect(response).to_contain_text("Ты откликнулся")
        expect(response).to_contain_text("1")
        response.click()
        expect(response).to_contain_text("Могу помочь")
        self.assertFalse(response.evaluate("button => button.classList.contains('on')"))
        frame.locator("#sectionWindowClose").click()
        home_request = frame.locator("#homeHelpList .home-help-card")
        expect(home_request).to_be_visible()
        expect(home_request).to_contain_text("Помочь привезти стулья")
        expect(home_request).to_contain_text("НУЖНО СРОЧНО")
        expect(frame.locator("#homeHelpCount")).to_have_attribute("aria-label", "Просьб: 1, срочных: 1")
        home_request.click()
        expect(frame.locator("#help")).to_be_visible()
        expect(frame.locator("#hpList h3")).to_have_text("Помочь привезти стулья")
        self.assertFalse(frame.evaluate("__mock.calls.some(call => ['insert', 'delete', 'update'].includes(call.op) || call.rpc)"))
        self.assertFalse(any("Blocked form submission" in error for error in console_errors), console_errors)

    def test_offline_export_runs_in_scripts_only_srcdoc_without_network(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("dearfriends_export_demo", root / "scripts" / "export_demo.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        document = module.export_demo((root / "index.html").read_text(encoding="utf-8"))
        context = self.browser.new_context(viewport={"width": 1000, "height": 1000}, reduced_motion="reduce")
        requested, errors, console_errors = [], [], []
        try:
            context.set_default_timeout(5000)
            context.route("**/*", lambda route: route.abort())
            context.on("request", lambda request: requested.append(request.url) if request.url.startswith(("http://", "https://", "ws://", "wss://")) else None)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page.set_content('<iframe id="offlinePreview" sandbox="allow-scripts" style="width:100%;height:900px;border:0"></iframe>')
            page.locator("#offlinePreview").evaluate("(element, document) => { element.srcdoc = document; }", document)
            frame = page.locator("#offlinePreview").element_handle().content_frame()
            self.assertIsNotNone(frame)
            expect(frame.locator("#load")).to_be_hidden()
            expect(frame.locator("#gate")).to_be_visible()
            expect(frame.locator("#gtForm")).to_be_hidden()
            expect(frame.locator("script[src]")).to_have_count(0)
            frame.locator("#demoCode").fill("123")
            frame.locator('#demoForm button[type="submit"]').click()
            expect(frame.locator("#gate")).to_be_hidden()
            expect(frame.locator("#user")).to_contain_text("Демо")
            self.open_section("chat", frame)
            frame.locator("#msgrT").fill("Офлайн через Enter")
            frame.locator("#msgrT").press("Enter")
            expect(frame.locator("#msgrMsgs")).to_contain_text("Офлайн через Enter")
            frame.locator("#msgrT").fill("Офлайн через кнопку")
            frame.locator("#msgrSend").click()
            expect(frame.locator("#msgrMsgs")).to_contain_text("Офлайн через кнопку")
            expect(frame.locator("#msgrMsgs .mm")).to_have_count(2)
            self.open_section("events", frame)
            frame.locator("#evT").fill("Офлайн-событие")
            frame.locator("#evD").fill("2026-11-01")
            frame.locator("#evP").fill("В предпросмотре")
            frame.locator("#evForm button").click()
            expect(frame.locator("#evList h3")).to_have_text("Офлайн-событие")
            self.assertEqual(requested, [], "The export must not attempt any network requests")
            self.assertEqual(errors, [])
            self.assertFalse(any("Blocked form submission" in error for error in console_errors), console_errors)
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
