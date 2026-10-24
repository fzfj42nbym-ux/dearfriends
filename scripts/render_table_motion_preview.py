#!/usr/bin/env python3
"""Capture the actual SVG preview timeline to a deterministic 12-second MP4."""
import argparse
from pathlib import Path
import subprocess

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('preview', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fps = 24
    with sync_playwright() as p, args.output.with_suffix('.render.log').open('w') as log:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        context = browser.new_context(viewport={'width':1440,'height':900}, reduced_motion='no-preference')
        context.route('**/*', lambda route: route.abort())
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_content(args.preview.read_text(), wait_until='load')
        page.add_style_tag(content='header{display:none}')
        page.evaluate('''async()=>{
          await Promise.all([...document.images].map(n=>n.decode()));await document.fonts.ready;
          window.captureAnimations=document.getAnimations();
          window.captureAnimations.forEach(a=>a.pause());
          await Promise.all(window.captureAnimations.map(a=>a.ready));
        }''')
        process = subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','warning','-y','-f','image2pipe','-framerate',str(fps),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','21','-pix_fmt','yuv420p','-movflags','+faststart',str(args.output)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
        try:
            for frame in range(12*fps):
                page.evaluate('(time)=>{window.captureAnimations.forEach(a=>a.currentTime=time)}', frame*1000/fps)
                image = page.screenshot(type='jpeg', quality=90)
                process.stdin.write(image)
                if frame == 84:
                    page.screenshot(path=str(args.output.with_suffix('.png')))
                if frame%48==0:
                    print(f'Captured {frame}/{12*fps}', flush=True)
        finally:
            process.stdin.close()
            code = process.wait(timeout=60)
            browser.close()
        assert code == 0, 'Video encoder failed; inspect the render log'
        assert not errors, errors
        print(f'Ready: {args.output} (12 seconds, {fps}fps)', flush=True)


if __name__ == '__main__':
    main()
