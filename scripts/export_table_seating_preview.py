#!/usr/bin/env python3
"""Preview the existing, unmodified SVG characters around the shared table."""
import argparse
import base64
import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from playwright.sync_api import sync_playwright
from export_demo import export_demo


# Contiguous existing shapes only: sleeves, hands and held props move together.
ARM_RIGS = {
    'kazar': (13, 15, 'M140 168', '140px 168px', '-14deg'),
    'nikita': (10, 13, 'M46 198', '46px 198px', '6deg'),
    'marina': (19, 22, 'M66 168', '66px 168px', '5deg'),
}


def rig_svg(actor):
    tree = ET.fromstring(actor['svg'])
    if actor['id'] in ARM_RIGS:
        start, end, expected, pivot, angle = ARM_RIGS[actor['id']]
        children = list(tree)
        assert children[start].get('d', '').startswith(expected), 'Artwork changed: review the arm rig'
        group = ET.Element('g', {'class': 'table-arm', 'data-rig': 'arm',
                                 'style': f'--pivot:{pivot};--gesture:{angle}'})
        tree.insert(start, group)
        for child in children[start:end]:
            tree.remove(child)
            group.append(child)
    if actor['id'] == 'artemiy':
        group = next(node for node in tree.iter() if node.get('class') == 'call')
        group.set('class', 'call table-call')
        group.set('data-rig', 'phone-arm')
    return ET.tostring(tree, encoding='unicode')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    package = root / 'rooms/club-room-3d'
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        page = browser.new_page()
        page.route('**/*', lambda route: route.abort())
        page.set_content(export_demo((root / 'index.html').read_text()), wait_until='load')
        page.wait_for_function("document.querySelectorAll('[data-seat][data-char] svg').length===17")
        actors = page.locator('[data-seat][data-char]').evaluate_all("nodes=>nodes.map(n=>({id:n.dataset.char,name:n.querySelector('svg').getAttribute('aria-label')||n.dataset.char,svg:n.querySelector('svg').outerHTML}))")
        browser.close()
    assert len(actors) == 17 and len({a['id'] for a in actors}) == 17
    (package / 'animation').mkdir(exist_ok=True)
    (package / 'animation/actors.json').write_text(json.dumps(actors, ensure_ascii=False, indent=2)+'\n')
    figures = []
    reactions = [('chat', 'Хорошая идея!'), ('heart', 'Поддерживаю'), ('check', 'Согласен'), ('star', 'Класс!')]
    for index, actor in enumerate(actors):
        row = 'far' if index < 9 else 'near'
        local = index if index < 9 else index-9
        count = 9 if row == 'far' else 8
        x = .5+(local-(count-1)/2)*1.2/16
        y = .31 if row == 'far' else .69
        icon, reaction = reactions[index % len(reactions)]
        name = html.escape(actor['name'], quote=True)
        figures.append(f'<figure class="actor {row}" data-actor="{actor["id"]}" data-name="{name}" data-reaction="{reaction}" style="left:{x*100:.3f}%;top:{y*100:.3f}%;--delay:-{index*12/17:.5f}s;--look:{2 if index%2==0 else -2}deg"><button class="portrait" type="button" aria-label="{name}: показать реакцию">{rig_svg(actor)}</button><figcaption>{name}</figcaption><span class="reaction" aria-hidden="true"><svg viewBox="0 0 24 24"><use href="#dfi-{icon}"></use></svg>{reaction}</span></figure>')
    source_app = (root / 'index.html').read_text()
    symbols = ''.join(re.search(rf'<symbol id="dfi-{name}".*?</symbol>', source_app, re.S)[0] for name in ['chat','heart','check','star'])
    icons = '<svg aria-hidden="true" style="position:absolute;width:0;height:0;overflow:hidden"><defs>'+symbols+'</defs></svg>'
    css = (root / 'assets/room/table-motion.css').read_text()
    script = (root / 'assets/room/table-motion.js').read_text()
    image = base64.b64encode((package/'renders/animation-top.png').read_bytes()).decode()
    source = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Dear Friends — рассадка за столом</title>
<style>STYLE</style>
ICONS<header><h1>Посиделки за общим столом</h1><p>Наши 17 героев, рассадка 9 + 8. Демонстрационный цикл — 12 секунд: наклоны головы, моргание, несколько жестов и постановочные реакции. Это отдельная SVG-проба; вид строго сверху и перенос в 3D ещё впереди.</p><div class="controls"><button id="pause" aria-pressed="false">Пауза</button><button id="restart">Сначала</button><button id="quiet" aria-pressed="false">Спокойный режим</button></div><p id="motionStatus" class="motion-status" role="status" aria-live="polite">Нажми на героя, чтобы показать его пробную реакцию.</p><p>На телефоне сцену можно листать по горизонтали.</p></header><div class="pan"><main class="stage"><img alt="Общий стол и 17 стульев — вид сверху" src="data:image/png;base64,IMAGE">FIGURES</main></div>
<script>SCRIPT</script></html>'''
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source.replace('IMAGE', image).replace('FIGURES', ''.join(figures)).replace('ICONS', icons).replace('STYLE', css).replace('SCRIPT', script))
    print(args.output.resolve())


if __name__ == '__main__':
    main()
