#!/usr/bin/env python3
"""Export the authored 3D layout review as one offline HTML document."""
import argparse
import base64
import html
import io
import json
from pathlib import Path
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / 'rooms/club-room-3d'

    def picture(path, label):
        # Keep the source artwork intact; compress only the review-page copies.
        with Image.open(root / path) as source:
            preview = source.convert('RGB')
            preview.thumbnail((1400, 1000), Image.Resampling.LANCZOS)
            encoded = io.BytesIO()
            preview.save(encoded, format='JPEG', quality=83, optimize=True)
        data = base64.b64encode(encoded.getvalue()).decode('ascii')
        return f'<figure><img src="data:image/jpeg;base64,{data}" alt="{html.escape(label)}"><figcaption>{html.escape(label)}</figcaption></figure>'

    hero = picture('renders/material-direction-preview.png', 'Объёмная геометрия с пробными цветами; окончательные материалы и свет ещё впереди.')
    perspective = picture('renders/layout-perspective.png', 'Вид на объёмную планировку со снятыми для обзора стенами и потолком.')
    if (root / 'renders/actor-seating-preview.png').exists():
        perspective += picture('renders/actor-seating-preview.png', 'Рассадка наших исходных SVG 9 + 8. Это отдельная проба, не готовая анимация внутри 3D-сцены.')
    plans = picture('plans/floor-plan.png', 'План сверху: проекции настоящих моделей, включая входной холл.')
    plans += '<details><summary>Потолок и стены</summary>'
    for path, label in [('plans/reflected-ceiling.png', 'Отдельный план потолка'), ('plans/elevation-north.png', 'Задняя стена'), ('plans/elevation-west.png', 'Стена с входом'), ('plans/elevation-east.png', 'Правая стена'), ('plans/elevation-south.png', 'Передняя стена')]:
        plans += picture(path, label)
    plans += '</details>'
    furniture = ''.join(picture(f'images/{name}-reference.png', label) for name, label in [('table', 'Большой общий стол 10,8 × 2,4 м на высоте 78 см; пять опорных станций.'), ('cabinet', 'Один тип шкафа, два отдельных экземпляра: книги/игры и фильмы/сериалы.')])
    (root / 'images/props-contact-sheet.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Мебель для 3D-комнаты</title><style>body{font:16px system-ui;max-width:1100px;margin:auto;padding:20px}img{max-width:100%;max-height:550px;object-fit:contain}figure{margin:20px 0}</style>'+furniture, encoding='utf-8')
    document = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Dear Friends — макет 3D-комнаты</title>
<style>*{box-sizing:border-box}html{color-scheme:dark}body{margin:0;background:#0b0b12;color:#f4f2ff;font:16px/1.6 system-ui,sans-serif}main{max-width:1200px;margin:auto;padding:24px}h1{font-size:clamp(26px,5vw,44px);line-height:1.2}h2{margin-top:46px;font-size:25px}p,li,figcaption{color:#b6b2ca}a{color:#cabaff}nav{display:flex;gap:12px;flex-wrap:wrap}nav a{padding:9px 14px;border:1px solid #383144;border-radius:20px;text-decoration:none}figure{margin:20px 0;padding:12px;background:#15151f;border:1px solid #262636;border-radius:18px}figure img{display:block;width:100%;max-height:760px;object-fit:contain;border-radius:9px}figcaption{font-size:13px;margin:10px 3px 0}summary{cursor:pointer;padding:14px;border:1px solid #383144;border-radius:12px}.status{color:#39e1c3;font-size:13px}.furniture{display:grid;grid-template-columns:1fr 1fr;gap:14px}.furniture figure:first-child{grid-column:1/-1}.furniture img{height:330px}.furniture figure:first-child img{height:auto}small{color:#b6b2ca}@media(max-width:650px){main{padding:16px}.furniture{display:block}.furniture img{height:auto;max-height:480px}}</style>
<main><p class="status">Dear Friends · планировка на согласование</p><h1>Первый объёмный макет комнаты</h1><p>Это модели в Blender. Сейчас проверяем расположение мебели и обзор. Управление камерой на сайте, герои, материалы и окончательный свет относятся к следующим этапам.</p><nav><a href="#view">Общий вид</a><a href="#plan">План комнаты</a><a href="#furniture">Мебель</a></nav><section id="view"><h2>Общий вид</h2>HERO PERSPECTIVE</section><section id="plan"><h2>План комнаты</h2><p>Размер комнаты — 14,4 × 12 м, высота — 3,8 м. За общим столом 17 мест: девять с дальней стороны и восемь с ближней. Стол — 10,8 × 2,4 м, высота — 78 см; по торцам остаётся 1,8 м. Вход — 2,6 м.</p>PLANS<ul><li>Ноутбук на столе — чат.</li><li>Фотографии на стене — галерея.</li><li>Два отдельных шкафа — библиотека книг, фильмов, сериалов и игр.</li><li>Доска слева — анонсы и помощь. Остальные дела клуба остаются в меню.</li></ul></section><section id="furniture"><h2>Направление мебели</h2><p>Образцы задают вид мебели для дальнейшего моделирования. Это образцы, а не загруженные в комнату готовые модели.</p><div class="furniture">FURNITURE</div></section><details><summary>Проёмы и техническая проверка</summary>OPENINGS<p>В геометрии 40 364 треугольников. Камера вмещает всю зарезервированную область стола и всех стульев. Вход и три окна вырезаны в стенах. Планировка и образцы мебели ожидают подтверждения; финальная 3D-сцена ещё не экспортирована и не опубликована.</p></details></main></html>'''
    for marker, content in [('HERO', hero), ('PERSPECTIVE', perspective), ('PLANS', plans), ('FURNITURE', furniture), ('OPENINGS', picture('masks/opening-contact-sheet.png', 'Входной проём и три окна; белые области — вырезы.'))]:
        document = document.replace(marker, content)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding='utf-8')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
