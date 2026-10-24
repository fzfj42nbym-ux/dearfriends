"""Offline motion preview: preserved artwork, looping, controls and accessibility."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from test_messenger import _BrowserCase

ROOT = Path(__file__).resolve().parents[1]


class TableMotionTests(_BrowserCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.artifacts = tempfile.TemporaryDirectory(prefix='df-table-motion-')
        cls.preview = Path(cls.artifacts.name) / 'preview.html'
        subprocess.run([sys.executable, '-B', str(ROOT/'scripts/export_table_seating_preview.py'), str(cls.preview)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.artifacts.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width':1440,'height':1000}, reduced_motion='no-preference')
        self.context.route('**/*', lambda route: route.abort())
        self.page = self.context.new_page()
        self.errors, self.requests = [], []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('request', lambda request: self.requests.append(request.url) if request.url.startswith(('http:', 'https:')) else None)
        self.page.set_content(self.preview.read_text(), wait_until='load')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.requests, [])

    def test_all_identities_seating_and_original_shapes_are_preserved(self):
        actors = json.loads((ROOT/'rooms/club-room-3d/animation/actors.json').read_text())
        self.assertEqual(self.page.locator('.actor').count(),17)
        self.assertEqual(self.page.locator('.far').count(),9)
        self.assertEqual(self.page.locator('.near').count(),8)
        self.assertEqual(self.page.locator('.table-arm').count(),3)
        self.assertEqual(self.page.locator('.table-call').count(),1)
        def artwork(svg):
            return [(node.tag.split('}')[-1], dict(node.attrib), node.text or '') for node in ET.fromstring(svg).iter() if node.tag.split('}')[-1] not in ('g','svg')]
        for actor in actors:
            actual = self.page.locator(f'[data-actor="{actor["id"]}"] .portrait>svg').evaluate('node=>node.outerHTML')
            self.assertEqual(artwork(actor['svg']),artwork(actual),actor['id'])

    def test_loop_repeats_and_pause_restart_keep_the_clock_still(self):
        self.page.locator('#pause').click()
        state = self.page.evaluate('''async()=>{
          const animations=document.getAnimations();
          const sample=async time=>{animations.forEach(a=>a.currentTime=time);await new Promise(r=>requestAnimationFrame(r));return [...document.querySelectorAll('.portrait>.bob,.portrait>svg,.bob,.table-arm,.reaction,.eye')].map(n=>[getComputedStyle(n).transform,getComputedStyle(n).opacity])};
          return {durations:animations.map(a=>a.effect.getTiming().duration),first:await sample(2200),second:await sample(14200),paused:animations.every(a=>a.playState==='paused')};
        }''')
        self.assertTrue(state['durations'])
        self.assertTrue(all(value==12000 for value in state['durations']))
        self.assertEqual(state['first'],state['second'])
        self.assertTrue(state['paused'])
        self.page.locator('#restart').click()
        self.assertTrue(self.page.evaluate('document.getAnimations().every(a=>a.currentTime===0&&a.playState==="paused")'))

    def test_manual_reaction_is_keyboard_accessible_and_calm_mode_can_hide_automatic_reactions(self):
        self.page.locator('#quiet').click()
        button=self.page.locator('[data-actor="kazar"] .portrait')
        button.focus();button.press('Enter')
        self.assertIn('Казар',self.page.locator('#motionStatus').inner_text())
        self.assertEqual(self.page.locator('[data-actor="kazar"] .reaction').evaluate('n=>getComputedStyle(n).opacity'),'1')
        self.page.locator('#restart').click()
        self.assertEqual(self.page.locator('.manual').count(),0)
        self.assertEqual(self.page.locator('[data-actor="kazar"] .reaction').evaluate('n=>getComputedStyle(n).opacity'),'0')

    def test_reduced_motion_and_mobile_pan_have_no_document_overflow(self):
        self.page.emulate_media(reduced_motion='reduce')
        self.assertEqual(self.page.locator('.portrait>svg').first.evaluate('n=>getComputedStyle(n).animationName'),'none')
        self.assertEqual(self.page.locator('.bob').first.evaluate('n=>getComputedStyle(n).animationName'),'none')
        for width in (320,375,768):
            self.page.set_viewport_size({'width':width,'height':812})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            self.assertTrue(self.page.locator('.pan').evaluate('n=>n.scrollWidth>n.clientWidth'))
