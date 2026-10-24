#!/usr/bin/env python3
"""Record an orbit of the actual WebGL room as a lightweight review video."""
import argparse
from pathlib import Path
import subprocess
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    fps=20;frames=6*fps
    with sync_playwright() as p,args.output.with_suffix('.render.log').open('w') as log:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        context.route('**/*',lambda r:r.abort());page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.set_content(args.source.read_text(),wait_until='load');page.wait_for_function('dfRoom3D.ready')
        process=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','warning','-y','-f','image2pipe','-framerate',str(fps),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','21','-pix_fmt','yuv420p','-movflags','+faststart',str(args.output)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log)
        try:
            for frame in range(frames):
                page.evaluate('''async angle=>{dfRoom3D.camera.position.set(14*Math.sin(angle),8,-6.8+14*Math.cos(angle));dfRoom3D.redraw();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))}''',frame/frames*6.283185307179586)
                process.stdin.write(page.screenshot(type='jpeg',quality=90))
                if frame==15:page.screenshot(path=str(args.output.with_suffix('.png')))
                if frame%30==0:print(f'Captured {frame}/{frames}',flush=True)
        finally:
            process.stdin.close();code=process.wait(timeout=60);browser.close()
        assert code==0,'Video encoding failed'
        assert not errors,errors
        print(args.output.resolve(),flush=True)


if __name__=='__main__':main()
