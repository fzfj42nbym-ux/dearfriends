#!/usr/bin/env python3
"""Build a self-contained procedural WebGL room; no GLB or club data export."""
import argparse
import base64
import io
import json
from pathlib import Path
from PIL import Image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    room=root/'rooms/club-room-3d'
    geometry=json.loads((room/'geometry-metadata.json').read_text())
    geometry={key:geometry[key] for key in ('objects','seats','cabinets','openings')}
    with Image.open(room/'renders/material-direction-preview.png') as im:
        buf=io.BytesIO();im.convert('RGB').save(buf,format='JPEG',quality=80,optimize=True)
    poster=base64.b64encode(buf.getvalue()).decode()
    css=(root/'assets/room/room3d-viewer.css').read_text()
    engine=(root/'assets/vendor/three/three.global.js').read_text()
    controls=(root/'assets/vendor/three/orbit.global.js').read_text()
    app=(root/'assets/room/room3d-viewer.js').read_text()
    def script(value):return value.replace('</script','<\\/script')
    buttons=''.join(f'<button type="button" data-camera="{key}" aria-pressed="false">{label}</button>' for key,label in [('overview','Общий вид'),('top','Сверху'),('inside','Изнутри'),('table','К столу'),('shelves','Полки'),('board','Доска')])
    document=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Dear Friends — 3D-комната</title><style>{css}</style></head><body><header><h1>Комната клуба</h1><p>Основа 3D-комнаты. Персонажи и подробные модели предметов будут добавляться отдельно.</p></header><main id="roomViewport" class="viewer" data-state="loading"><img class="poster" alt="Макет комнаты с общим столом и семнадцатью стульями" src="data:image/jpeg;base64,{poster}"><div id="roomFallback" class="fallback" hidden><p>В этом просмотрщике 3D недоступно. Макет комнаты сохранён.</p><button type="button" id="roomRetry">Повторить 3D</button></div></main><nav aria-label="Камера комнаты">{buttons}<button type="button" id="roomLight">Дневной свет</button></nav><footer><p id="roomStatus" role="status" aria-live="polite">Загружаем комнату…</p><p class="help">Поворот — перетаскивание. Масштаб — колёсико или два пальца. Клавиатура: стрелки, +/−, Home.</p></footer><script id="roomGeometry" type="application/json">{json.dumps(geometry,ensure_ascii=False).replace('<',chr(92)+'u003c')}</script><script>{script(engine)}</script><script>{script(controls)}</script><script>{script(app)}</script></body></html>'''
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(document)
    print(args.output.resolve())


if __name__=='__main__':main()
