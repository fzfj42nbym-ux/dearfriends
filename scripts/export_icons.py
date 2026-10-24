#!/usr/bin/env python3
"""Export the inline Dear Friends icon registry as portable, offline SVG assets.

    python3 -B scripts/export_icons.py
    python3 -B scripts/export_icons.py --zip /tmp/dearfriends-icons-kit.zip

The canonical source is the icon-defs SVG in index.html. Only generated files
listed in this export are written; other files in an existing kit are preserved.
"""

import argparse
from copy import deepcopy
from dataclasses import dataclass
import html
import io
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile


REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "index.html"
SVG_NS = "http://www.w3.org/2000/svg"
GENERATOR = "scripts/export_icons.py"
ZIP_MARKER = b"Dear Friends generated icon kit v1"
ID_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
CATEGORIES = {"section", "media", "action", "state"}
GEOMETRY = {"g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
ET.register_namespace("", SVG_NS)


@dataclass(frozen=True)
class Icon:
    key: str
    label: str
    category: str
    view_box: str
    symbol: ET.Element


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def read_registry(source):
    """Validate the one local sprite and return stable, sorted icon records."""
    sprites = re.findall(
        r'<svg\b(?=[^>]*\bclass="[^\"]*\bicon-defs\b[^\"]*")[^>]*>.*?</svg>',
        source, flags=re.DOTALL,
    )
    if len(sprites) != 1:
        raise ValueError("Expected exactly one inline SVG with class icon-defs")
    root = ET.fromstring(sprites[0])
    try:
        stroke_width = float(root.get("data-stroke-width", "1.8"))
    except ValueError as error:
        raise ValueError("The sprite stroke width must be a number") from error
    if not math.isfinite(stroke_width) or not 0 < stroke_width <= 8:
        raise ValueError("The sprite stroke width must be between 0 and 8")
    defaults = {
        "viewBox": "0 0 24 24", "fill": "none", "stroke": "currentColor",
        "strokeWidth": stroke_width, "strokeLinecap": "round", "strokeLinejoin": "round",
    }
    icons, seen = [], set()
    for symbol in root.iter(f"{{{SVG_NS}}}symbol"):
        symbol_id = symbol.get("id", "")
        key = symbol_id.removeprefix("dfi-")
        if not symbol_id.startswith("dfi-") or not ID_PATTERN.fullmatch(key):
            raise ValueError(f"Invalid icon symbol id: {symbol_id!r}")
        if key in seen:
            raise ValueError(f"Duplicate icon symbol: {symbol_id}")
        seen.add(key)
        label = symbol.get("data-label", "").strip()
        category = symbol.get("data-category", "")
        if not label or len(label) > 160:
            raise ValueError(f"Icon {key} needs a Russian data-label (1–160 characters)")
        if category not in CATEGORIES:
            raise ValueError(f"Icon {key} needs data-category: {', '.join(sorted(CATEGORIES))}")
        view_box = symbol.get("viewBox", "")
        try:
            values = [float(value) for value in view_box.split()]
        except ValueError as error:
            raise ValueError(f"Invalid viewBox for icon {key}") from error
        if len(values) != 4 or not all(math.isfinite(value) for value in values) or values[2] <= 0 or values[3] <= 0:
            raise ValueError(f"Invalid viewBox for icon {key}")
        if not len(symbol):
            raise ValueError(f"Icon {key} has no geometry")
        for node in symbol.iter():
            if node is symbol:
                continue
            if local_name(node.tag) not in GEOMETRY or not node.tag.startswith("{" + SVG_NS + "}"):
                raise ValueError(f"Unsupported element in {key}: {local_name(node.tag)}")
            if any(attribute.lower().startswith("on") or local_name(attribute) == "href" for attribute in node.attrib):
                raise ValueError(f"Icon {key} must contain only local SVG geometry")
        icons.append(Icon(key, label, category, view_box, symbol))
    if not icons:
        raise ValueError("The icon sprite contains no symbols")
    literal_refs = set(re.findall(r'href=[\"\']#dfi-([a-z][a-z0-9-]*)[\"\']', source))
    unknown = literal_refs - seen
    if unknown:
        raise ValueError("Unknown static icon references: " + ", ".join(sorted(unknown)))
    return sorted(icons, key=lambda icon: icon.key), defaults


def drawing_attributes(defaults):
    return {
        "fill": defaults["fill"], "stroke": defaults["stroke"],
        "stroke-width": str(defaults["strokeWidth"]),
        "stroke-linecap": defaults["strokeLinecap"], "stroke-linejoin": defaults["strokeLinejoin"],
    }


def svg_document(icon, defaults):
    root = ET.Element(f"{{{SVG_NS}}}svg", {
        "viewBox": icon.view_box, "width": "24", "height": "24", **drawing_attributes(defaults),
    })
    root.extend(deepcopy(list(icon.symbol)))
    return ET.tostring(root, encoding="unicode") + "\n"


def sprite_document(icons, defaults):
    root = ET.Element(f"{{{SVG_NS}}}svg")
    defs = ET.SubElement(root, f"{{{SVG_NS}}}defs")
    for icon in icons:
        symbol = ET.SubElement(defs, f"{{{SVG_NS}}}symbol", {
            "id": "dfi-" + icon.key, "viewBox": icon.view_box, **drawing_attributes(defaults),
        })
        symbol.extend(deepcopy(list(icon.symbol)))
    return ET.tostring(root, encoding="unicode") + "\n"


def catalog_document(icons, defaults):
    categories = {"section": "Разделы", "media": "Библиотека", "action": "Действия", "state": "Состояния"}
    cards = []
    for icon in icons:
        svg = svg_document(icon, defaults).strip().replace('<svg ', '<svg aria-hidden="true" focusable="false" ', 1)
        search_text = " ".join((icon.label, icon.key, categories[icon.category],
                                "фото изображения картинки снимки" if icon.key == "photo" else ""))
        cards.append(
            f'<article data-category="{icon.category}" data-search="{html.escape(search_text, quote=True)}"><div class="drawing">{svg}</div>'
            f'<h2>{html.escape(icon.label)}</h2><code>{icon.key}</code>'
            f'<small>{categories[icon.category]}</small></article>'
        )
    return """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>Иконки Dear Friends</title><style>
:root{color-scheme:light dark;--bg:#f6f4ff;--card:#fff;--fg:#14122b;--mut:#6a6786;--line:#e3e0f5;--accent:#7c5cff}
@media(prefers-color-scheme:dark){:root{--bg:#0b0b12;--card:#15151f;--fg:#f4f2ff;--mut:#9a98b3;--line:#262636}}
*{box-sizing:border-box}body{margin:0;padding:32px max(20px,5vw);background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
h1{font-size:clamp(26px,5vw,42px);margin:0}header>p{max-width:760px;color:var(--mut)}.controls{display:flex;flex-wrap:wrap;gap:12px;margin:26px 0 16px}
label{display:flex;flex:1 1 220px;flex-direction:column;gap:6px;font-size:12px;color:var(--mut)}select,input{width:100%;padding:12px;border:1px solid var(--line);border-radius:14px;background:var(--card);color:var(--fg);font:inherit;min-height:44px}
:is(select,input):focus-visible{outline:2px solid var(--accent);outline-offset:3px}.count{color:var(--mut);font-size:13px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:12px}
article{padding:20px;border:1px solid var(--line);border-radius:20px;background:var(--card);min-width:0}.drawing{color:var(--accent);margin-bottom:18px;min-height:42px}.drawing svg{width:36px;height:36px}
article h2{font-size:14px;margin:0 0 8px;overflow-wrap:anywhere}code{display:block;font-size:12px;overflow-wrap:anywhere}article small{display:block;margin-top:8px;color:var(--mut);font-size:11px}[hidden]{display:none!important}
.empty{padding:24px;border:1px dashed var(--line);border-radius:16px;color:var(--mut)}footer{margin:28px 0;color:var(--mut);font-size:12px}
</style></head><body><header><h1>◐ Иконки Dear Friends</h1><p>Общий набор для сайта и будущего приложения. Поиск работает без сети. Исходная сетка — 24 × 24; цвет и размер задаёт интерфейс.</p></header>
<div class="controls"><label>Найти иконку<input id="search" type="search" placeholder="Название или ключ: chat, фото…" autocomplete="off"></label><label>Группа<select id="category"><option value="all">Все иконки</option><option value="section">Разделы</option><option value="media">Библиотека</option><option value="action">Действия</option><option value="state">Состояния</option></select></label></div>
<p class="count" id="count" role="status" aria-live="polite"></p><main aria-label="Каталог иконок">""" + "\n".join(cards) + """</main><p class="empty" id="empty" hidden>Ничего не нашлось. Попробуй другое название.</p>
<footer>Стабильные ключи — в manifest.json. Этот каталог — набор компонентов, не готовое мобильное приложение.</footer><script>
const search=document.querySelector('#search'),category=document.querySelector('#category'),cards=[...document.querySelectorAll('main article')];
function filter(){const query=search.value.trim().toLocaleLowerCase('ru');let visible=0;cards.forEach(card=>{card.hidden=(category.value!=='all'&&card.dataset.category!==category.value)||(query&&!card.dataset.search.toLocaleLowerCase('ru').includes(query));if(!card.hidden)visible++});document.querySelector('#count').textContent='Показано: '+visible+' из '+cards.length;document.querySelector('#empty').hidden=visible>0}
search.addEventListener('input',filter);category.addEventListener('change',filter);filter();
</script></body></html>\n"""


def build_files(icons, defaults):
    files = {icon.key + ".svg": svg_document(icon, defaults) for icon in icons}
    manifest = {
        "schema_version": 1, "generated_by": GENERATOR,
        "source": {"file": "index.html", "selector": "svg.icon-defs"},
        "defaults": defaults,
        "icons": [{"id": icon.key, "label_ru": icon.label, "category": icon.category,
                   "symbol_id": "dfi-" + icon.key, "file": icon.key + ".svg", "viewBox": icon.view_box}
                  for icon in icons],
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    files["sprite.svg"] = sprite_document(icons, defaults)
    files["preview.html"] = catalog_document(icons, defaults)
    return files


def validate_output(output, files):
    blocked = {REPO, REPO / "assets", REPO / "scripts", REPO / "docs", *REPO.parents}
    if output in blocked or output == SOURCE:
        raise ValueError("Choose a dedicated icon-kit output directory")
    previous_files = set()
    if output.exists():
        if not output.is_dir():
            raise ValueError("The output path must be a directory")
        if any(output.iterdir()):
            try:
                manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ValueError("Refusing to write into a nonempty directory without this export's manifest") from error
            if not isinstance(manifest, dict) or manifest.get("generated_by") != GENERATOR:
                raise ValueError("The existing output directory is not owned by this exporter")
            previous_files = {"manifest.json", "sprite.svg", "preview.html"}
            previous_icons = manifest.get("icons", [])
            if not isinstance(previous_icons, list) or any(not isinstance(icon, dict) for icon in previous_icons):
                raise ValueError("The existing icon manifest has an invalid icons list")
            for icon in previous_icons:
                name = icon.get("file", "")
                if isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9-]*\.svg", name):
                    previous_files.add(name)
    for name in files:
        target = output / name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(f"Refusing to replace a non-regular generated file: {target}")
        if target.exists() and name not in previous_files:
            raise ValueError(f"Refusing to replace an unrelated file: {target}")


def write_zip(path, files):
    if path.suffix.lower() != ".zip" or path.is_symlink() or path == SOURCE:
        raise ValueError("Choose a regular .zip output path")
    if path.exists():
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.comment != ZIP_MARKER:
                    raise ValueError("Refusing to overwrite a ZIP not created by this exporter")
        except (OSError, zipfile.BadZipFile) as error:
            raise ValueError("The existing ZIP is not a generated icon kit") from error
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.comment = ZIP_MARKER
        for name in sorted(files):
            info = zipfile.ZipInfo("dearfriends-icons/" + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name].encode("utf-8"), compresslevel=9)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REPO / "assets" / "icons")
    parser.add_argument("--zip", dest="zip_path", type=Path)
    args = parser.parse_args()
    try:
        icons, defaults = read_registry(SOURCE.read_text(encoding="utf-8"))
        files = build_files(icons, defaults)
        output = args.output_dir.expanduser().resolve()
        validate_output(output, files)
        if args.zip_path:
            archive = args.zip_path.expanduser().absolute()
            if archive.resolve() in {output / name for name in files}:
                raise ValueError("The ZIP path must not replace a generated asset")
            # Validate/write the optional archive before changing the asset kit.
            write_zip(archive, files)
        output.mkdir(parents=True, exist_ok=True)
        for name, contents in files.items():
            (output / name).write_text(contents, encoding="utf-8")
    except (OSError, ValueError, ET.ParseError) as error:
        parser.exit(1, f"Icon export failed: {error}\n")
    print(f"Exported {len(icons)} icons: {output}")
    if args.zip_path:
        print(f"Portable kit: {archive}")


if __name__ == "__main__":
    main()
