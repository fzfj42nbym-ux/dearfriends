"""Integrated club windows against offline demo and an isolated fake backend.

Run: python3 -B -m unittest discover -s tests -p 'test_club_features.py' -v
No production data, credentials, transfers, or external services are used.
"""

import base64
import importlib.util
from pathlib import Path
import re

from playwright.sync_api import expect

from test_messenger import MOCK_SUPABASE, _BrowserCase


TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
IMAGE_URL = "https://example.invalid/test-receipt.png"

# Extend this fixture only. Existing messenger and library fake SDKs retain
# their original behavior and their own tests remain independent.
CLUB_MOCK = MOCK_SUPABASE.replace(
    "    delete() { this.op = 'delete'; return this; }",
    "    update(value) { this.op = 'update'; this.values = [value]; return this; }\n"
    "    delete() { this.op = 'delete'; return this; }",
).replace(
    "      if (this.op === 'insert') {",
    """      if (this.op === 'update') {
        data = table.filter(row => this.matches(row));
        data.forEach(row => Object.assign(row, clone(this.values[0])));
      } else if (this.op === 'insert') {""",
).replace(
    "      const failureIndex = state.failures.findIndex(f => f.table === this.table && f.op === this.op);",
    """      const earlyHold=state.holds.find(h=>h.before&&!h.matched&&h.table===this.table&&h.op===this.op&&Object.entries(h.equals).every(([key,value])=>this.filters.some(f=>f.key===key&&f.value===value)));
      if(earlyHold){earlyHold.matched=true;await new Promise(resolve=>{earlyHold.resolve=resolve;});}
      const failureIndex = state.failures.findIndex(f => f.table === this.table && f.op === this.op);""",
).replace(
    "storage: {from() { return {async createSignedUrl() { return {data: null, error: null}; }}; }},",
    """storage: {from(bucket) { return {
      async upload(path, file) {
        state.storageCalls.push({op:'upload',bucket,path,name:file.name,size:file.size});
        if(state.uploadFailure){state.uploadFailure=false;return {data:null,error:{message:'Тест: загрузка прервана'}};}
        return {data:{path},error:null};
      },
      async remove(paths) {state.storageCalls.push({op:'remove',bucket,paths});return {data:[],error:null};},
      async createSignedUrl(path) {
        state.storageCalls.push({op:'sign',bucket,path});
        return {data:{signedUrl:'https://example.invalid/test-receipt.png'},error:null};
      }
    }; }},""",
) + r"""
__mock.storageCalls=[];
__mock.uploadFailure=false;
__mock.tables.members[0].birthday='1990-01-12';
__mock.tables.members[1].birthday='1991-03-14';
__mock.tables.members[2].birthday='1992-08-18';
Object.assign(__mock.tables, {
  fund:[{id:701,amount:'30.03',note:'Клубный взнос',by:'alice@example.invalid',ts:1792400000000}],
  receipts:[{id:801,amount:'100.00',note:'Продукты клуба',path:null,by:'alice@example.invalid',ts:1792400000000}],
  challenges:[{id:901,title:'Прочитать книгу',text:'Обсудим вместе',until:null,by:'alice@example.invalid',ts:'2026-10-19T10:00:00Z'}],
  challenge_join:[{challenge_id:901,email:'alice@example.invalid'}]
});
"""


class _ClubCase(_BrowserCase):
    def close(self):
        self.page.locator("#sectionWindowClose").click()
        expect(self.page.locator("#sectionWindow")).to_be_hidden()

    def go(self, section):
        if self.page.locator("#sectionWindow").is_visible():
            self.close()
        self.page.locator("#moreOpen").click()
        self.page.locator(f'#more [data-open-section="{section}"]').click()
        expect(self.page.locator("#" + section)).to_be_visible()

    def send(self, form):
        self.page.locator(f"#{form} button[type=submit]").click()

    def date_today_birthday(self):
        return self.page.evaluate("() => {const d=new Date();return '2000-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}")

    def date_today(self):
        return self.page.evaluate("() => {const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}")


class ClubDemoTests(_ClubCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("club_demo_export", root / "scripts/export_demo.py")
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)
        document = exporter.export_demo((root / "index.html").read_text(encoding="utf-8"))
        self.context = self.browser.new_context(
            viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True,
            reduced_motion="reduce", timezone_id="Europe/Moscow",
        )
        self.context.set_default_timeout(5000)
        self.errors, self.requests = [], []
        self.context.route("**/*", lambda route: route.abort())
        self.context.on("request", lambda request: self.requests.append(request.url)
                        if request.url.startswith(("http://", "https://", "ws://", "wss://")) else None)
        parent = self.context.new_page()
        parent.on("pageerror", lambda error: self.errors.append(str(error)))
        parent.set_content('<meta name="viewport" content="width=device-width,initial-scale=1">'
                           '<iframe id="preview" sandbox="allow-scripts" '
                           'style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe>')
        parent.locator("#preview").evaluate("(node,document) => {node.srcdoc=document}", document)
        self.parent_page = parent
        self.page = parent.locator("#preview").element_handle().content_frame()
        self.page.locator("#demoCode").fill("123")
        self.page.locator("#demoCode").press("Enter")
        self.page.wait_for_function("document.querySelector('#gate').hidden&&!document.documentElement.classList.contains('auth-open')")

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "Club demo must not raise JavaScript exceptions")
        self.assertEqual(self.requests, [], "Club demo must remain offline")

    def test_fund_addition_and_own_removal_survive_window_switching(self):
        self.go("fund")
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "150000")
        self.page.locator("#fdSum").fill("0")
        self.send("fdForm")
        expect(self.page.locator("#fundCount")).to_have_text("2")
        self.page.locator("#fdSum").fill("123.45")
        self.page.locator("#fdNote").fill("Тестовый взнос <b>без HTML</b>")
        self.send("fdForm")
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "162345")
        expect(self.page.locator("#fundCount")).to_have_text("3")
        expect(self.page.locator("#fundPeople")).to_have_text("3")
        own = self.page.locator('#fdList [data-kind="fund"]').filter(has_text="Тестовый взнос <b>без HTML</b>")
        expect(own).to_have_count(1)
        expect(own.locator("b").filter(has_text="без HTML")).to_have_count(0)
        expect(self.page.locator("#fdSum")).to_have_value("")
        self.go("receipts")
        self.go("fund")
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "162345")
        own.locator('[data-club-finance-action="delete-fund"]').click()
        expect(own).to_have_count(0)
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "150000")

    def test_receipt_photo_and_rounding_keep_every_kopeck_and_balances_sum_to_zero(self):
        self.go("receipts")
        expect(self.page.locator("#rcSettle")).to_have_attribute("data-total-cents", "90001")
        self.page.locator("#rcSum").fill("0.01")
        self.page.locator("#rcNote").fill("Одна копейка для проверки")
        self.page.locator("#rcFile").set_input_files({"name": "check.png", "mimeType": "image/png", "buffer": TINY_PNG})
        self.send("rcForm")
        row = self.page.locator('#rcList [data-kind="receipts"]').filter(has_text="Одна копейка для проверки")
        expect(row).to_have_count(1)
        image = row.locator("img")
        expect(image).to_be_visible()
        image.scroll_into_view_if_needed()
        self.assertTrue(image.evaluate("async node => {await node.decode();return node.naturalWidth>0}"))
        expect(self.page.locator("#rcSettle")).to_have_attribute("data-total-cents", "90002")
        balances = self.page.locator("[data-club-balance]").evaluate_all("nodes=>nodes.map(n=>({email:n.dataset.clubBalance,share:+n.dataset.shareCents,balance:+n.dataset.balanceCents}))")
        self.assertEqual(sum(row["share"] for row in balances), 90002)
        self.assertEqual(sum(row["balance"] for row in balances), 0)
        self.assertEqual({row["email"]: row["share"] for row in balances},
                         {"demo-alisa": 30001, "demo-guest": 30001, "demo-nikita": 30000})
        self.go("challenges")
        self.go("receipts")
        expect(row).to_have_count(1)
        row.locator('[data-club-finance-action="delete-receipt"]').click()
        expect(row).to_have_count(0)
        expect(self.page.locator("#rcSettle")).to_have_attribute("data-total-cents", "90001")

    def test_challenge_due_today_accepts_participation_then_own_delete(self):
        self.go("challenges")
        self.page.locator("#chT").fill("Прогулка сегодня")
        self.page.locator("#chD").fill("Дедлайн действует до конца дня")
        self.page.locator("#chU").fill(self.date_today())
        self.send("chForm")
        row = self.page.locator("#chList article[data-challenge-id]").filter(has_text="Прогулка сегодня")
        expect(row).to_have_count(1)
        join = row.locator('[data-club-social-action="join"]')
        expect(join).to_be_enabled()
        expect(join).to_have_attribute("aria-pressed", "false")
        join.click()
        expect(join).to_have_attribute("aria-pressed", "true")
        expect(row.locator(".club-join-count")).to_have_text("1")
        join.click()
        expect(join).to_have_attribute("aria-pressed", "false")
        expect(row.locator(".club-join-count")).to_have_text("0")
        row.locator('[data-club-social-action="delete"]').click()
        expect(row).to_have_count(0)

    def test_birthday_date_is_saved_locally_and_today_banner_updates(self):
        self.go("birthdays")
        initial = self.page.locator("#bdList [data-birthday-email]").count()
        value = self.date_today_birthday()
        self.page.locator("#bdDate").fill(value)
        self.send("bdForm")
        own = self.page.locator('#bdList [data-birthday-email="demo-guest"]')
        expect(own).to_be_visible()
        expect(self.page.locator("#bdList [data-birthday-email]")).to_have_count(initial + 1)
        expect(self.page.locator("#bdToday")).to_contain_text("Ты")
        self.go("fund")
        self.go("birthdays")
        expect(self.page.locator("#bdDate")).to_have_value(value)
        expect(own).to_be_visible()


class ClubBackendTests(_ClubCase):
    def setUp(self):
        self.errors = []
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000},
                                                reduced_motion="reduce", timezone_id="Europe/Moscow")
        self.context.set_default_timeout(5000)
        self.context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.base_url) else route.abort())
        self.context.route(IMAGE_URL, lambda route: route.fulfill(content_type="image/png", body=TINY_PNG))
        self.context.add_init_script(CLUB_MOCK)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.base_url, wait_until="load")
        self.page.wait_for_function("document.querySelector('#gate').hidden&&!document.documentElement.classList.contains('auth-open')")

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "Integrated club forms must not raise JavaScript exceptions")

    def test_failed_fund_save_keeps_draft_and_retry_updates_without_realtime(self):
        self.go("fund")
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "3003")
        self.page.evaluate("__mock.failNext('fund')")
        self.page.locator("#fdSum").fill("45.67")
        self.page.locator("#fdNote").fill("Сохрани черновик")
        self.send("fdForm")
        expect(self.page.locator("#fdStatus")).to_contain_text("Не")
        expect(self.page.locator("#fdSum")).to_have_value("45.67")
        expect(self.page.locator("#fdNote")).to_have_value("Сохрани черновик")
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "3003")
        self.send("fdForm")
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "7570")
        self.assertEqual(self.page.evaluate("__mock.tables.fund.filter(r=>r.note==='Сохрани черновик').length"), 1)

    def test_photo_upload_and_receipt_save_errors_preserve_fields_for_retry(self):
        self.go("receipts")
        self.page.locator("#rcSum").fill("10.02")
        self.page.locator("#rcNote").fill("Чек с повтором")
        self.page.locator("#rcFile").set_input_files({"name": "receipt.png", "mimeType": "image/png", "buffer": TINY_PNG})
        self.page.evaluate("__mock.uploadFailure=true")
        self.send("rcForm")
        expect(self.page.locator("#rcStatus")).to_contain_text("Не")
        expect(self.page.locator("#rcSum")).to_have_value("10.02")
        self.assertEqual(self.page.evaluate("__mock.calls.filter(c=>c.table==='receipts'&&c.op==='insert').length"), 0)
        self.page.evaluate("__mock.failNext('receipts')")
        self.send("rcForm")
        self.page.wait_for_function("__mock.calls.some(c=>c.table==='receipts'&&c.op==='insert')")
        expect(self.page.locator("#rcNote")).to_have_value("Чек с повтором")
        self.send("rcForm")
        row = self.page.locator('#rcList [data-kind="receipts"]').filter(has_text="Чек с повтором")
        expect(row).to_have_count(1)
        expect(self.page.locator("#rcSettle")).to_have_attribute("data-total-cents", "11002")
        self.assertEqual(self.page.evaluate("__mock.tables.receipts.filter(r=>r.note==='Чек с повтором').length"), 1)

    def test_birthday_update_failure_does_not_change_another_members_date(self):
        self.go("birthdays")
        before = self.page.evaluate("__mock.tables.members.map(r=>({email:r.email,birthday:r.birthday}))")
        self.page.evaluate("__mock.failNext('members','update')")
        self.page.locator("#bdDate").fill("2000-07-16")
        self.send("bdForm")
        expect(self.page.locator("#bdStatus")).to_contain_text("Не")
        expect(self.page.locator("#bdDate")).to_have_value("2000-07-16")
        self.assertEqual(self.page.evaluate("__mock.tables.members.map(r=>({email:r.email,birthday:r.birthday}))"), before)
        self.send("bdForm")
        self.page.wait_for_function("__mock.tables.members[0].birthday==='2000-07-16'")
        self.assertEqual(self.page.evaluate("__mock.tables.members[1].birthday"), "1991-03-14")
        self.assertEqual(self.page.evaluate("__mock.tables.members[2].birthday"), "1992-08-18")

    def test_failed_challenge_join_does_not_claim_participation(self):
        self.go("challenges")
        row = self.page.locator('#chList article[data-challenge-id="901"]')
        join = row.locator('[data-club-social-action="join"]')
        expect(join).to_have_attribute("aria-pressed", "false")
        expect(row.locator(".club-join-count")).to_have_text("1")
        self.page.evaluate("__mock.failNext('challenge_join')")
        join.click()
        expect(self.page.locator("#chStatus")).to_contain_text("Не")
        expect(join).to_have_attribute("aria-pressed", "false")
        expect(row.locator(".club-join-count")).to_have_text("1")
        join.click()
        expect(join).to_have_attribute("aria-pressed", "true")
        expect(row.locator(".club-join-count")).to_have_text("2")

    def test_totals_include_every_page_and_late_private_read_cannot_replace_demo(self):
        self.go("fund")
        self.page.evaluate("""() => {
          __mock.tables.fund=Array.from({length:1101},(_,i)=>({id:i+1,amount:'1.01',note:'Приватный взнос '+i,by:'alice@example.invalid',ts:i}));
          window.__allFundRead=clubFinance.load();
        }""")
        self.page.evaluate("() => window.__allFundRead")
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "111201")
        expect(self.page.locator("#fundCount")).to_have_text("1101")
        self.page.evaluate("() => {__mock.holdNext('fund');window.__pendingFundRead=clubFinance.load();}")
        self.page.wait_for_function("__mock.holds[0].matched")
        self.page.evaluate("showGate()")
        self.page.locator("#demoCode").fill("123")
        self.page.locator("#demoCode").press("Enter")
        self.page.wait_for_function("document.querySelector('#gate').hidden&&!document.documentElement.classList.contains('auth-open')")
        self.page.evaluate("__mock.release(0)")
        self.page.evaluate("() => window.__pendingFundRead")
        self.go("fund")
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "150000")
        expect(self.page.locator("#fdList")).not_to_contain_text("Приватный взнос")
        expect(self.page.locator("#fdForm button[type=submit]")).to_be_enabled()

    def test_failed_delete_after_realtime_rerender_can_be_retried(self):
        self.go("fund")
        self.page.locator("#fdSum").fill("7.01")
        self.page.locator("#fdNote").fill("Проверка повтора удаления")
        self.send("fdForm")
        row = self.page.locator('#fdList [data-kind="fund"]').filter(has_text="Проверка повтора удаления")
        expect(row).to_have_count(1)
        self.page.evaluate("() => {const i=__mock.holdNext('fund',{},'delete');__mock.holds[i].before=true;__mock.failNext('fund','delete');}")
        remove = row.locator('[data-club-finance-action="delete-fund"]')
        remove.click()
        self.page.wait_for_function("__mock.holds[0].matched")
        remove.evaluate("node=>{window.__removeBeforeRefresh=node}")
        self.page.evaluate("__mock.emit('fund')")
        self.page.wait_for_function("!window.__removeBeforeRefresh.isConnected")
        expect(remove).to_be_disabled()
        self.page.evaluate("__mock.release(0)")
        expect(self.page.locator("#fdStatus")).to_contain_text("Не")
        expect(row).to_have_count(1)
        expect(remove).to_be_enabled()
        remove.click()
        expect(row).to_have_count(0)
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "3003")

    def test_saved_fund_entry_with_failed_refresh_reports_both_states_without_duplicate(self):
        self.go("fund")
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "3003")
        self.page.locator("#fdSum").fill("2.02")
        self.page.locator("#fdNote").fill("Сохранено, обновление прервано")
        self.page.evaluate("__mock.failNext('fund','select')")
        self.send("fdForm")
        expect(self.page.locator("#fdStatus")).to_contain_text(re.compile(r"не.*(?:обнов|загруз)", re.I))
        expect(self.page.locator("#fdStatus")).to_contain_text(re.compile(r"записан|сохран", re.I))
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "3003")
        expect(self.page.locator("#fdSum")).to_have_value("")
        self.assertEqual(self.page.evaluate("__mock.tables.fund.filter(r=>r.note==='Сохранено, обновление прервано').length"), 1)
        self.page.locator('#fund [data-club-finance-action="refresh"]').click()
        expect(self.page.locator("#fundTotal")).to_have_attribute("data-cents", "3205")
        self.assertEqual(self.page.evaluate("__mock.calls.filter(c=>c.table==='fund'&&c.op==='insert').length"), 1)
