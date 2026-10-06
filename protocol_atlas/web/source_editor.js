'use strict';

const sourceDrafts = new Map();
let sourcePreviewTimer, sourcePreviewSequence = 0;

async function renderSourceEditor(params) {
  const path=params.get('path');let doc;try{doc=await sourceDocument(path);}catch{doc=null;}
  if(state.page!=='edit')return;
  if(!doc||!path.endsWith('.md')){
    $('main').innerHTML=header('РЕДАКТОР','Документ недоступен','Редактирование доступно для Markdown-документов из каталога.');return;
  }
  let draft=sourceDrafts.get(path);
  if(!draft){const text=textOf(doc).replace(/\r\n/g,'\n');draft={path,sha:doc.sha256,original:text,text,saving:false};sourceDrafts.set(path,draft);}
  $('main').innerHTML=header('РЕДАКТОР РУССКОГО ОРИГИНАЛА',escapeHTML(path),'Измените русский текст Markdown; рядом показано оформление. Кнопка «Сохранить» записывает изменения в исходный файл.')+
    `<div class="button-row"><a class="secondary-button" href="#translate?${new URLSearchParams({path})}">Русский ↔ English</a><button id="source-save" class="primary-button" type="button">Сохранить</button><a class="secondary-button" href="#source?${new URLSearchParams({path,full:'1'})}">К чтению</a><button id="source-discard" class="secondary-button" type="button">Отменить правки</button></div><p id="source-edit-status" class="small-note" role="status"></p><div class="source-editor-grid"><section><label class="form-label" for="source-edit-text">Русский текст документа · Markdown</label><textarea id="source-edit-text" class="source-edit-text" spellcheck="false"></textarea></section><section><h2>Предпросмотр</h2><div data-original id="source-edit-preview" class="source-content markdown">${doc.blocks.map(block=>blockHTML(block,true)).join('')}</div></section></div>`;
  $('source-edit-text').value=draft.text;
  $('source-edit-text').disabled=draft.saving;
  $('source-save').disabled=draft.saving;
  updateSourceEditStatus(draft);
  previewSourceDraft(draft);
  if(typeof mountAIEditor==='function')mountAIEditor(draft);
}

function currentSourceDraft(){return state.page==='edit'?sourceDrafts.get(new URLSearchParams(location.hash.split('?')[1]).get('path')):null;}
function updateSourceEditStatus(draft){
  if(currentSourceDraft()!==draft)return;
  const stale=docByPath(draft.path)?.sha256!==draft.sha;
  $('source-edit-status').textContent=stale?'Файл изменился после открытия черновика. Скопируйте правки перед загрузкой новой версии.':draft.text===draft.original?'Изменений нет.':'Есть несохранённые изменения. При переходе к другим страницам черновик остаётся до закрытия вкладки.';
}

async function sourceEditAPI(action,payload){
  const response=await fetch('/api/source/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||'Не удалось выполнить действие.');
  return result;
}

async function previewSourceDraft(draft){
  const sequence=++sourcePreviewSequence;
  try{
    const preview=await sourceEditAPI('preview',{path:draft.path,text:draft.text});
    if(sequence!==sourcePreviewSequence||currentSourceDraft()!==draft)return;
    $('source-edit-preview').innerHTML=preview.blocks.map(block=>blockHTML(block,true)).join('');
  }catch(error){
    if(sequence===sourcePreviewSequence&&currentSourceDraft()===draft)$('source-edit-status').textContent=error.message;
  }
}

document.addEventListener('input',event=>{
  if(event.target.id!=='source-edit-text')return;
  const draft=currentSourceDraft();if(!draft)return;
  draft.text=event.target.value;updateSourceEditStatus(draft);
  clearTimeout(sourcePreviewTimer);sourcePreviewTimer=setTimeout(()=>previewSourceDraft(draft),250);
});

document.addEventListener('click',async event=>{
  const button=event.target.closest('button');
  if(!button||!['source-save','source-discard'].includes(button.id))return;
  const draft=currentSourceDraft();if(!draft||draft.saving)return;
  if(button.id==='source-discard'){
    sourceDrafts.delete(draft.path);renderSourceEditor(new URLSearchParams({path:draft.path}));return;
  }
  draft.saving=true;button.disabled=true;$('source-edit-text').disabled=true;$('source-discard').disabled=true;
  $('source-edit-status').textContent='Сохраняем документ…';
  try{
    const result=await sourceEditAPI('save',{path:draft.path,text:draft.text,expected_sha256:draft.sha});
    if(extraSources.has(draft.path))extraSources.set(draft.path,result.document);
    draft.sha=result.document.sha256;draft.original=textOf(result.document).replace(/\r\n/g,'\n');draft.text=draft.original;
    await loadCatalog(true);
    if(currentSourceDraft()===draft){
      $('source-edit-status').textContent=result.changed?'Сохранено в исходный файл. Прежняя версия: '+result.backup:'Изменений нет; файл не перезаписан.';
    }
  }catch(error){if(currentSourceDraft()===draft)$('source-edit-status').textContent=error.message;}
  finally{
    draft.saving=false;
    if(currentSourceDraft()===draft){$('source-save').disabled=false;$('source-edit-text').disabled=false;$('source-discard').disabled=false;}
  }
});

window.addEventListener('beforeunload',event=>{
  if([...sourceDrafts.values()].some(draft=>draft.text!==draft.original)){event.preventDefault();event.returnValue='';}
});
