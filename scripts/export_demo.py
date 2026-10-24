#!/usr/bin/env python3
"""Export an offline demo for a chat preview, without external dependencies.

Usage: python3 scripts/export_demo.py /tmp/dearfriends-demo.html
Refresh embedded room artwork: python3 scripts/export_demo.py --refresh-room-assets
The export keeps the app's inline artwork and UI, disables the real backend,
and opens the local demo after code 123. The original index.html is unchanged.
"""
import argparse
import base64
from pathlib import Path
import re


def embed_room_assets(source: str) -> str:
    """Keep the main page portable while retaining editable WebP originals."""
    root = Path(__file__).resolve().parents[1] / 'assets' / 'room'
    patterns = {
        'room-background.webp': r'(<img\b(?=[^>]*\bdata-room-asset="room-background\.webp")[^>]*\bsrc=")[^"]*(")',
        'table-foreground.webp': r'(<img\b(?=[^>]*\bdata-room-asset="table-foreground\.webp")[^>]*\bsrc=")[^"]*(")',
    }
    for filename, pattern in patterns.items():
        encoded = base64.b64encode((root / filename).read_bytes()).decode('ascii')
        url = f'data:image/webp;base64,{encoded}'
        source, count = re.subn(pattern, lambda match: match[1] + url + match[2], source)
        if count != 1:
            raise ValueError(f'Expected exactly one room asset slot: {filename}')
    return source


def export_demo(source: str) -> str:
    if source.count('<html lang="ru">') != 1:
        raise ValueError('Expected the Russian HTML document root')
    source = embed_room_assets(source)
    source = source.replace('<html lang="ru">', '<html lang="ru" data-demo-preview>', 1)
    source = re.sub(r'<script\b[^>]*\bsrc="https://cdn\.jsdelivr\.net/[^\"]+"[^>]*>\s*</script>\s*', '', source)
    source = re.sub(r'<link\b[^>]*\bhref="https://fonts\.googleapis\.com/[^\"]+"[^>]*>\s*', '', source)
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--refresh-room-assets', action='store_true',
                        help='Refresh the two embedded room images in index.html')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / 'index.html'
    if args.refresh_room_assets:
        if args.output:
            parser.error('Do not combine an output path with --refresh-room-assets')
        source.write_text(embed_room_assets(source.read_text(encoding='utf-8')), encoding='utf-8')
        print('Embedded room artwork refreshed in index.html')
        return
    if args.output is None:
        parser.error('Choose an output path or --refresh-room-assets')
    output = args.output.resolve()
    if output == source:
        parser.error('Choose a destination other than index.html')
    document = export_demo(source.read_text(encoding='utf-8'))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding='utf-8')
    print(f'Offline demo saved: {output}')


if __name__ == '__main__':
    main()
