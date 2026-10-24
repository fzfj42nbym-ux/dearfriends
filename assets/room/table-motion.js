(()=>{
  const root=document.documentElement,pause=document.querySelector('#pause'),quiet=document.querySelector('#quiet'),restart=document.querySelector('#restart'),status=document.querySelector('#motionStatus');
  const timers=new Map();
  pause.onclick=()=>{const stopped=root.classList.toggle('paused');pause.setAttribute('aria-pressed',String(stopped));pause.textContent=stopped?'Продолжить':'Пауза'};
  quiet.onclick=()=>{const calm=root.classList.toggle('quiet');quiet.setAttribute('aria-pressed',String(calm));status.textContent=calm?'Спокойный режим: только лёгкие движения и моргание.':'Жесты и постановочные реакции включены.'};
  restart.onclick=()=>{
    document.querySelectorAll('.manual').forEach(node=>node.classList.remove('manual'));
    timers.forEach(timer=>clearTimeout(timer));timers.clear();
    document.getAnimations().forEach(animation=>{animation.currentTime=0});
    status.textContent='Цикл начат сначала.';
  };
  document.querySelectorAll('.portrait').forEach(button=>button.addEventListener('click',()=>{
    const actor=button.closest('.actor');clearTimeout(timers.get(actor));actor.classList.add('manual');
    status.textContent=actor.dataset.name+': '+actor.dataset.reaction;
    timers.set(actor,setTimeout(()=>{actor.classList.remove('manual');timers.delete(actor)},1800));
  }));
  const visibility=()=>root.classList.toggle('page-hidden',document.hidden);
  document.addEventListener('visibilitychange',visibility);visibility();
})();
