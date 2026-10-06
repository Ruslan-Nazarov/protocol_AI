'use strict';

const aiEditorState=new Map();
let aiEditorPoll;
const AI_PROVIDERS={custom:'Другой сервис или локальная модель',openai:'OpenAI',groq:'Groq',cerebras:'Cerebras'};
const AI_MODES={full:'Полный текст',excerpts:'Фрагменты',omitted:'Не передан'};
const AI_STATUSES={running:'ИИ анализирует',ready:'Предложения готовы',failed:'Операция не завершена',applied:'Правки применены',undone:'Правки отменены',applying:'Сохраняем правки'};

async function aiEditorAPI(path,payload){
  const response=await fetch('/api/editor/'+path,payload?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}:{cache:'no-store'});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Не удалось выполнить действие редактора.');return result;
}
function currentAIState(){const draft=currentSourceDraft();return draft?aiEditorState.get(draft.path):null;}
function aiEditorPayload(){
  const draft=currentSourceDraft(),local=currentAIState();
  return {path:draft.path,text:draft.text,expected_sha256:draft.sha,intent:local.intent||'',language:AtlasI18n.language,paths:[...local.paths]};
}
function aiCoverageHTML(plan){
  return `${runtimeManifestHTML(plan.runtime)}<p class="small-note">Объём передаваемого текста: ${plan.characters} символов. Предел: ${plan.limit}.</p><details><summary>Какие источники получит ИИ</summary><ul class="ai-source-list">${plan.coverage.map(item=>`<li><code>${escapeHTML(item.path)}</code> — ${AI_MODES[item.mode]}${item.ranges.length?' · '+item.ranges.map(range=>range.join('–')).join(', '):''}</li>`).join('')}</ul>${plan.unselected?.length?`<p class="small-note">Вне выбранной области: ${plan.unselected.map(escapeHTML).join(', ')}</p>`:''}</details>`;
}
async function mountAIEditor(draft){
  clearTimeout(aiEditorPoll);
  let local=aiEditorState.get(draft.path);
  if(!local){local={intent:'',paths:null,job:null,busy:false};aiEditorState.set(draft.path,local);}
  const grid=$('main').querySelector('.source-editor-grid');
  grid.insertAdjacentHTML('beforebegin',`<section id="ai-editor" class="card ai-editor"><div class="section-heading"><h2>Редактирование с ИИ</h2><a href="#source?path=docs%2FAI_EDITING.md&full=1">Как это работает →</a></div><p>Исправьте текст ниже или опишите нужную правку. ИИ предложит изменения в связанных документах; выберите, что применить.</p><details id="ai-settings"><summary>Мой ИИ · API и модель</summary><div id="ai-settings-fields"><p class="small-note">Читаем настройки…</p></div></details><label class="form-label" for="ai-intent">Что меняем и почему?</label><textarea id="ai-intent" class="draft-input compact" maxlength="4000" placeholder="Например: уточнить область действия правила и проверить связанные инструкции…"></textarea><details><summary>Область анализа</summary><div id="ai-source-options" class="ai-source-list"></div></details><p id="ai-provider-note" class="small-note"></p><div class="button-row"><button class="secondary-button" type="button" id="ai-preview">Показать область анализа</button><button class="primary-button" type="button" id="ai-analyze">Найти связанные правки</button></div><p id="ai-editor-status" class="small-note" role="status"></p><div id="ai-coverage"></div><div id="ai-result"></div><details><summary>История изменений с ИИ</summary><div id="ai-history"></div></details></section>`);
  $('ai-intent').value=local.intent;
  try{
    const [settings,inventory,history]=await Promise.all([aiEditorAPI('settings'),aiEditorAPI('sources'),aiEditorAPI('changes?'+new URLSearchParams({path:draft.path}))]);
    if(currentSourceDraft()!==draft)return;
    local.settings=settings;
    if(!local.paths)local.paths=new Set(inventory.sources.filter(item=>item.path!=='PROTOCOL.md'||item.path===draft.path).map(item=>item.path));
    $('ai-source-options').innerHTML=inventory.sources.map(item=>`<label class="checkbox-label"><input type="checkbox" data-ai-source="${escapeHTML(item.path)}" ${local.paths.has(item.path)?'checked':''} ${item.path===draft.path?'disabled':''}><code>${escapeHTML(item.path)}</code>${item.history?' · История':!item.editable?' · Код':''}</label>`).join('');
    renderAISettings(settings);
    $('ai-history').innerHTML=history.changes.length?history.changes.map(item=>`<p><button class="link-button" type="button" data-ai-job="${item.id}">${new Date(item.created_at).toLocaleString(AtlasI18n.language)} · ${AI_STATUSES[item.status]||item.status}</button></p>`).join(''):'<p class="small-note">Сохранённых изменений пока нет.</p>';
    if(!local.job&&history.changes.length)local.job=await aiEditorAPI('changes/'+history.changes[0].id);
    if(local.preview)$('ai-coverage').innerHTML=aiCoverageHTML(local.preview);
    if(local.job)renderAIJob(local.job);
    if(!settings.configured)$('ai-settings').open=true;
  }catch(error){if($('ai-editor-status'))$('ai-editor-status').textContent=error.message;}
}
function renderAISettings(settings){
  const local=currentAIState();if(!local)return;local.settings=settings;
  $('ai-settings-fields').innerHTML=`<label class="form-label" for="ai-provider">Сервис ИИ</label><select class="text-input" id="ai-provider">${Object.entries(AI_PROVIDERS).map(([value,label])=>`<option value="${value}">${label}</option>`).join('')}</select><div id="ai-endpoint-field"><label class="form-label" for="ai-endpoint">Базовый адрес API</label><input id="ai-endpoint" class="text-input" type="url" placeholder="https://example.com/v1"><p class="small-note">API формата Chat Completions. Для локальной модели можно указать http://127.0.0.1:порт/v1.</p></div><label class="form-label" for="ai-model">Имя модели</label><input id="ai-model" class="text-input" maxlength="160" autocomplete="off"><label class="form-label" for="ai-key">Мой API-ключ</label><input id="ai-key" class="text-input" type="password" maxlength="2000" autocomplete="new-password" placeholder="Новый ключ или пусто — сохранить прежний"><p class="small-note">Ключ сохраняется на этом компьютере. Для локального API без авторизации поле можно оставить пустым.</p><label class="checkbox-label"><input id="ai-clear-key" type="checkbox">Удалить сохранённый ключ</label><details><summary>Параметры ответа</summary><label class="form-label" for="ai-output">Предел ответа, токенов</label><input id="ai-output" class="text-input" type="number" min="1000" max="16000"><label class="checkbox-label"><input id="ai-json" type="checkbox">Запросить JSON-режим, если сервис поддерживает</label></details><div class="button-row"><button id="ai-settings-save" class="secondary-button" type="button">Сохранить подключение ИИ</button></div><p id="ai-settings-status" class="small-note" role="status"></p>`;
  $('ai-provider').value=settings.provider;$('ai-endpoint').value=settings.endpoint;$('ai-model').value=settings.model;$('ai-output').value=settings.max_output;$('ai-json').checked=settings.json_mode;
  $('ai-endpoint-field').hidden=settings.provider!=='custom';
  $('ai-settings-status').textContent=settings.key_source==='project'?'Используется настроенный ключ проекта.':settings.key_configured?'API-ключ настроен.':'';
  $('ai-provider-note').textContent=settings.configured?AtlasI18n.text('При запуске ИИ получит вашу правку и источники из выбранной области. Сервис: ')+settings.endpoint+' · '+settings.model:AtlasI18n.text('Сначала выберите сервис, модель и настройте подключение выше.');
}
function renderAIJob(job){
  const local=currentAIState();if(!local||job.path!==currentSourceDraft().path)return;local.job=job;
  $('ai-editor-status').textContent=AI_STATUSES[job.status]||job.status;
  $('ai-analyze').disabled=local.busy||job.status==='running';
  const target=$('ai-result');
  if(job.status==='running'){
    target.innerHTML='<p class="small-note">Один запрос к выбранному сервису. Результат сохранится в истории; документы остаются без изменений.</p>';
    clearTimeout(aiEditorPoll);aiEditorPoll=setTimeout(()=>pollAIJob(job.id,job.path),1500);return;
  }
  if(job.status==='failed'){target.innerHTML=`<p role="alert">${escapeHTML(job.error)}</p>`;return;}
  target.innerHTML=`<div class="ai-proposal"><h3>Предложение изменения</h3><p data-original>${escapeHTML(job.summary||'')}</p><p class="small-note">Фактическая модель: <span data-original>${escapeHTML(job.actual_model||'Не сообщена')}</span> · Входные токены: ${job.input_tokens??'Не сообщены'} · Выходные токены: ${job.output_tokens??'Не сообщены'}</p>${aiCoverageHTML(job)}${job.patches.map(patch=>`<article class="ai-patch"><label class="checkbox-label"><input type="checkbox" data-ai-patch="${patch.id}" ${patch.origin==='human'?'checked':''} ${job.status!=='ready'||!patch.applicable?'disabled':''}><strong data-original>${escapeHTML(patch.path)}</strong><span>${patch.origin==='human'?'Ваша правка':patch.relation==='direct'?'Связанная правка':'Возможная связь'}</span></label><p data-original>${escapeHTML(patch.reason)}</p>${!patch.applicable?'<p class="small-note">Нужна отдельная доработка кода или исторической записи.</p>':''}<details><summary>Было → стало</summary><div class="ai-diff"><section><h4>Было</h4><pre><code>${escapeHTML(patch.before)}</code></pre></section><section><h4>Стало</h4><pre><code>${escapeHTML(patch.after)}</code></pre></section></div></details></article>`).join('')}${job.unresolved?.length?`<h3>Что остаётся открытым</h3><ul data-original>${job.unresolved.map(item=>`<li>${escapeHTML(item)}</li>`).join('')}</ul>`:''}${job.status==='ready'?'<p class="small-note">Выбранные правки сохранятся в файлы. Невыбранные останутся в истории предложения. Смысловую согласованность оценивает человек.</p><button id="ai-apply" class="primary-button" type="button">Применить выбранные правки</button>':job.status==='applied'?`<p class="check-summary">Изменённые документы: ${job.saved.map(item=>escapeHTML(item.path)).join(', ')}. Проверьте переводы и пересмотр записей памяти.</p><div class="button-row"><a class="secondary-button" href="#translations">Обновить переводы</a><a class="secondary-button" href="#records">Проверить память</a><button id="ai-undo" class="secondary-button" type="button">Отменить это изменение</button></div>${job.remaining.length?'<p class="small-note">В предложении остались неприменённые правки.</p>':''}`:''}</div>`;
}
async function pollAIJob(id,path){
  if(state.page!=='edit'||currentSourceDraft()?.path!==path)return;
  try{renderAIJob(await aiEditorAPI('changes/'+id));}
  catch(error){$('ai-editor-status').textContent=error.message;}
}
document.addEventListener('input',event=>{
  const local=currentAIState();if(event.target.id==='ai-intent'&&local)local.intent=event.target.value;
});
document.addEventListener('change',event=>{
  if(event.target.id==='ai-provider')$('ai-endpoint-field').hidden=event.target.value!=='custom';
  if(event.target.dataset.aiSource){const local=currentAIState();event.target.checked?local.paths.add(event.target.dataset.aiSource):local.paths.delete(event.target.dataset.aiSource);}
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.aiJob){try{renderAIJob(await aiEditorAPI('changes/'+button.dataset.aiJob));}catch(error){$('ai-editor-status').textContent=error.message;}return;}
  if(!['ai-settings-save','ai-preview','ai-analyze','ai-apply','ai-undo'].includes(button.id))return;
  const local=currentAIState(),draft=currentSourceDraft();if(!local||local.busy)return;
  local.busy=true;button.disabled=true;$('ai-editor-status').textContent='Выполняем действие…';
  try{
    if(button.id==='ai-settings-save'){
      const settings=await aiEditorAPI('settings',{provider:$('ai-provider').value,endpoint:$('ai-endpoint').value,model:$('ai-model').value,api_key:$('ai-key').value,clear_key:$('ai-clear-key').checked,json_mode:$('ai-json').checked,max_output:Number($('ai-output').value),expected_revision:local.settings.revision});
      $('ai-key').value='';renderAISettings(settings);$('ai-settings-status').textContent='Подключение сохранено. Вызов ИИ ещё не выполнялся.';
    }else if(button.id==='ai-preview'){
      local.preview=await aiEditorAPI('preview',aiEditorPayload());$('ai-coverage').innerHTML=aiCoverageHTML(local.preview);
    }else if(button.id==='ai-analyze'){
      const payload=aiEditorPayload();local.preview=await aiEditorAPI('preview',payload);$('ai-coverage').innerHTML=aiCoverageHTML(local.preview);
      renderAIJob(await aiEditorAPI('analyze',payload));
    }else{
      if(button.id==='ai-apply'&&draft.text!==local.job.draft)throw Error('Черновик изменился после анализа. Повторите анализ, чтобы сохранить новые правки.');
      const result=await aiEditorAPI(button.id==='ai-undo'?'undo':'apply',{id:local.job.id,selected:[...document.querySelectorAll('[data-ai-patch]:checked:not(:disabled)')].map(input=>input.dataset.aiPatch)});
      // sourceDocument may use the old catalog; reload before resetting the draft.
      await loadCatalog(true);
      const updated=await sourceDocument(draft.path);
      draft.sha=updated.sha256;draft.original=normalizeSourceText(textOf(updated));draft.text=draft.original;
      sourceDrafts.set(draft.path,draft);local.job=result;renderSourceEditor(new URLSearchParams({path:draft.path}));
    }
  }catch(error){if($('ai-editor-status'))$('ai-editor-status').textContent=error.message;}
  finally{local.busy=false;if(button.isConnected)button.disabled=false;if($('ai-analyze'))$('ai-analyze').disabled=local.job?.status==='running';}
});
function normalizeSourceText(text){return text.replace(/\r\n/g,'\n');}
