/* Procedural room authoring preview; individual interactive models are deferred. */
(()=>{
  const T=window.THREE,host=document.querySelector('#roomViewport'),status=document.querySelector('#roomStatus'),fallback=document.querySelector('#roomFallback');
  const data=JSON.parse(document.querySelector('#roomGeometry').textContent);
  const reduced=matchMedia('(prefers-reduced-motion:reduce)');
  document.body.dataset.embedded=String(window.parent!==window);
  if(window.parent!==window)document.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();window.parent.postMessage({type:'dearfriends-room3d-close'},'*')}});
  let active=null;
  const points={overview:{position:[0,8,7],target:[0,.7,-6.8]},top:{position:[0,18,-6.799],target:[0,0,-6.8]},inside:{position:[0,2.6,-.7],target:[0,1,-7]},table:{position:[0,4.2,-1.6],target:[0,.8,-6.8]},shelves:{position:[3.8,3,-7.4],target:[5,1.3,-11.6]},board:{position:[-4,2.6,-7.3],target:[-5.1,2,-11.9]}};
  function launch(){
    if(active)active.dispose();active=null;
    host.dataset.state='loading';status.textContent='Загружаем комнату…';document.querySelectorAll('nav button').forEach(b=>b.disabled=true);
    try{
      if(!T||!window.DFOrbitControls)throw new Error('3D library unavailable');
      const renderer=new T.WebGLRenderer({antialias:true,alpha:false,powerPreference:'low-power'});
      renderer.setPixelRatio(Math.min(devicePixelRatio||1,innerWidth<=800?1.25:1.75));
      renderer.shadowMap.enabled=true;renderer.shadowMap.type=T.PCFSoftShadowMap;
      renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1.15;
      renderer.domElement.tabIndex=0;renderer.domElement.setAttribute('aria-label','Трёхмерная комната: перетаскивание поворачивает камеру; масштаб — колёсиком или двумя пальцами. Для готовых ракурсов используй кнопки.');
      host.querySelector('canvas')?.remove();host.prepend(renderer.domElement);
      const scene=new T.Scene();scene.background=new T.Color('#18131f');
      const camera=new T.PerspectiveCamera(50,1,.08,100);
      const controls=new DFOrbitControls(camera,renderer.domElement);controls.enableDamping=!reduced.matches;controls.dampingFactor=.12;controls.minDistance=2.2;controls.maxDistance=28;controls.maxPolarAngle=Math.PI/2-.03;controls.minPolarAngle=.02;controls.screenSpacePanning=true;controls.keyPanSpeed=12;
      const mats={};
      function material(name,color,extra={}){return mats[name]||(mats[name]=new T.MeshStandardMaterial({color,roughness:.78,metalness:0,...extra}))}
      material('wall','#493952');material('floor','#755039');material('wood','#754320');material('table','#8a5429');material('seat','#ac3157');material('back','#682138');material('paper','#eaddba');material('detail','#252635');material('metal','#514e50',{metalness:.5,roughness:.4});material('glass','#82a2c5',{transparent:true,opacity:.36,roughness:.15});material('glow','#ffd18a',{emissive:'#ffb75d',emissiveIntensity:2});
      const hemi=new T.HemisphereLight('#cfc2ee','#523322',1.5);scene.add(hemi);
      const sun=new T.DirectionalLight('#ffe0ba',2.8);sun.position.set(-3,8,4);sun.castShadow=true;sun.shadow.mapSize.set(innerWidth<=800?512:1024,innerWidth<=800?512:1024);sun.shadow.camera.left=-12;sun.shadow.camera.right=12;sun.shadow.camera.top=12;sun.shadow.camera.bottom=-12;sun.shadow.camera.near=.5;sun.shadow.camera.far=40;sun.shadow.normalBias=.035;scene.add(sun);sun.target.position.set(0,0,-7);scene.add(sun.target);
      const lights=[];
      for(const [x,y,z,power] of [[0,3.15,-6.8,80],[5.1,2.6,-10.9,45],[-5.1,2.8,-10.9,30]]){const light=new T.PointLight('#ffc27c',power,12,2);light.position.set(x,y,z);scene.add(light);lights.push(light)}
      const geometrySet=new Set(),meshes=[];
      function mesh(geometry,mat,position){geometrySet.add(geometry);const m=new T.Mesh(geometry,mat);m.position.set(...position);m.castShadow=true;m.receiveShadow=true;scene.add(m);meshes.push(m);return m}
      function wallShape(width,door){const s=new T.Shape();s.moveTo(0,0);if(door){s.lineTo(.8,0);s.lineTo(.8,2.7);s.lineTo(3.4,2.7);s.lineTo(3.4,0)}s.lineTo(width,0);s.lineTo(width,3.8);s.lineTo(0,3.8);s.closePath();return s}
      function extrude(shape){return new T.ExtrudeGeometry(shape,{depth:.22,bevelEnabled:false,curveSegments:2})}
      const northShape=wallShape(14.4,false);
      for(const [x,w] of [[-4.6,2.6],[0,2.8],[4.6,2.6]]){const hole=new T.Path(),a=x+7.2-w/2;hole.moveTo(a,3);hole.lineTo(a,3.6);hole.lineTo(a+w,3.6);hole.lineTo(a+w,3);hole.closePath();northShape.holes.push(hole)}
      const north=mesh(extrude(northShape),mats.wall,[-7.2,0,-12.22]);
      const west=mesh(extrude(wallShape(12.44,true)),mats.wall,[-7.42,0,0]);west.rotation.y=Math.PI/2;
      const east=mesh(new T.BoxGeometry(.22,3.8,12.44),mats.wall,[7.31,1.9,-6]);
      const south=mesh(new T.BoxGeometry(14.4,3.8,.22),mats.wall,[0,1.9,.11]);
      const ceiling=mesh(new T.BoxGeometry(14.84,.22,12.44),mats.wall,[0,3.91,-6]);
      const groups=new Map();
      function kind(id){
        if(id.includes('floor'))return 'floor';if(id.startsWith('chair_back'))return 'back';if(id.startsWith('chair_seat'))return 'seat';
        if(id.includes('sheet')||id.startsWith('place_')||id.startsWith('cup_')||id.startsWith('photo_frame'))return 'paper';
        if(id.includes('glazing'))return 'glass';if(id.includes('_case_')||id.includes('photo_panel')||id.includes('laptop_screen')||id.includes('sign_reserve'))return 'detail';
        if(id.startsWith('pendant')||id.startsWith('laptop'))return 'metal';return 'wood';
      }
      const skip=new Set(['wall_north','wall_south','wall_west','wall_east','room_ceiling','communal_table_top']);
      for(const obj of data.objects){
        if(skip.has(obj.id))continue;
        const min=obj.bounds.min,max=obj.bounds.max,d=max.map((v,i)=>Math.max(.001,v-min[i])),p=max.map((v,i)=>(v+min[i])/2);
        const shape=/^(place_|cup_|pendant_)/.test(obj.id)?'cylinder':'box',key=kind(obj.id)+':'+shape;
        if(!groups.has(key))groups.set(key,[]);groups.get(key).push({obj,d,p});
      }
      const matrix=new T.Matrix4(),position=new T.Vector3(),quaternion=new T.Quaternion(),scale=new T.Vector3();
      for(const [key,items] of groups){
        const [name,shape]=key.split(':'),geometry=shape==='cylinder'?new T.CylinderGeometry(.5,.5,1,24):new T.BoxGeometry(1,1,1);geometrySet.add(geometry);
        const instance=new T.InstancedMesh(geometry,mats[name],items.length);instance.name='room-'+key;
        items.forEach(({d,p},i)=>{position.set(p[0],p[2],-p[1]);scale.set(d[0],d[2],d[1]);matrix.compose(position,quaternion,scale);instance.setMatrixAt(i,matrix)});
        instance.instanceMatrix.needsUpdate=true;instance.computeBoundingSphere();instance.castShadow=name!=='glass';instance.receiveShadow=true;scene.add(instance);meshes.push(instance);
      }
      const top=new T.Shape(),w=10.8,d=2.4,r=.18;
      top.moveTo(-w/2+r,-d/2);top.lineTo(w/2-r,-d/2);top.quadraticCurveTo(w/2,-d/2,w/2,-d/2+r);top.lineTo(w/2,d/2-r);top.quadraticCurveTo(w/2,d/2,w/2-r,d/2);top.lineTo(-w/2+r,d/2);top.quadraticCurveTo(-w/2,d/2,-w/2,d/2-r);top.lineTo(-w/2,-d/2+r);top.quadraticCurveTo(-w/2,-d/2,-w/2+r,-d/2);
      const table=mesh(new T.ExtrudeGeometry(top,{depth:.06,bevelEnabled:true,bevelSize:.015,bevelThickness:.015,bevelSegments:2,curveSegments:6}),mats.table,[0,.705,-6.8]);table.rotation.x=-Math.PI/2;
      for(const x of [4.1,5.95])for(const h of [.62,1.25,1.89,2.52])mesh(new T.BoxGeometry(1.48,.018,.025),mats.glow,[x,h,-11.39]);
      const state={cutaway:true,preset:'overview',night:true,frames:0,ready:false};let raf=0,disposed=false,contextLost=false;
      function cutWalls(){north.visible=!state.cutaway||camera.position.z>=-12;west.visible=!state.cutaway||camera.position.x>=-7.2;east.visible=!state.cutaway||camera.position.x<=7.2;south.visible=!state.cutaway||camera.position.z<=0;ceiling.visible=!state.cutaway}
      function invalidate(){if(!disposed&&!contextLost&&!document.hidden&&!raf)raf=requestAnimationFrame(draw)}
      function draw(){raf=0;if(disposed||contextLost||document.hidden)return;controls.update();const before=controls.target.clone();controls.target.clamp(new T.Vector3(-6,0,-11.5),new T.Vector3(6,3,-.5));camera.position.add(controls.target.clone().sub(before));camera.position.y=Math.max(.25,camera.position.y);cutWalls();renderer.render(scene,camera);state.frames++;if(!state.ready){state.ready=true;host.dataset.state='ready';status.textContent='Комната готова. Поворачивай сцену или выбери ракурс.';fallback.hidden=true;document.querySelectorAll('nav button').forEach(b=>b.disabled=false)} }
      controls.addEventListener('change',invalidate);
      function resize(){const rect=host.getBoundingClientRect();camera.aspect=Math.max(1,rect.width)/Math.max(1,rect.height);camera.updateProjectionMatrix();renderer.setSize(Math.max(1,rect.width),Math.max(1,rect.height),false);if(state.ready&&(state.preset==='overview'||state.preset==='top'))setPreset(state.preset);else invalidate()}
      const observer=new ResizeObserver(resize);observer.observe(host);
      function setPreset(name){const point=points[name];if(!point)return;state.preset=name;state.cutaway=name!=='inside';camera.position.set(...point.position);controls.target.set(...point.target);if(name==='overview'||name==='top')camera.position.sub(controls.target).multiplyScalar(Math.min(2,Math.max(1,.95/camera.aspect))).add(controls.target);controls.update();document.querySelectorAll('[data-camera]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.camera===name)));invalidate()}
      function setNight(){state.night=!state.night;hemi.intensity=state.night?1.5:2.4;sun.intensity=state.night?2.8:3.8;lights.forEach(l=>l.visible=state.night);document.querySelector('#roomLight').textContent=state.night?'Дневной свет':'Вечерний свет';invalidate()}
      const visibility=()=>{if(document.hidden){cancelAnimationFrame(raf);raf=0}else invalidate()};document.addEventListener('visibilitychange',visibility);
      const lost=event=>{event.preventDefault();contextLost=true;controls.enabled=false;state.ready=false;host.dataset.state='fallback';fallback.hidden=false;status.textContent='3D остановлено: графический контекст потерян. Можно повторить загрузку.';document.querySelectorAll('nav button').forEach(b=>b.disabled=true);cancelAnimationFrame(raf);raf=0};renderer.domElement.addEventListener('webglcontextlost',lost);
      const keyboard=event=>{if(!renderer.domElement.matches(':focus'))return;const key=event.key;if(key==='Home'){event.preventDefault();setPreset('overview');return}if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','='].includes(key))return;event.preventDefault();const offset=camera.position.clone().sub(controls.target),spherical=new T.Spherical().setFromVector3(offset);if(key==='ArrowLeft')spherical.theta-=.12;if(key==='ArrowRight')spherical.theta+=.12;if(key==='ArrowUp')spherical.phi=Math.max(.02,spherical.phi-.1);if(key==='ArrowDown')spherical.phi=Math.min(Math.PI/2-.03,spherical.phi+.1);if(key==='+'||key==='=')spherical.radius=Math.max(2.2,spherical.radius*.9);if(key==='-')spherical.radius=Math.min(28,spherical.radius*1.1);camera.position.copy(controls.target).add(new T.Vector3().setFromSpherical(spherical));controls.update();invalidate()};renderer.domElement.addEventListener('keydown',keyboard);
      active={setPreset,setNight,state,camera,controls,renderer,scene,dispose(){disposed=true;cancelAnimationFrame(raf);observer.disconnect();document.removeEventListener('visibilitychange',visibility);renderer.domElement.removeEventListener('webglcontextlost',lost);renderer.domElement.removeEventListener('keydown',keyboard);controls.dispose();geometrySet.forEach(g=>g.dispose());Object.values(mats).forEach(m=>m.dispose());renderer.dispose();renderer.domElement.remove()}};
      resize();setPreset('overview');draw();
      // Authoring/QA hook: camera and aggregate geometry only, no club backend.
      window.dfRoom3D={get ready(){return !!active?.state.ready},get state(){return active?.state},get camera(){return active?.camera},get stats(){return active?{triangles:active.renderer.info.render.triangles,calls:active.renderer.info.render.calls,seats:data.seats.length,objects:data.objects.length}:null},preset:name=>active?.setPreset(name),redraw:invalidate};
    }catch(error){host.dataset.state='fallback';fallback.hidden=false;status.textContent='В этом просмотрщике 3D недоступно. Показан макет комнаты; попробуй открыть файл в обычном браузере.';window.dfRoom3D={ready:false,error:String(error.message||error)}}
  }
  document.querySelectorAll('[data-camera]').forEach(button=>button.onclick=()=>active?.setPreset(button.dataset.camera));
  document.querySelector('#roomLight').onclick=()=>active?.setNight();document.querySelector('#roomRetry').onclick=()=>{launch();if(active?.state.ready)host.querySelector('canvas')?.focus()};
  launch();
})();
