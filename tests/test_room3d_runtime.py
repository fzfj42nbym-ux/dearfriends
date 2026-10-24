"""Real WebGL room, portable srcdoc, camera input and graceful GPU failures."""
from pathlib import Path
import io
import subprocess
import sys
import tempfile
import unittest

from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


class Room3DRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='df-room3d-')
        cls.file=Path(cls.temp.name)/'room.html'
        subprocess.run([sys.executable,'-B',str(ROOT/'scripts/export_room3d_runtime.py'),str(cls.file)],check=True,capture_output=True)
        cls.source=cls.file.read_text()
        cls.p=sync_playwright().start()
        cls.browser=cls.p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.p.stop();cls.temp.cleanup()

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        self.context.route('**/*',lambda r:r.abort())
        self.page=self.context.new_page();self.errors=[];self.requests=[]
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.on('request',lambda r:self.requests.append(r.url) if r.url.startswith(('http:','https:','ws:','wss:')) else None)

    def tearDown(self):
        self.context.close();self.assertEqual(self.errors,[]);self.assertEqual(self.requests,[])

    def load(self):
        self.page.set_content(self.source,wait_until='load')
        self.page.wait_for_function('window.dfRoom3D?.ready===true')

    def test_actual_webgl_has_geometry_and_stops_rendering_while_idle(self):
        self.load()
        stats=self.page.evaluate('dfRoom3D.stats')
        self.assertEqual(stats['seats'],17)
        self.assertGreater(stats['triangles'],1000)
        self.assertLess(stats['triangles'],120000)
        self.assertLess(stats['calls'],100)
        picture=Image.open(io.BytesIO(self.page.locator('canvas').screenshot())).convert('RGB')
        self.assertGreater(len(picture.getcolors(picture.width*picture.height)),30)
        self.page.wait_for_timeout(200)
        before=self.page.evaluate('dfRoom3D.state.frames')
        self.page.wait_for_timeout(200)
        self.assertEqual(before,self.page.evaluate('dfRoom3D.state.frames'))

    def test_camera_drag_zoom_keyboard_and_presets_change_real_camera(self):
        self.load();canvas=self.page.locator('canvas');box=canvas.bounding_box()
        before=self.page.evaluate('dfRoom3D.camera.position.toArray()')
        self.page.mouse.move(box['x']+box['width']*.5,box['y']+box['height']*.5)
        self.page.mouse.down();self.page.mouse.move(box['x']+box['width']*.65,box['y']+box['height']*.5,steps=8);self.page.mouse.up()
        self.assertNotEqual(before,self.page.evaluate('dfRoom3D.camera.position.toArray()'))
        before=self.page.evaluate('dfRoom3D.camera.position.toArray()');self.page.mouse.wheel(0,-150)
        self.page.wait_for_function('old=>JSON.stringify(dfRoom3D.camera.position.toArray())!==JSON.stringify(old)',arg=before)
        canvas.focus();before=self.page.evaluate('dfRoom3D.camera.position.toArray()');canvas.press('ArrowLeft')
        self.assertNotEqual(before,self.page.evaluate('dfRoom3D.camera.position.toArray()'))
        canvas.press('Home');self.assertEqual(self.page.evaluate('dfRoom3D.state.preset'),'overview')
        self.page.locator('#roomLight').click();self.assertFalse(self.page.evaluate('dfRoom3D.state.night'))

    def test_camera_presets_and_layout_fit_desktop_and_mobile(self):
        self.load()
        for width,height in [(1440,1000),(375,812),(320,568)]:
            self.page.set_viewport_size({'width':width,'height':height})
            for name in ['overview','top','inside','table','shelves','board']:
                self.page.locator(f'[data-camera="{name}"]').click()
                self.assertEqual(self.page.evaluate('dfRoom3D.state.preset'),name)
                self.assertTrue(self.page.evaluate('dfRoom3D.camera.position.toArray().every(Number.isFinite)'))
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth&&document.documentElement.scrollHeight<=innerHeight'))
            bounds=self.page.locator('canvas').bounding_box();self.assertLessEqual(bounds['x']+bounds['width'],width+1)

    def test_context_loss_disables_controls_and_retry_creates_a_working_context(self):
        self.load();self.page.locator('canvas').evaluate("n=>n.dispatchEvent(new Event('webglcontextlost',{cancelable:true}))")
        self.assertFalse(self.page.evaluate('dfRoom3D.ready'))
        expect(self.page.locator('#roomFallback')).to_be_visible()
        expect(self.page.locator('[data-camera="top"]')).to_be_disabled()
        self.page.locator('#roomRetry').click();self.page.wait_for_function('dfRoom3D.ready')
        expect(self.page.locator('#roomFallback')).to_be_hidden();expect(self.page.locator('canvas')).to_be_focused()

    def test_unavailable_webgl_shows_poster_and_explanation(self):
        self.page.evaluate("() => {const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){return String(type).startsWith('webgl')?null:original.call(this,type,...args)}}")
        self.page.set_content(self.source,wait_until='load')
        self.assertFalse(self.page.evaluate('dfRoom3D.ready'))
        expect(self.page.locator('#roomFallback')).to_be_visible()
        expect(self.page.locator('#roomStatus')).to_contain_text('недоступно')
        self.assertTrue(self.page.locator('.poster').evaluate('n=>n.complete&&n.naturalWidth>0'))

    def test_scripts_only_srcdoc_has_no_dependency_on_sibling_files(self):
        self.page.set_content('<iframe id="preview" sandbox="allow-scripts" style="width:100%;height:900px;border:0"></iframe>')
        self.page.locator('#preview').evaluate('(n,source)=>n.srcdoc=source',self.source)
        frame=self.page.locator('#preview').element_handle().content_frame()
        frame.wait_for_function('window.dfRoom3D?.ready===true')
        frame.locator('[data-camera="top"]').click()
        self.assertEqual(frame.evaluate('dfRoom3D.state.preset'),'top')
        self.assertEqual(frame.evaluate('document.baseURI'),'about:blank')

    def test_club_menu_opens_embedded_room_and_only_child_can_request_escape(self):
        sys.path.insert(0,str(ROOT/'scripts'))
        from export_demo import export_demo
        document=export_demo((ROOT/'index.html').read_text())
        self.page.set_content('<iframe id="app" sandbox="allow-scripts" style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe>')
        self.page.locator('#app').evaluate('(n,s)=>n.srcdoc=s',document)
        app=self.page.locator('#app').element_handle().content_frame()
        app.locator('#demoCode').fill('123');app.locator('#demoCode').press('Enter')
        app.wait_for_function("document.querySelector('#gate').hidden&&!document.documentElement.classList.contains('auth-open')")
        app.locator('#moreOpen').click();app.locator('#more [data-open-section="club-room"]').click()
        # The lazy iframe attaches asynchronously when its section becomes visible.
        room=app.frame_locator('#clubRoomFrame')
        expect(room.locator('#roomViewport')).to_have_attribute('data-state','ready')
        expect(room.locator('body')).to_have_attribute('data-embedded','true')
        app.evaluate("window.postMessage({type:'dearfriends-room3d-close'},'*')")
        expect(app.locator('#sectionWindow')).to_be_visible()
        room.locator('canvas').focus();room.locator('canvas').press('Escape')
        expect(app.locator('#sectionWindow')).to_be_hidden()
        expect(app.locator('#moreOpen')).to_be_focused()
