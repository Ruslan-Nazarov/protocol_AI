'use strict';
let readerState=null, readerBusy=false;
const readerLabels={known:'Известно',introduced:'Введено',unknown:'Неизвестно',doubted:'Под сомнением'};
const READER_DRAFT='protocol-reader-draft';
function readerDraft(){try{return localStorage.getItem(READER_DRAFT)||'';}catch{return '';}}
function saveReaderDraft(value){try{localStorage.setItem(READER_DRAFT,value);}catch{}}
async function renderReader(){
  readerState=null;
  $('main').innerHTML=protocolAboutHTML()+protocolSetupRouteHTML('reader')+`<div class="page-header"><div class="eyebrow">ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ · §8.3</div><h1>Какие объяснения вам нужны?</h1><p class="intro">Профиль помогает ИИ начинать с понятных вам оснований и раскрывать новые понятия там, где они нужны.</p></div><section class="card"><h2>Оценка понимания с вашим ИИ</h2><p>Расскажите, в какой области работаете, что уже понимаете и что пока вызывает затруднение. ИИ может предложить небольшой пример и уточняющий вопрос. Затем вы проверите предложенный профиль.</p><p class="small-note">«Известно» — вы подтвердили или применили понятие. «Введено» — объяснение дано, понимание ещё не подтверждено. «Неизвестно» — вы сообщили о затруднении. «Под сомнением» — значение или применение требует уточнения.</p><p id="reader-ai-status" role="status">Читаем подключение…</p><div id="reader-conversation" class="onboarding-conversation"></div><form id="reader-form"><label class="form-label" for="reader-answer">О вашей работе и понимании понятий</label><textarea id="reader-answer" class="draft-input compact" maxlength="12000" required placeholder="Например: работаю с текстами, в программировании начинаю. Понимаю, что такое промпт; пока не понимаю, как скрипт проверяет ответ…"></textarea><div class="button-row"><button class="primary-button" disabled>Оценить профиль с ИИ →</button><button id="reader-defer" type="button" class="secondary-button" disabled>Пока без оценки</button></div><p class="small-note">Беседа отправляется вашему API только по нажатию кнопки. Оценку можно отложить: тогда ИИ будет кратко объяснять необходимые понятия на примере текущей задачи.</p></form><p id="reader-status" role="status"></p><div id="reader-proposal"></div></section><section id="reader-current" class="card" hidden></section>`;
  $('reader-answer').value=readerDraft();
  try{
    const [data,settings]=await Promise.all([workspaceAPI('/api/reader'),aiEditorAPI('settings')]);
    if(state.page!=='reader')return;
    readerState=data;renderReaderState();
    $('reader-ai-status').innerHTML=settings.configured?`Подключён ${escapeHTML(settings.model)}. <a href="#settings">Настройки ИИ</a>`:'Сначала <a href="#home">подключите свой ИИ</a>. Черновик сохранится.';
    $('reader-form').querySelector('button').disabled=!settings.configured||readerBusy;
    $('reader-defer').disabled=readerBusy;
  }catch(error){if($('reader-status'))$('reader-status').textContent=error.message;}
}
function readerTermsHTML(terms,editable=false){
  if(!terms.length)return '<p>Понимание отдельных понятий пока не установлено.</p>';
  return terms.map((t,i)=>`<article class="reader-term"><div><strong>${escapeHTML(t.term)}</strong>${editable?`<label class="form-label" for="reader-term-${i}">Состояние понимания</label><select id="reader-term-${i}" class="text-input" data-reader-term="${escapeHTML(t.term)}">${Object.entries(readerLabels).map(([k,v])=>`<option value="${k}" ${k===t.status?'selected':''}>${v}</option>`).join('')}</select>`:`<span class="reader-status-badge">${readerLabels[t.status]}</span>`}</div><blockquote>${escapeHTML(t.evidence.quote)}</blockquote><p class="small-note">Основание: ${t.evidence.role==='user'?'ваша реплика':'объяснение ИИ'} ${t.evidence.message+1}.${editable?' Проверьте, действительно ли запись описывает ваше понимание.':''}</p></article>`).join('');
}
function renderReaderState(){
  const p=readerState.profile,c=readerState.conversation;
  $('reader-defer').hidden=p.configured;
  $('reader-conversation').innerHTML=c.messages.map(m=>`<article class="conversation-message ${m.role}"><strong>${m.role==='user'?'Вы':'ИИ'}</strong><p data-original>${escapeHTML(m.content)}</p></article>`).join('');
  $('reader-current').hidden=!p.configured;
  $('reader-current').innerHTML=p.configured?`<h2>Сохранённый профиль · версия ${p.revision}</h2><p>${p.assessed?'Предложение проверено и сохранено вами.':'Вы выбрали работу без оценки понимания.'}</p><p><strong>Область:</strong> ${escapeHTML(p.areas||'Не установлена')}</p><p><strong>Язык:</strong> ${escapeHTML(p.language||'Из текущего общения')}</p><p><strong>Объяснение:</strong> ${escapeHTML(p.preferences||'Кратко раскрывать необходимые понятия на текущем примере')}</p>${readerTermsHTML(p.terms)}<div class="button-row"><a class="primary-button" href="#protocol-setup">Продолжить настройку протокола →</a><a class="secondary-button" href="/api/reader/file" download="READER.md">Скачать профиль</a></div>`:'';
  const draft=c.proposal;
  const stale=c.reader_revision!==p.revision;
  if(stale&&p.configured){$('reader-proposal').innerHTML='<p class="small-note">Предложение рассмотрено. Действующая запись показана в сохранённом профиле ниже; её можно уточнить новым ответом.</p>';return;}
  $('reader-proposal').innerHTML=draft?`<div class="onboarding-summary"><h2>Предложение профиля · проверьте перед сохранением</h2><p><strong>Область:</strong> ${escapeHTML(draft.areas||'Не установлена')}</p><p><strong>Язык:</strong> ${escapeHTML(draft.language||'Не установлен')}</p><p><strong>Как объяснять:</strong> ${escapeHTML(draft.preferences||'Уточняется по ходу работы')}</p>${readerTermsHTML(draft.terms,true)}${draft.questions.length?`<p>Можно уточнить в следующем ответе:</p><ul>${draft.questions.map(q=>`<li>${escapeHTML(q)}</li>`).join('')}</ul>`:''}<p class="small-note">Сохранение подтверждает выбранные вами состояния. Сам ответ ИИ и молчание не подтверждают понимание.</p><p role="status">${stale?'Это предложение уже сохранено или профиль изменён. Продолжайте настройку либо уточните профиль новым ответом.':c.checks?.blocking?'Обязательная проверка ответа не пройдена; сохранение заблокировано.':'Проверки ссылок и формы выполнены; смысл записи проверяете вы.'}</p><button id="reader-accept" class="primary-button" ${stale||c.checks?.blocking?'disabled':''}>Подтвердить и сохранить профиль →</button><details><summary>Состав запроса и проверки</summary><p>Текущий профиль: версия ${c.reader_revision}. Состав инструкций и точная беседа сохранены вместе с ответом.</p><pre class="raw-source">${escapeHTML(JSON.stringify({rules:c.runtime?.rules?.map(r=>r.section),checks:c.checks,usage:c.usage},null,2))}</pre><details><summary>Точный запрос вашему ИИ</summary><pre class="raw-source">${escapeHTML(JSON.stringify(c.calls?.at(-1)?.messages||[],null,2))}</pre></details></details></div>`:'';
}
async function readerAction(action,payload){
  if(readerBusy||!readerState)return;
  readerBusy=true;
  const buttons=[...$('main').querySelectorAll('button')].map(b=>[b,b.disabled]);buttons.forEach(([b])=>b.disabled=true);
  $('reader-status').textContent=action==='message'?'ИИ уточняет профиль понимания…':'Сохраняем ваше решение…';
  try{
    const data=await workspaceAPI('/api/reader/'+action,{expected_revision:readerState.conversation.revision,expected_profile_revision:readerState.profile.revision,...payload});
    readerState=data;
    if(action==='message'&&readerDraft()===payload.answer)saveReaderDraft('');
    if(state.page!=='reader')return;
    $('reader-answer').value=readerDraft();renderReaderState();
    refreshSetupRoute();
    $('reader-status').textContent=action==='message'?'ИИ предложил профиль. Проверьте состояния и основания.':'Профиль сохранён. Он будет учтён в запросах и передан рабочему клиенту.';
    if(action==='defer')location.hash='protocol-setup';
    if(action==='accept')$('reader-current').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(error){if(state.page==='reader')$('reader-status').textContent=error.message;}
  finally{readerBusy=false;buttons.forEach(([b,wasDisabled])=>{if(b.isConnected)b.disabled=wasDisabled;});}
}
document.addEventListener('input',e=>{if(e.target.id==='reader-answer')saveReaderDraft(e.target.value);});
document.addEventListener('submit',e=>{if(e.target.id==='reader-form'){e.preventDefault();readerAction('message',{answer:$('reader-answer').value});}});
document.addEventListener('click',e=>{
  if(e.target.closest('#reader-defer'))readerAction('defer',{});
  if(e.target.closest('#reader-accept'))readerAction('accept',{statuses:Object.fromEntries([...document.querySelectorAll('[data-reader-term]')].map(s=>[s.dataset.readerTerm,s.value]))});
});
