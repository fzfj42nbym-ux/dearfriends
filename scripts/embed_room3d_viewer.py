#!/usr/bin/env python3
"""Refresh the self-contained 3D iframe in the main single-file application."""
import html
from pathlib import Path
import re


def main():
    root=Path(__file__).resolve().parents[1]
    viewer=(root/'room3d.html').read_text()
    source=root/'index.html'
    document=source.read_text()
    def update(match):
        tag=re.sub(r'\s+srcdoc="[^"]*"','',match[0])
        embedded=html.escape(viewer,quote=True).replace('\r','&#13;').replace('\n','&#10;')
        return tag[:-1]+' srcdoc="'+embedded+'">'
    document,count=re.subn(r'<iframe\b(?=[^>]*\bid="clubRoomFrame")[^>]*>',update,document)
    if count!=1:raise ValueError('Expected exactly one clubRoomFrame')
    source.write_text(document)
    print('Embedded3Droom refreshed in index.html')


if __name__=='__main__':main()
