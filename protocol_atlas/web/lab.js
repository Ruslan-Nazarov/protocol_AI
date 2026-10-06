'use strict';

const labState = {options:null, run:null, snapshot:null, starting:false, timer:null, episodeId:'protocol-pilot'};
const CONDITION_NAMES = {full:'Полный материал',summary:'Обычное резюме',structured:'Структура и основания',records:'Записи с точными основаниями',retrieval:'Чтение источников по запросу',exact:'Точные записи и проверка ссылок'};
const RUN_STATUS = {prepared:'Подготовлен',running:'Выполняется',completed:'Завершён',failed:'Техническая ошибка',cancelled:'Остановлен',interrupted:'Прерван перезапуском'};
const CHECK_NAMES = {budget:'Предел размера',json:'Формат JSON',task_coverage:'Все задания',source_paths:'Известные пути источников',answers_present:'Ответы не пусты',meaning:'Содержательная оценка',references:'Ссылки, версии и цитаты'};
const VERDICTS = {pass:'Пройдено',fail:'Не пройдено',unknown:'Не проверено'};

async function labRequest(path,payload) {
  const response=await fetch(path,payload===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Ошибка стенда.');return data;
}

function labError(error){if($('memory-error'))$('memory-error').innerHTML=`<div class="check-message">${escapeHTML(error.message)}</div>`;}

function materialHTML(material) {
  return `<p class="small-note">${material.characters.toLocaleString('ru')} символов · версия каталога ${escapeHTML(material.catalog_revision.slice(0,12))}</p><details class="source-details"><summary>Посмотреть всё, что будет передано модели</summary><p class="small-note">Инструкция для всех вариантов: ${escapeHTML(material.instructions)}</p>${material.sources.map(source=>`<details class="source-details"><summary>${escapeHTML(source.path)}${source.start_line?` · строки ${source.start_line}–${source.end_line}`:''} · ${escapeHTML(source.sha256.slice(0,12))}</summary><pre class="raw-source">${escapeHTML(source.text)}</pre></details>`).join('')}<h3>Задания новой сессии</h3><ol>${material.tasks.map(task=>`<li>${escapeHTML(task.question)}</li>`).join('')}</ol><p class="small-note">Критерии оценщика не передаются моделям. Сжиматель получает только материал и свою инструкцию, без заданий продолжения.</p></details>`;
}

async function mountMemoryLab() {
  clearTimeout(labState.timer);
  try{
    labState.options=await labRequest('/api/lab-options');
    if(state.page!=='labs'||!$('memory-setup'))return;
    renderLabSetup();await refreshRuns();await renderComparison();
    const runId=new URLSearchParams(location.hash.split('?')[1]||'').get('run');
    if(runId){labState.run=await labRequest('/api/runs/'+encodeURIComponent(runId));if(state.page!=='labs')return;}
    if(labState.run){renderRun();scheduleRunPoll();}
  }catch(error){labError(error);}
}

function renderLabSetup() {
  const options=labState.options, material=labState.snapshot?.episode||options.episodes.find(e=>e.id===labState.episodeId)||options.episode;
  const available=options.providers.filter(provider=>provider.configured);
  const chosen=available.find(provider=>provider.id===labState.snapshot?.provider)||available.find(provider=>provider.id==='saved')||available.find(provider=>provider.id==='cerebras')||available[0]||options.providers[0];
  $('memory-setup').innerHTML=`${labState.snapshot?`<div class="check-summary"><strong>Повтор сохранённого снимка ${escapeHTML(labState.snapshot.id.slice(0,8))}</strong><p class="small-note">Материал берётся из старого прогона, включая прежние версии файлов.</p><button type="button" class="link-button" id="current-snapshot">Вернуться к текущим источникам</button></div>`:''}<label class="form-label" for="lab-episode">Сценарий</label><select id="lab-episode" class="text-input" ${labState.snapshot?'disabled':''}>${options.episodes.map(e=>`<option value="${e.id}" ${e.id===material.id?'selected':''}>${escapeHTML(e.label||e.id)}</option>`).join('')}</select>${materialHTML(material)}<details class="source-details"><summary>Детерминированные записи и способ их подготовки</summary><p class="small-note">${escapeHTML(material.record_preparation||'Нет в старом снимке')}</p><pre class="raw-source">${escapeHTML(material.record_context||'')}</pre></details><form id="memory-form"><div class="form-grid"><div><label class="form-label" for="provider">Сервис</label><select class="text-input" id="provider">${options.providers.map(provider=>`<option value="${provider.id}" ${provider.id===chosen.id?'selected':''} ${!provider.configured?'disabled':''}>${escapeHTML(provider.label||provider.id)}${provider.configured?' · настроен':' · не настроен'}</option>`).join('')}</select></div><div><label class="form-label" for="model">Имя модели</label><input class="text-input" id="model" required maxlength="160" value="${escapeHTML(labState.snapshot?.model||chosen.model)}" placeholder="Имя из API сервиса"></div><div><label class="form-label" for="summary-budget">Предел краткой памяти, символы</label><input class="text-input" id="summary-budget" type="number" min="1500" max="12000" step="1" required value="${labState.snapshot?.summary_characters||12000}"></div><div><label class="form-label" for="repeats">Повторы каждого условия</label><select class="text-input" id="repeats"><option value="1">1 · проверка прохождения</option><option value="3">3 · пилот</option></select></div><div><label class="form-label" for="call-interval">Пауза между вызовами, секунды</label><input class="text-input" id="call-interval" type="number" min="0" max="120" step="1" required value="${labState.snapshot?.min_interval_seconds??(chosen.id==='cerebras'?60:0)}"></div></div><fieldset class="condition-picker"><legend>Условия сравнения</legend>${Object.entries(CONDITION_NAMES).map(([key,label])=>`<label class="checkbox-label"><input name="lab-condition" type="checkbox" value="${key}" ${(labState.snapshot?.conditions||['full','exact']).includes(key)?'checked':''} ${key==='exact'&&!material.exact_context?'disabled':''}>${escapeHTML(label)}</label>`).join('')}</fieldset><div id="lab-size-assessment" class="check-message"></div><p class="small-note lab-destination" id="provider-info"></p><p class="small-note">Все шесть условий: 2 сжатия, 6 продолжений и запрос на чтение — максимум 9 вызовов на повтор. До 3 повторов и 27 вызовов; предел времени — 30 минут. Фактический предел зависит от выбранных условий. Бюджет краткой памяти относится к сохранённой истории; новые данные добавляются всем вариантам отдельно и учитываются в полном объёме запросов. Детерминированные записи заранее подготовлены автором сценария: эту затрату нельзя считать нулевой стоимостью создания памяти. Предел ответа: 3000 токенов для сжатия, 4500 для продолжения. Пауза помогает укладываться в частоту сервиса, но не гарантирует квоту. Автоматических повторов при ошибке нет. Цена в валюте пока неизвестна.</p><div class="button-row lab-actions"><button class="primary-button" type="submit" ${!available.length||labState.starting||(labState.run&&isRunning(labState.run))?'disabled':''}>Запустить опыт →</button><button class="secondary-button" type="button" id="refresh-material">Обновить предпросмотр</button></div></form>`;
  showProviderInfo();showContextNeed();
}

function showContextNeed(){
  if(!$('lab-size-assessment'))return;
  const material=labState.snapshot?.episode||labState.options.episodes.find(e=>e.id===labState.episodeId)||labState.options.episode;
  const budget=Number($('summary-budget').value), exact=material.exact_context?.context.length;
  const chosen=[...document.querySelectorAll('[name=lab-condition]:checked')].map(e=>e.value);
  const compress=['summary','structured'].filter(k=>chosen.includes(k)||(k==='structured'&&chosen.includes('retrieval'))).length;
  const calls=(chosen.length+compress+(chosen.includes('retrieval')?1:0))*Number($('repeats').value);
  $('lab-size-assessment').textContent=`Исходная история: ${material.characters} символов; бюджет памяти: ${budget}. `+(material.characters<=budget?'Исходник уже помещается: по размеру сжатие не требуется. ':`Нужен отбор или сжатие. `)+(exact!==undefined?`Точный отбор автора: ${exact} символов ${exact<=budget?'— помещается':'— превышает бюджет'}. `:'В этом старом снимке нет точного формата. ')+`Выбрано до ${calls} API-вызовов. По умолчанию — контроль и точные записи; остальные методы выбираются для сравнения. Это оценка размера, а не доказательство достаточности отбора.`;
}

function showProviderInfo(){
  const provider=labState.options.providers.find(item=>item.id===$('provider').value);
  $('provider-info').textContent=`При запуске материал уйдёт в ${provider.endpoint}. Наличие ключа не подтверждает доступ или квоту. Ключ остаётся на локальном сервере.`;
  const profile=labState.snapshot?labState.snapshot.reader_profile:labState.options.reader_profile;
  if(provider.id==='saved'&&profile){
    $('provider-info').insertAdjacentHTML('beforeend',`<details><summary>Профиль читателя в запросе · версия ${profile.revision}</summary><pre class="raw-source">${escapeHTML(JSON.stringify(profile,null,2))}</pre></details>`);
  }
}

async function refreshRuns(){
  const data=await labRequest('/api/runs');if(!$('saved-runs'))return;
  const active=data.runs.find(isRunning);
  if(!labState.run&&active){labState.run=await labRequest('/api/runs/'+active.id);}
  $('saved-runs').innerHTML=data.runs.length?`<details class="source-details"><summary>Сохранённые прогоны · ${data.runs.length}</summary><div class="run-list">${data.runs.map(run=>`<button type="button" class="run-link" data-run="${run.id}"><strong>${escapeHTML(run.model)}</strong><span>${escapeHTML(run.episode_id||'protocol-pilot')} · ${escapeHTML(RUN_STATUS[run.status]||run.status)} · ${run.calls}/${run.max_calls} вызовов</span><small>${escapeHTML(new Date(run.created_at).toLocaleString('ru'))} · ${run.id.slice(0,8)} ↗</small></button>`).join('')}</div></details>`:'<p class="small-note">Сохранённых прогонов пока нет.</p>';
}

function isRunning(run){return ['prepared','running'].includes(run.status);}
function sumUsage(events,key){const known=events.filter(event=>typeof event[key]==='number');const subtotal=known.reduce((sum,event)=>sum+event[key],0);return known.length===events.length&&events.length?subtotal.toLocaleString('ru'):`неизвестно${known.length?` · известная часть ${subtotal.toLocaleString('ru')}`:''}`;}

function renderRun(){
  const run=labState.run;if(!$('memory-run')||!run)return;
  const active=isRunning(run);
  $('memory-run').innerHTML=`<section class="run-report"><div class="section-heading"><h3>Прогон ${escapeHTML(run.id.slice(0,8))}</h3>${badge(RUN_STATUS[run.status]||run.status,run.status==='failed'?'proposal':'neutral')}</div><p class="small-note">Статус завершения относится к процедурам. Исходы каждого варианта и смысл ответов оцениваются отдельно.</p><div class="run-stats"><div><strong>${run.calls} / ${run.max_calls}</strong><span>вызовов, включая сжатие</span></div><div><strong>${escapeHTML(sumUsage(run.events,'input_tokens'))}</strong><span>входных токенов</span></div><div><strong>${escapeHTML(sumUsage(run.events,'output_tokens'))}</strong><span>выходных токенов</span></div></div><p class="small-note">Сервис: ${escapeHTML(run.provider)} · запрошенная модель: ${escapeHTML(run.model)}${run.elapsed_seconds!==undefined?` · ${run.elapsed_seconds} с`:''} · стоимость неизвестна. Кэшированные токены могут входить во входные; дополнительно к ним не прибавляются.</p>${run.waiting_until?`<p class="check-summary">Пауза перед ${escapeHTML(run.waiting_stage)}. Следующий вызов не раньше ${escapeHTML(new Date(run.waiting_until).toLocaleTimeString('ru'))}.</p>`:''}${run.error?`<div class="check-message">${escapeHTML(run.error)}</div>`:''}${active?`<div class="button-row lab-actions"><button type="button" class="secondary-button" id="cancel-run" ${run.cancel_requested?'disabled':''}>${run.cancel_requested?'Остановка запрошена':'Остановить опыт'}</button><span class="small-note">Текущий запрос может завершиться; новые вызовы после остановки не начнутся.</span></div>`:`<button type="button" class="secondary-button lab-actions" id="repeat-snapshot">Повторить на этом снимке</button>`}<div class="button-row lab-actions"><a class="secondary-button" download="protocol-run-${run.id}.json" href="/api/runs/${run.id}">Сохранить полный отчёт JSON</a></div><p class="version">Версия движка ${escapeHTML((run.engine_revision||'не записана').slice(0,12))}</p><details class="source-details"><summary>Исходный снимок прогона</summary>${materialHTML(run.episode)}</details><div class="results-grid">${run.results.map(result=>`<article class="result-card"><div class="eyebrow">ПОВТОР ${result.repeat}</div><h3>${escapeHTML(CONDITION_NAMES[result.condition])}</h3><p class="small-note">${result.characters.toLocaleString('ru')} символов переданного контекста${result.retained_memory_characters!==undefined?` · память ${result.retained_memory_characters} / ${run.summary_characters}, новые данные отдельно`:``} · ${escapeHTML(result.actual_model||'фактическая модель неизвестна')}</p>${result.status==='preparation_failed'?'<div class="check-message">Предел краткой памяти превышен. Текст сохранён целиком; продолжение для этого условия не запускалось.</div>':''}${result.validation_error?`<div class="check-message">Ответ сохранён, проверка ссылок отклонена: ${escapeHTML(result.validation_error)}</div>`:''}${result.status==='retrieval_failed'?'<div class="check-message">Запрос чтения не выполнен; причина сохранена в журнале чтения.</div>':''}<div class="checks-list">${Object.entries(result.checks).map(([key,value])=>`<span>${escapeHTML(CHECK_NAMES[key]||key)}: <b>${escapeHTML(VERDICTS[value]||value)}</b></span>`).join('')}</div><details class="source-details"><summary>Переданный контекст</summary><pre class="raw-source">${escapeHTML(result.context)}</pre></details><details class="source-details" ${result.status==='completed'?'open':''}><summary>Ответ новой сессии</summary><pre class="raw-source response-text">${escapeHTML(result.response||'Ответа нет.')}</pre></details>${result.resolved_response?`<details class="source-details"><summary>Проверенная расшифровка ссылок и статусов</summary><p class="small-note">Исходные записи раскрыты программой. Смысл новых выводов не проверен.</p><pre class="raw-source">${escapeHTML(JSON.stringify(result.resolved_response,null,2))}</pre></details>`:''}${Object.keys(run.review[result.key]||{}).length?`<p class="small-note">Ручных оценок: ${Object.keys(run.review[result.key]).length} / ${run.criteria.length}</p>`:''}</article>`).join('')}</div><details class="source-details"><summary>Журнал чтения · ${(run.read_events||[]).length}</summary><pre class="raw-source">${escapeHTML(JSON.stringify(run.read_events||[],null,2))}</pre></details><details class="source-details"><summary>Журнал всех вызовов · ${run.events.length}</summary>${run.events.map(event=>`<details class="source-details"><summary>${escapeHTML(event.stage)} · ${escapeHTML(event.status)} · ${escapeHTML(event.actual_model||event.requested_model)}</summary><pre class="raw-source">${escapeHTML(JSON.stringify(event,null,2))}</pre></details>`).join('')}</details></section>`;
  renderReview();
  const start=$('memory-form')?.querySelector('button[type=submit]');if(start)start.disabled=active;
}

function renderReview(){
  const run=labState.run, results=run.results.filter(result=>result.status==='completed');
  if(isRunning(run)||!results.length){$('memory-review').innerHTML='';return;}
  $('memory-review').innerHTML=`<details class="source-details"><summary>Оценить смысл ответов вручную</summary><p class="small-note">Автоматические проверки выше относятся к форме ответа. Человек оценивает применение правила и сохраняет точную цитату. Общий балл не вычисляется.</p><form id="review-form"><label class="form-label" for="review-result">Ответ</label><select class="text-input" id="review-result">${results.map(result=>`<option value="${escapeHTML(result.key)}">Повтор ${result.repeat} · ${escapeHTML(CONDITION_NAMES[result.condition])}</option>`).join('')}</select><label class="form-label" for="review-criterion">Критерий</label><select class="text-input" id="review-criterion">${run.criteria.map(criterion=>`<option value="${criterion.id}">${escapeHTML(criterion.text)}</option>`).join('')}</select><p class="small-note" id="criterion-source"></p><label class="form-label" for="review-verdict">Оценка</label><select class="text-input" id="review-verdict"><option value="unknown">Не проверено</option><option value="pass">Пройдено</option><option value="fail">Не пройдено</option></select><label class="form-label" for="review-quote">Точная цитата из ответа</label><textarea class="draft-input" id="review-quote" maxlength="4000" placeholder="Обязательна для оценки «пройдено» или «не пройдено»"></textarea><button type="submit" class="primary-button lab-actions">Сохранить оценку</button><p id="review-message" class="small-note" role="status"></p></form><details class="source-details"><summary>Сохранённые оценки с основаниями</summary><pre id="saved-review" class="raw-source">${escapeHTML(JSON.stringify(run.review,null,2))}</pre></details></details>`;
  showExistingReview();
}

function showExistingReview(){
  const criterion=labState.run.criteria.find(item=>item.id===$('review-criterion').value);
  $('criterion-source').textContent='Основание критерия: '+criterion.source;
  const saved=labState.run.review[$('review-result').value]?.[criterion.id];
  $('review-verdict').value=saved?.verdict||'unknown';$('review-quote').value=saved?.quote||'';
}

function scheduleRunPoll(){
  clearTimeout(labState.timer);
  if(state.page!=='labs'||!labState.run||!isRunning(labState.run))return;
  labState.timer=setTimeout(async()=>{
    try{
      const previous=labState.run;labState.run=await labRequest('/api/runs/'+previous.id);
      if(state.page!=='labs')return;
      // Avoid resetting details or selections when no visible state changed.
      if(JSON.stringify(previous)!==JSON.stringify(labState.run))renderRun();
      if(!isRunning(labState.run)){await refreshRuns();await renderComparison();}scheduleRunPoll();
    }catch(error){labError(error);}
  },2000);
}

async function startMemoryRun(form){
  labState.starting=true;const button=form.querySelector('button[type=submit]');button.disabled=true;$('memory-error').innerHTML='';
  try{
    const material=labState.snapshot?.episode||labState.options.episodes.find(e=>e.id===labState.episodeId)||labState.options.episode;
    labState.run=await labRequest('/api/memory-run',{episode_id:material.id,expected_reader_revision:labState.options.reader_profile?.revision,conditions:[...document.querySelectorAll('[name=lab-condition]:checked')].map(e=>e.value),provider:$('provider').value,model:$('model').value.trim(),summary_characters:Number($('summary-budget').value),repeats:Number($('repeats').value),min_interval_seconds:Number($('call-interval').value),catalog_revision:material.catalog_revision,...(labState.snapshot?{snapshot_run_id:labState.snapshot.id}:{})});
    if(state.page==='labs'){renderRun();await refreshRuns();scheduleRunPoll();$('memory-run').scrollIntoView({behavior:'smooth',block:'start'});}
  }catch(error){labError(error);button.disabled=false;}finally{labState.starting=false;}
}

document.addEventListener('input',event=>{if(event.target.id==='summary-budget')showContextNeed();});
document.addEventListener('change',event=>{
  if(event.target.name==='lab-condition'||event.target.id==='repeats')showContextNeed();
  if(event.target.id==='lab-episode'){labState.episodeId=event.target.value;renderLabSetup();}
  if(event.target.id==='provider'){const provider=labState.options.providers.find(item=>item.id===event.target.value);$('model').value=provider.model;$('call-interval').value=provider.id==='cerebras'?'60':'0';showProviderInfo();}
  if(['review-result','review-criterion'].includes(event.target.id))showExistingReview();
});
document.addEventListener('submit',async event=>{
  if(event.target.id==='memory-form'){event.preventDefault();startMemoryRun(event.target);}
  if(event.target.id==='review-form'){
    event.preventDefault();const button=event.target.querySelector('button[type=submit]');button.disabled=true;
    try{labState.run=await labRequest(`/api/runs/${labState.run.id}/review`,{result_key:$('review-result').value,criterion:$('review-criterion').value,verdict:$('review-verdict').value,quote:$('review-quote').value});$('saved-review').textContent=JSON.stringify(labState.run.review,null,2);$('review-message').textContent='Оценка с цитатой сохранена.';}
    catch(error){$('review-message').textContent=error.message;}finally{button.disabled=false;}
  }
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  try{
    if(button.dataset.episode){labState.snapshot=null;labState.episodeId=button.dataset.episode;renderLabSetup();$('memory-setup').scrollIntoView({block:'start'});}
    if(button.dataset.run){labState.run=await labRequest('/api/runs/'+button.dataset.run);renderRun();scheduleRunPoll();$('memory-run').scrollIntoView({behavior:'smooth',block:'start'});}
    if(button.id==='cancel-run'){labState.run=await labRequest(`/api/runs/${labState.run.id}/cancel`,{});renderRun();scheduleRunPoll();}
    if(button.id==='repeat-snapshot'){labState.snapshot=labState.run;renderLabSetup();$('memory-setup').scrollIntoView({behavior:'smooth',block:'start'});}
    if(button.id==='current-snapshot'){labState.snapshot=null;renderLabSetup();}
    if(button.id==='refresh-material'){labState.options=await labRequest('/api/lab-options');renderLabSetup();}
  }catch(error){labError(error);}
});

async function renderComparison(){
  const data=await labRequest('/api/comparison');if(!$('comparison-report'))return;
  $('comparison-report').innerHTML=`<p class="small-note">${escapeHTML(data.scope)} ${escapeHTML(data.conclusion)}</p><div class="table-wrap markdown"><table><thead><tr><th>Эпизод / версия</th><th>Модель / условие</th><th>Завершено / всего</th><th>Форма</th><th>Смысл: да / нет / ?</th><th>API вызовы · вход / выход</th></tr></thead><tbody>${data.groups.map(g=>`<tr><td>${escapeHTML(g.episode_id)}<br><small>${escapeHTML(g.episode_revision.slice(0,8))} · движок ${escapeHTML((g.engine_revision||'').slice(0,8))}<br>бюджет ${g.budget}</small></td><td>${escapeHTML(g.provider)} · ${escapeHTML(g.actual_model||g.requested_model)}<br>${escapeHTML(CONDITION_NAMES[g.condition])}</td><td>${g.completed}/${g.results}</td><td>${g.format_pass}</td><td>${g.meaning.pass} / ${g.meaning.fail} / ${g.meaning.unknown}</td><td>${g.calls} · ${g.input_tokens} / ${g.output_tokens}${g.usage_complete?'':' · известная часть'}</td></tr>`).join('')}</tbody></table></div><button id="comparison-export" class="secondary-button">Экспорт сравнения</button>`;
  $('comparison-export').addEventListener('click',()=>downloadJSON('comparison.json',data));
}
