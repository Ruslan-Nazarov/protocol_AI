'use strict';

let onboardingState=null, onboardingProfileRevision=0, onboardingBusy=false, setupSettings=null;
let handoffData={description:'',materials:'',firstStep:''}, handoffLoaded=false, handoffLoading=null;
try{handoffData={...handoffData,...JSON.parse(localStorage.getItem('protocol-first-message')||'{}')};}catch{}

function firstProjectMessage(description,materials,firstStep,protocolPath){
  return `Прочитай инструкции рабочего проекта, подключённый протокол и актуальную память.\nПапка протокола: ${protocolPath}.\nСообщи, какие файлы прочитаны и какие недоступны.\n\nОписание проекта и исходное состояние:\n${description.trim()}\n\n${materials.trim()?'Материалы проекта:\n'+materials.trim()+'\n\n':''}Первый шаг:\n${firstStep.trim()||'Исследуй предоставленные материалы и исходное состояние. Объясни, что удалось проверить и чего не хватает. Предложи небольшую первую задачу и способ проверки её результата.'}\n\nСохрани цель, исходное состояние и следующий шаг в памяти именно этого рабочего проекта. Загруженные примеры памяти атласа не считай состоянием проекта. Неизвестное обозначай явно.`;
}
async function loadHandoffDescription(){
  if(handoffLoaded)return;
  if(handoffLoading)return handoffLoading;
  handoffLoading=(async()=>{
    const [adaptive,conversation]=await Promise.all([workspaceAPI('/api/adaptive'),onboardingAPI('')]);
    if(!handoffData.description){
      const p=adaptive.profile;
      handoffData.description=p.configured?[p.purpose,'Исходное состояние: '+p.starting_point,'Требования: '+p.requirements].join('\n\n'):conversation.messages.filter(m=>m.role==='user').map(m=>m.content).join('\n\n');
    }
    if(adaptive.profile.configured&&!handoffData.materials){
      handoffData.materials=conversation.messages.filter(m=>m.role==='user').map(m=>m.content).join('\n\n');
    }
    handoffLoaded=true;
  })();
  try{await handoffLoading;}finally{handoffLoading=null;}
}
function mountProjectHandoff(client,protocolPath){
  const container=$('connection-instruction');if(!container||client.type!=='agent')return;
  const title=connectionChoice.client==='codex'?'Codex':client.label;
  container.insertAdjacentHTML('beforeend',`<section id="project-handoff" class="project-handoff"><div class="eyebrow">ПОДКЛЮЧЕНИЕ ГОТОВО · ПЕРЕХОД В РАБОЧИЙ ПРОЕКТ</div><h2>Первое сообщение для ${escapeHTML(title)}</h2><p>Скопируйте сообщение ниже, перейдите в открытый проект своего приложения в ${escapeHTML(title)} и вставьте его в новый чат. Дальнейшую работу ведите в этом чате.</p><p class="small-note">Описание из начальной настройки подставится автоматически. Здесь можно дописать материалы и первый шаг обычным текстом. Сообщение собирается на этом компьютере.</p><label class="form-label" for="handoff-description">Описание проекта и что уже есть</label><textarea id="handoff-description" class="draft-input compact" maxlength="4000" placeholder="Что хотите получить и из какого состояния начинаете…"></textarea><label class="form-label" for="handoff-materials">Материалы проекта — ссылки, API, документы</label><textarea id="handoff-materials" class="draft-input compact" maxlength="2000" placeholder="Например: адрес API программы конференции…"></textarea><label class="form-label" for="handoff-first-step">Что сделать первым — необязательно</label><textarea id="handoff-first-step" class="draft-input compact" maxlength="1000" placeholder="Например: исследовать ответ API и предложить статистики, которые можно достоверно посчитать…"></textarea><h3>Готовое сообщение</h3><pre id="handoff-message" class="raw-source" data-original></pre><div class="button-row"><button id="handoff-copy" class="primary-button" type="button">Скопировать первое сообщение</button><a id="handoff-download" class="secondary-button" data-connection-download download="FIRST_MESSAGE.md">Скачать первое сообщение</a></div><p id="handoff-status" class="small-note" role="status"></p><p><strong>Теперь перейдите в ${escapeHTML(title)}.</strong> Этот экран завершает подключение; ответы по рабочей задаче вы получаете в чате своего проекта.</p><h3>Что происходит после отправки</h3><ol><li>Codex читает инструкции, протокол и память проекта и сообщает, какие файлы доступны.</li><li>Выполняет первый небольшой шаг и объясняет, что проверено и что осталось неизвестным.</li><li>Вы проверяете результат в чате Codex: принимаете его или просите доработку.</li><li>Codex сохраняет итог и следующий шаг в памяти проекта. Новый чат начинает с её чтения.</li></ol><p class="small-note">Возвращайтесь к протоколу, если нужно изменить правила или разобрать обнаруженный недостаток. Обычные результаты работы сохраняются в памяти вашего проекта.</p></section>`);
  for(const [id,key] of [['handoff-description','description'],['handoff-materials','materials'],['handoff-first-step','firstStep']])$(id).value=handoffData[key];
  $('project-handoff').dataset.protocolPath=protocolPath;
  updateProjectHandoff();
}
function updateProjectHandoff(){
  const section=$('project-handoff');if(!section)return;
  const message=firstProjectMessage(handoffData.description,handoffData.materials,handoffData.firstStep,section.dataset.protocolPath);
  $('handoff-message').textContent=message;
  const reason=!handoffData.description.trim()?'Опишите проект выше, чтобы получить первое сообщение.':!connectionChoice.path.trim()?'Укажите путь к папке проекта в поле подключения выше.':message.length>8000?'Сообщение превышает 8000 символов. Сократите описание или передайте часть материалов отдельным файлом. Текст не обрезается.':'';
  $('handoff-copy').disabled=Boolean(reason);
  const download=$('handoff-download');download.setAttribute('aria-disabled',String(Boolean(reason)));download.tabIndex=reason?-1:0;
  if(reason)download.removeAttribute('href');else download.href='/api/connection-instruction?'+new URLSearchParams({text:message,filename:'FIRST_MESSAGE.md'});
  $('handoff-status').textContent=reason;
  try{localStorage.setItem('protocol-first-message',JSON.stringify(handoffData));}catch{}
}
document.addEventListener('input',event=>{
  const key={'handoff-description':'description','handoff-materials':'materials','handoff-first-step':'firstStep'}[event.target.id];
  if(key){handoffData[key]=event.target.value;updateProjectHandoff();}
});
document.addEventListener('click',async event=>{
  if(!event.target.closest('#handoff-copy'))return;
  try{await navigator.clipboard.writeText($('handoff-message').textContent);$('handoff-status').textContent='Скопировано. Перейдите в рабочий проект и вставьте сообщение в чат.';}
  catch{ $('handoff-status').textContent='Выделите готовое сообщение и скопируйте вручную либо скачайте файл.';}
});
const ONBOARDING_DRAFT='protocol-onboarding-draft';
function helpHint(label,content){
  return `<span class="help-wrap"><button type="button" class="help-button" aria-label="${escapeHTML(label)}" aria-expanded="false">?</button><span class="help-popup" role="note" hidden>${escapeHTML(content)}</span></span>`;
}
async function onboardingAPI(action,payload){return workspaceAPI('/api/onboarding'+(action?'/'+action:''),payload);}
function onboardingDraft(){try{return localStorage.getItem(ONBOARDING_DRAFT)||'';}catch{return '';}}
function saveOnboardingDraft(value){try{localStorage.setItem(ONBOARDING_DRAFT,value);}catch{}}

async function renderStart(){
  $('main').innerHTML=protocolAboutHTML()+protocolSetupRouteHTML('protocol-setup')+`<div class="page-header"><div class="eyebrow">НАСТРОЙКА ПРОТОКОЛА · БЕСЕДА С ИИ</div><h1>Для какой работы настраиваем протокол?</h1><p class="intro">Опишите цель и исходные условия. ИИ поможет определить требования к инструкциям, этапам, памяти и проверкам. Рабочую задачу вы затем выполняете в Codex или другом клиенте.</p></div><section class="card"><p id="start-ai-note" class="small-note">Читаем подключение ИИ…</p><div id="onboarding-conversation" class="onboarding-conversation" aria-live="polite"></div><form id="onboarding-form"><label class="form-label" for="onboarding-answer">Ваш ответ</label><textarea id="onboarding-answer" class="draft-input compact" maxlength="12000" required placeholder="Например: разрабатываю приложения. ИИ должен разбирать задачу на этапы, проверять код и сохранять решения между чатами…"></textarea><div class="button-row"><button class="primary-button" type="submit">Обсудить с ИИ →</button><a class="secondary-button" href="#protocol-setup">К инструментам настройки</a></div><p class="small-note">Нажатие «Обсудить с ИИ» отправит беседу вашему выбранному API.</p></form><p id="onboarding-status" role="status"></p><div id="onboarding-understanding"></div></section>`;
  $('onboarding-answer').value=onboardingDraft();
  try{
    const [data,settings,adaptive]=await Promise.all([onboardingAPI(''),aiEditorAPI('settings'),workspaceAPI('/api/adaptive')]);
    if(state.page!=='onboarding')return;
    onboardingState=data;onboardingProfileRevision=adaptive.profile.revision;renderOnboardingConversation();
    $('start-ai-note').innerHTML=settings.configured?`Для беседы подключён ${escapeHTML(settings.model)}. <a href="#settings">Настройки ИИ →</a>`:'Сначала <a href="#settings">добавьте свой ИИ</a>. Можно написать описание сейчас: черновик сохранится при переходе к настройкам.';
  }catch(error){if($('onboarding-status'))$('onboarding-status').textContent=error.message;}
}
function renderOnboardingConversation(){
  const target=$('onboarding-conversation');if(!target||!onboardingState)return;
  target.innerHTML=onboardingState.messages.map(m=>`<article class="conversation-message ${m.role}"><strong>${m.role==='user'?'Вы':'ИИ'}</strong><p data-original>${escapeHTML(m.content)}</p></article>`).join('');
  const p=onboardingState.proposal;
  $('onboarding-understanding').innerHTML=p?`<div class="onboarding-summary"><h3>Как ИИ понял условия настройки</h3><p><strong>Цель:</strong> <span data-original>${escapeHTML(p.purpose||'Пока не установлена')}</span></p><p><strong>Уже есть:</strong> <span data-original>${escapeHTML(p.starting_point||'Пока не установлено')}</span></p><p><strong>Требования:</strong> <span data-original>${escapeHTML(p.requirements||'Пока не названы')}</span></p>${p.questions.length?`<p><strong>Осталось уточнить:</strong></p><ul data-original>${p.questions.map(q=>`<li>${escapeHTML(q)}</li>`).join('')}</ul>`:''}<p>Если что-то понято неверно, поправьте обычным текстом в поле ответа выше.</p><button id="onboarding-accept" class="secondary-button" ${p.purpose&&!onboardingState.checks?.blocking?'':'disabled'}>Сохранить условия настройки →</button><details><summary>Запрос, инструкции и проверки</summary><pre class="raw-source">${escapeHTML(JSON.stringify({reader_revision:onboardingState.reader_revision,rules:onboardingState.runtime?.rules?.map(r=>r.section),checks:onboardingState.checks,usage:onboardingState.usage},null,2))}</pre><details><summary>Точный запрос вашему ИИ</summary><pre class="raw-source">${escapeHTML(JSON.stringify(onboardingState.calls?.at(-1)?.messages||[],null,2))}</pre></details></details></div>`:'';
}
function protocolAboutHTML(){
  return `<button id="protocol-about-open" type="button" class="protocol-about-banner" aria-haspopup="dialog" aria-controls="protocol-about"><span><strong>Как это работает</strong><small>Зачем нужен протокол, что он настраивает и где выполняется работа</small></span><span aria-hidden="true">↗</span></button>`;
}
function protocolSetupRouteHTML(){return '';}
async function refreshSetupRoute(){}
let setupDirty=false, setupChecking=false;
async function renderSettings(firstStep=false){
  setupSettings=null;setupDirty=false;setupChecking=false;
  const page=state.page;
  $('main').innerHTML=protocolAboutHTML()+protocolSetupRouteHTML('home')+`<div class="page-header"><div class="eyebrow">${firstStep?'ШАГ 1 · ПОДКЛЮЧЕНИЕ ИИ':'НАСТРОЙКИ ПОДКЛЮЧЕНИЯ'}</div><h1>${firstStep?'Подключите свой ИИ':'Мой ИИ'}</h1><p class="intro">Подключите собственный API ИИ, чтобы настраивать промпты и правила протокола, разбирать работу скриптов и проверять изменения.</p></div><section class="card"><p>Здесь вы настраиваете протокол с помощью своего ИИ. После настройки рабочие задачи выполняются в Codex, другом агенте или чате.</p><form id="setup-ai-form"><label class="form-label" for="setup-provider">Сервис ИИ ${helpHint('Пояснение выбора сервиса ИИ','Выберите готовый сервис или «Другой сервис или локальная модель» для своего адреса API. Поддерживается формат Chat Completions.')}</label><select id="setup-provider" class="text-input">${Object.entries(AI_PROVIDERS).map(([k,v])=>`<option value="${k}">${escapeHTML(v)}</option>`).join('')}</select><div id="setup-endpoint-field"><label class="form-label" for="setup-endpoint">Базовый адрес API ${helpHint('Как указать адрес API','Укажите адрес до /chat/completions, например https://example.com/v1. Для локального сервиса: http://127.0.0.1:порт/v1.')}</label><input id="setup-endpoint" class="text-input" type="url" placeholder="https://example.com/v1"></div><label class="form-label" for="setup-model">Имя модели</label><input id="setup-model" class="text-input" maxlength="160" required><label class="form-label" for="setup-key">Ваш API-ключ</label><input id="setup-key" class="text-input" type="password" maxlength="2000" autocomplete="new-password" placeholder="Введите ключ своего сервиса"><p class="small-note">Каждый пользователь подключает свой ключ. Ключ сохраняется в локальных настройках этого приложения и используется для запросов к выбранному сервису ИИ. Он не включается в инструкции и архив подключения рабочего клиента. Для локального API без авторизации поле можно оставить пустым.</p><label class="checkbox-label"><input id="setup-clear-key" type="checkbox">Удалить сохранённый ключ</label><details><summary>Параметры ответа</summary><label class="form-label" for="setup-output">Предел ответа, токенов</label><input id="setup-output" class="text-input" type="number" min="1000" max="16000" value="6000"><label class="checkbox-label"><input id="setup-json" type="checkbox">JSON-режим для сервисов, которые его поддерживают</label></details><div class="button-row"><button class="primary-button" type="submit" disabled>Сохранить подключение</button><button id="setup-test" class="secondary-button" type="button" disabled>Проверить подключение</button></div><p class="small-note">Сохранение не вызывает ИИ. «Проверить подключение» отправит выбранному сервису один короткий запрос; он расходует токены вашего API.</p></form><p id="setup-status" role="status">Читаем сохранённое подключение…</p><div class="button-row"><a id="setup-continue" class="primary-button" aria-disabled="true" tabindex="-1">Продолжить к профилю пользователя →</a></div></section>`;
  $('setup-ai-form').querySelectorAll('input,select').forEach(field=>{field.disabled=true;});
  try{const settings=await aiEditorAPI('settings');if(state.page!==page||!$('setup-ai-form'))return;setupSettings=settings;fillSetupSettings(settings);}catch(error){if(state.page===page&&$('setup-status'))$('setup-status').textContent=error.message;}
}
function updateSetupActions(){
  if(!$('setup-test'))return;
  $('setup-ai-form').querySelector('button[type="submit"]').disabled=!setupSettings||setupChecking;
  $('setup-test').disabled=!setupSettings?.configured||setupDirty||setupChecking;
  const ready=Boolean(setupSettings?.connection_verified&&!setupDirty&&!setupChecking),next=$('setup-continue');
  next.setAttribute('aria-disabled',String(!ready));next.tabIndex=ready?0:-1;
  if(ready){next.href='#reader';next.textContent='Продолжить к профилю пользователя →';}else next.removeAttribute('href');
}
function fillSetupSettings(s){
  $('setup-ai-form').querySelectorAll('input,select').forEach(field=>{field.disabled=false;});
  $('setup-provider').value=s.provider;$('setup-endpoint').value=s.endpoint;$('setup-model').value=s.model;$('setup-output').value=s.max_output;$('setup-json').checked=s.json_mode;
  $('setup-endpoint-field').hidden=s.provider!=='custom';
  $('setup-key').placeholder=s.key_configured?'Ключ сохранён. Оставьте пустым, чтобы сохранить его':'Введите ключ своего сервиса';
  setupDirty=false;updateSetupActions();
  $('setup-status').textContent=s.connection_verified?`Подключение проверено: ${s.model}. Можно перейти к настройке протокола.`:s.configured?`Подключение сохранено: ${s.model}. Нажмите «Проверить подключение», чтобы получить ответ ИИ.`:'Выберите сервис, укажите модель и свой API-ключ, затем сохраните подключение.';
}
function markSetupDirty(event){
  if(!event.target.closest('#setup-ai-form'))return;
  setupDirty=true;updateSetupActions();
  $('setup-status').textContent='Настройки изменены. Сохраните подключение перед проверкой.';
}
document.addEventListener('input',markSetupDirty);
document.addEventListener('change',markSetupDirty);
document.addEventListener('click',async event=>{
  if(event.target.closest('#protocol-about-open'))$('protocol-about').showModal();
  if(event.target.closest('#protocol-about-close'))$('protocol-about').close();
  if(!event.target.closest('#setup-test'))return;
  const button=$('setup-test');if(button.disabled)return;
  setupChecking=true;updateSetupActions();$('setup-status').textContent='Отправляем проверочный запрос вашему ИИ…';
  try{
    const result=await aiEditorAPI('test-connection',{expected_revision:setupSettings.revision});
    if(!button.isConnected)return;
    setupSettings=result.settings;
    $('setup-status').textContent=setupDirty?'Подключение ответило, но вы изменили поля. Сохраните изменения и проверьте их.':result.message;
  }catch(error){if(button.isConnected){setupSettings.connection_verified=false;$('setup-status').textContent=error.message;}}
  finally{if(button.isConnected){setupChecking=false;updateSetupActions();}}
});

document.addEventListener('input',event=>{if(event.target.id==='onboarding-answer')saveOnboardingDraft(event.target.value);});
document.addEventListener('change',event=>{if(event.target.id==='setup-provider')$('setup-endpoint-field').hidden=event.target.value!=='custom';});
document.addEventListener('click',async event=>{
  const help=event.target.closest('.help-button');
  if(help){event.preventDefault();const open=help.getAttribute('aria-expanded')!=='true';help.setAttribute('aria-expanded',String(open));help.nextElementSibling.hidden=!open;return;}
  if(event.target.closest('#onboarding-accept')){
    const b=$('onboarding-accept');b.disabled=true;
    try{await onboardingAPI('accept',{expected_revision:onboardingState.revision,expected_profile_revision:onboardingProfileRevision});handoffData.description='';handoffLoaded=false;location.hash='protocol-setup';}
    catch(error){if($('onboarding-status'))$('onboarding-status').textContent=error.message;}finally{if(b.isConnected)b.disabled=false;}
  }
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')document.querySelectorAll('.help-button[aria-expanded="true"]').forEach(b=>{b.setAttribute('aria-expanded','false');b.nextElementSibling.hidden=true;});});
document.addEventListener('submit',async event=>{
  if(!['onboarding-form','setup-ai-form'].includes(event.target.id))return;
  event.preventDefault();const form=event.target,b=form.querySelector('button[type="submit"]');
  if(b.disabled||onboardingBusy)return;b.disabled=true;
  if(form.id==='setup-ai-form'){
    try{
      if(!setupSettings)throw Error('Дождитесь загрузки настроек.');
      const s=await aiEditorAPI('settings',{provider:$('setup-provider').value,endpoint:$('setup-endpoint').value,model:$('setup-model').value,api_key:$('setup-key').value,clear_key:$('setup-clear-key').checked,json_mode:$('setup-json').checked,max_output:Number($('setup-output').value),expected_revision:setupSettings.revision});
      if(!b.isConnected)return;setupSettings=s;$('setup-key').value='';$('setup-clear-key').checked=false;fillSetupSettings(s);
    }catch(error){if($('setup-status'))$('setup-status').textContent=error.message;}finally{if(b.isConnected)b.disabled=false;}return;
  }
  onboardingBusy=true;const answer=$('onboarding-answer').value;$('onboarding-status').textContent='ИИ разбирает ваш ответ…';
  try{
    if(!onboardingState)throw Error('Дождитесь загрузки беседы.');
    const data=await onboardingAPI('message',{answer,expected_revision:onboardingState.revision});onboardingState=data;
    if(onboardingDraft()===answer)saveOnboardingDraft('');
    if(state.page!=='onboarding')return;
    $('onboarding-answer').value=onboardingDraft();renderOnboardingConversation();$('onboarding-status').textContent='Ответ сохранён. Проверьте условия настройки протокола.';
  }catch(error){if($('onboarding-status'))$('onboarding-status').textContent=error.message;}
  finally{onboardingBusy=false;if(b.isConnected)b.disabled=false;}
});
