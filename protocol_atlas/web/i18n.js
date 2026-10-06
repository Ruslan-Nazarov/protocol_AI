'use strict';
// Source strings stay in Russian. Only the presentation layer uses this catalog.
// English document units are accepted only against their saved Russian fingerprint.
const AtlasI18n = (() => {
  let language;try{language=localStorage.getItem('atlas-language')||'ru';}catch{language='ru';}
  let bundle={ui:{entries:[]},documents:[]}, replacements=[], sourceMap=new Map(), unitMap=new Map();
  const nodes=new WeakMap(), attributes=new WeakMap();
  const normalize=value=>value.replace(/\r\n/g,'\n');
  const ignored='textarea,input,pre,code,.raw-source,.comment-quotation,.comment-body,[data-original],[data-translation-content]';
  function rebuild(){
    const map=new Map(bundle.ui.entries.filter(e=>e.translation).map(e=>[e.source,e.translation]));sourceMap=new Map();unitMap=new Map();
    for(const doc of bundle.documents)for(const unit of doc.units){
      if(unit.status!=='current')continue;
      sourceMap.set(normalize(unit.source),unit.translation);
      unitMap.set(unit.id+'::'+normalize(unit.source),unit.translation);
      for(const [ru,en] of [[unit.source.trim(),unit.translation.trim()]]){
        map.set(ru,en);
        if(unit.kind==='heading')map.set(ru.replace(/^#+\s+/,''),en.replace(/^#+\s+/,''));
        if(unit.kind==='heading'){
          const strip=s=>s.replace(/^#+\s+/,'').replace(/^(?:(?:\d+|[А-ЯA-Z])(?:\.\d+)*\.?\s+|[ED]-\d{3}\s*·\s*)/,'');
          map.set(strip(ru),strip(en));
          map.set(ru.replace(/^#+\s+[ED]-\d{3}\s*·\s*/,''),en.replace(/^#+\s+[ED]-\d{3}\s*·\s*/,''));
        }
        const ruLines=ru.split('\n'),enLines=en.split('\n');
        if(ruLines.length===enLines.length&&unit.kind!=='code')for(let i=0;i<ruLines.length;i++){
          const strip=s=>s.replace(/^[-*]\s+/,'').replace(/[*`#]/g,'').trim();
          const a=strip(ruLines[i]),b=strip(enLines[i]);if(!a||!b)continue;map.set(a,b);
          if(/^[А-Яа-яЁё][^:]{0,60}:/.test(a))map.set(a.replace(/^[^:]+:\s*/,''),b.replace(/^[^:]+:\s*/,''));
        }
        if(unit.kind!=='code'){
          const plain=s=>s.replace(/^(?:#{1,6}|[-*]|\d+[.)])\s+/,'').replace(/\[([^\]]+)\]\([^)]+\)/g,'$1').replace(/[*`]/g,'');
          map.set(plain(ru),plain(en));
          const split=s=>s.replace(/^(?:#{1,6}|[-*]|\d+[.)])\s+/,'').split(/(?:\*\*|`|\[|\]\([^)]+\))/);
          const a=split(ru),b=split(en);
          if(a.length===b.length)for(let i=0;i<a.length;i++)if(a[i].trim()&&b[i].trim())map.set(a[i].trim(),b[i].trim());
        }
      }
    }
    replacements=[...map.entries()].filter(([ru,en])=>ru!==en&&/[А-Яа-яЁё]/.test(ru)).sort((a,b)=>b[0].length-a[0].length).map(([ru,en])=>{
      const escaped=ru.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
      return [ru,en,new RegExp((/\p{L}/u.test(ru[0])?'(?<!\\p{L})':'')+escaped+(/\p{L}/u.test(ru.at(-1))?'(?!\\p{L})':''),'gu')];
    });
  }
  function text(value){
    if(language!=='en')return value;
    const exact=replacements.find(([ru])=>ru===value.trim());
    if(exact)return value.replace(exact[0],exact[1]);
    // Fixed fragments of dynamic labels are translated; values and identifiers remain intact.
    let result=value;
    for(const [ru,en,pattern] of replacements)if(ru.length>=4||ru==='ИЗ')result=result.replace(pattern,()=>en);
    result=result.replace(/(\d+)\s+из\s+(\d+)/g,'$1 of $2');
    return result;
  }
  function localize(){
    observer.disconnect();
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    let node;
    while(node=walker.nextNode()){
      if(node.parentElement?.closest(ignored))continue;
      const previous=nodes.get(node);
      const original=previous&&node.nodeValue===previous.rendered?previous.original:node.nodeValue;
      const rendered=text(original);nodes.set(node,{original,rendered});
      if(node.nodeValue!==rendered)node.nodeValue=rendered;
    }
    for(const element of document.querySelectorAll('[placeholder],[title],[aria-label]')){
      if(element.closest('[data-original],[data-translation-content]'))continue;
      const saved=attributes.get(element)||{};
      for(const attr of ['placeholder','title','aria-label']){
        if(!element.hasAttribute(attr))continue;
        const current=element.getAttribute(attr),prev=saved[attr];
        const original=prev&&current===prev.rendered?prev.original:current;
        const rendered=text(original);saved[attr]={original,rendered};
        if(current!==rendered)element.setAttribute(attr,rendered);
      }
      attributes.set(element,saved);
    }
    document.documentElement.lang=language;
    const languageStatus=document.getElementById('language-status');
    if(languageStatus)languageStatus.textContent=bundle.ui.pending?(language==='en'?bundle.ui.pending+' interface messages need translation':bundle.ui.pending+' текстов интерфейса требуют перевода'):'';
    document.title=language==='en'?'Protocol · Connection and development':'Протокол · Подключение и развитие';
    const select=document.getElementById('language-switch');if(select)select.value=language;
    observer.observe(document.body,{subtree:true,childList:true,characterData:true});
  }
  let scheduled=false, readyPromise;
  const observer=new MutationObserver(()=>{if(!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;localize();});}});
  async function refresh(){
    const response=await fetch('/api/translations',{cache:'no-store'});
    if(!response.ok)throw new Error('Translation catalog unavailable');
    bundle=await response.json();rebuild();localize();return bundle;
  }
  function source(value,unit){return language==='en'?(unit?.id?unitMap.get(unit.id+'::'+normalize(value)):sourceMap.get(normalize(value)))??value:value;}
  function translationStatus(path,line,value){
    return bundle.documents.find(d=>d.path===path)?.units.find(u=>u.start_line===line&&normalize(u.source).trim()===normalize(value).trim())?.status||'missing';
  }
  function sourceByLine(path,line,value){
    if(language!=='en')return value;
    const unit=bundle.documents.find(d=>d.path===path)?.units.find(u=>u.start_line===line&&normalize(u.source).trim()===normalize(value).trim());
    return unit?.status==='current'?unit.translation.trim():value;
  }
  async function setLanguage(value){
    language=value==='en'?'en':'ru';try{localStorage.setItem('atlas-language',language);}catch{}
    if(typeof render==='function')render();localize();
  }
  document.addEventListener('DOMContentLoaded',()=>{
    document.getElementById('language-switch').addEventListener('change',event=>setLanguage(event.target.value));
    readyPromise=refresh().then(()=>{if(typeof state!=='undefined'&&state.catalog)render();}).catch(error=>{
      document.getElementById('language-status').textContent=language==='en'?'English catalog unavailable': 'Перевод недоступен';
      console.error(error.message);
    });localize();
  });
  return {get ready(){return readyPromise||Promise.resolve();},get language(){return language;},source,sourceByLine,translationStatus,text,refresh,localize,setLanguage,get documents(){return bundle.documents;},get history(){return bundle.history||{bytes:0,edits:0,legacy_files:0};}};
})();

const translationDrafts=new Map();
async function renderTranslationEditor(params){
  const path=params.get('path')||'PROTOCOL.md';
  const en=AtlasI18n.language==='en',label=(ru,english)=>en?english:ru;
  $('main').innerHTML=header(label('ПЕРЕВОД','TRANSLATION'),escapeHTML(path),label('Русский оригинал и связанный английский перевод. Изменённые фрагменты отмечены отдельно.','Russian source and linked English translation. Changed units are marked separately.'));
  try{
    const response=await fetch('/api/translations?'+new URLSearchParams({path}),{cache:'no-store'});
    const doc=await response.json();if(!response.ok)throw new Error(doc.error);
    if(state.page!=='translate')return;
    const pending=doc.units.filter(u=>u.status!=='current');
    const choices=doc.units.filter(u=>u.source.trim()&&u.kind!=='separator');
    const requested=params.get('unit'),unit=choices.find(u=>u.unit_id===requested)||pending.find(u=>u.source.trim())||choices[0];
    const draftKey=path+'::'+unit.unit_id;
    if(!translationDrafts.has(draftKey))translationDrafts.set(draftKey,{text:unit.translation,original:unit.translation});
    const draft=translationDrafts.get(draftKey);
    const status=s=>label({current:'Актуален',stale:'Обновить',missing:'Нет перевода'}[s],{current:'Current',stale:'Update needed',missing:'Missing'}[s]);
    $('main').insertAdjacentHTML('beforeend',`<div class="button-row"><a class="secondary-button" href="#edit?${new URLSearchParams({path})}">${label('Редактировать русский оригинал','Edit Russian source')}</a><a class="secondary-button" href="#source?${new URLSearchParams({path,full:'1'})}">${label('К чтению','Read document')}</a></div><p>${label('Требуют перевода или обновления:','Need translation or update:')} ${pending.length}</p><label class="form-label" for="translation-unit">${label('Фрагмент','Unit')}</label><select id="translation-unit" data-original class="text-input">${choices.map(u=>`<option value="${escapeHTML(u.unit_id)}" ${u.unit_id===unit.unit_id?'selected':''}>${status(u.status)} · ${u.start_line} · ${escapeHTML(u.source.replace(/^#+\s*/,'').slice(0,95))}</option>`).join('')}</select><div class="source-editor-grid" data-translation-content><section><h2>${label('Русский оригинал сейчас','Current Russian source')}</h2><pre class="translation-original">${escapeHTML(unit.source)}</pre>${unit.status==='stale'?`<details open><summary>${label('Оригинал, с которого сделан перевод','Source used for this translation')}</summary><pre class="translation-original">${escapeHTML(unit.translated_source)}</pre></details>`:''}</section><section><label class="form-label" for="translation-text">English · Markdown</label><textarea id="translation-text" class="source-edit-text" spellcheck="true" lang="en"></textarea><button id="translation-save" class="primary-button" type="button">${label('Сохранить перевод фрагмента','Save unit translation')}</button><p id="translation-status" role="status"></p></section></div>`);
    $('translation-text').value=draft.text;
    $('translation-text').addEventListener('input',event=>{draft.text=event.target.value;});
    $('translation-unit').addEventListener('change',event=>{location.hash='translate?'+new URLSearchParams({path,unit:event.target.value});});
    $('translation-save').addEventListener('click',async event=>{
      event.target.disabled=true;
      try{
        const response=await fetch('/api/translations/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,unit_id:unit.unit_id,translation:draft.text,revision:doc.revision,source_sha256:doc.source_sha256})});
        const result=await response.json();if(!response.ok)throw new Error(result.error);
        draft.original=draft.text;await AtlasI18n.refresh();
        if(state.page==='translate')await renderTranslationEditor(new URLSearchParams({path,unit:unit.unit_id}));
        if($('translation-status'))$('translation-status').textContent=label('Перевод сохранён и связан с текущим оригиналом.','Translation saved against the current source.');
      }catch(error){if($('translation-status'))$('translation-status').textContent=error.message;}
      finally{if(event.target.isConnected)event.target.disabled=false;}
    });
    await renderTranslationHistory(path,unit.unit_id,doc,draftKey,()=>renderTranslationEditor(new URLSearchParams({path,unit:unit.unit_id})));
  }catch(error){$('main').insertAdjacentHTML('beforeend',`<p role="alert">${escapeHTML(error.message)}</p>`);}
}
window.addEventListener('beforeunload',event=>{
  if([...translationDrafts.values()].some(d=>d.text!==d.original)){event.preventDefault();event.returnValue='';}
});
function renderTranslationsOverview(){
  const en=AtlasI18n.language==='en',label=(ru,english)=>en?english:ru;
  $('main').innerHTML=header(label('ДВА ЯЗЫКА','TWO LANGUAGES'),label('Оригиналы и переводы','Sources and translations'),label('Измените русский текст, затем обновите только отмеченные английские фрагменты.','Edit the Russian text, then update only the flagged English units.'))+`<p><a class="secondary-button" href="#translate-ui">${label('Переводы интерфейса','Interface translations')}</a></p><div class="card-grid">${AtlasI18n.documents.map(doc=>`<article class="card"><h2>${escapeHTML(doc.path)}</h2><p>${doc.pending?label('Обновить фрагменты:','Units to update:')+' '+doc.pending:label('Перевод актуален','Translation current')}</p><a class="primary-button" href="#translate?${new URLSearchParams({path:doc.path})}">RU ↔ English</a> <button class="secondary-button" data-export-translation="${escapeHTML(doc.path)}">English Markdown ↓</button></article>`).join('')}</div><p id="translation-export-status" role="status"></p><section><h2>${label('Хранилище истории переводов','Translation history storage')}</h2><p>${label('Размер:','Size:')} ${(AtlasI18n.history.bytes/1000000).toFixed(1)} MB · ${label('Операций:','Operations:')} ${AtlasI18n.history.edits} · ${label('Старых копий в сжатом архиве:','Legacy copies in compressed archive:')} ${AtlasI18n.history.legacy_files}</p><p>${label('Историю и восстановление откройте у нужного фрагмента. Неизменённый перевод не создаёт новую версию; пакетное обновление даёт одну точку истории на документ.','Open a unit to view its history and restore it. Unchanged text creates no version; a batch update creates one checkpoint per document.')}</p></section>`;
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-export-translation]');if(!button)return;
  let doc;
  try{const response=await fetch('/api/translations?'+new URLSearchParams({path:button.dataset.exportTranslation}),{cache:'no-store'});doc=await response.json();if(!response.ok)throw new Error(doc.error);}
  catch(error){$('translation-export-status').textContent=error.message;return;}
  if(doc.pending){$('translation-export-status').textContent=AtlasI18n.language==='en'?'Update all flagged units before exporting English.':'Перед выгрузкой English обновите все отмеченные фрагменты.';return;}
  const text=doc.units.map(u=>u.translation).join('');
  const url=URL.createObjectURL(new Blob([text],{type:'text/markdown;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=doc.path.split('/').pop();link.click();URL.revokeObjectURL(url);
});
async function renderUITranslationEditor(params){
  const en=AtlasI18n.language==='en',label=(ru,english)=>en?english:ru;
  await AtlasI18n.refresh();if(state.page!=='translate-ui')return;
  const response=await fetch('/api/translations',{cache:'no-store'}),bundle=await response.json();
  const entries=bundle.ui.entries.filter(e=>e.source.trim());
  const entry=entries.find(e=>e.id===params.get('id'))||entries.find(e=>!e.translation)||entries[0];
  if(!entry)return;
  const key='ui::'+entry.id;
  if(!translationDrafts.has(key))translationDrafts.set(key,{text:entry.translation,original:entry.translation});
  const draft=translationDrafts.get(key);
  $('main').innerHTML=header(label('ПЕРЕВОД ИНТЕРФЕЙСА','INTERFACE TRANSLATION'),label('Русский текст и English','Russian text and English'),label('Русские подписи задаются в коде сайта. Здесь правится их английский перевод; новые русские подписи отмечаются как отсутствующие.','Russian labels are defined in the site code. Edit their English equivalents here; new Russian labels are marked as missing.'))+`<a href="#translations">← RU ↔ EN</a><p>${label('Нет перевода:','Missing translations:')} ${bundle.ui.pending}</p><label class="form-label" for="ui-translation-choice">${label('Текст интерфейса','Interface message')}</label><select id="ui-translation-choice" data-original class="text-input">${entries.map(e=>`<option value="${e.id}" ${e.id===entry.id?'selected':''}>${e.translation?'✓':'!'} ${escapeHTML(e.source.slice(0,110))}</option>`).join('')}</select><div class="source-editor-grid" data-translation-content><section><h2>Русский</h2><pre class="translation-original">${escapeHTML(entry.source)}</pre></section><section><label class="form-label" for="ui-translation-text">English</label><textarea id="ui-translation-text" class="source-edit-text" lang="en"></textarea><button id="ui-translation-save" class="primary-button">${label('Сохранить перевод','Save translation')}</button><p id="ui-translation-status" role="status"></p></section></div>`;
  $('ui-translation-text').value=draft.text;
  $('ui-translation-text').addEventListener('input',event=>draft.text=event.target.value);
  $('ui-translation-choice').addEventListener('change',event=>location.hash='translate-ui?'+new URLSearchParams({id:event.target.value}));
  $('ui-translation-save').addEventListener('click',async event=>{
    event.target.disabled=true;
    try{
      const response=await fetch('/api/translations/ui/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:entry.id,revision:bundle.ui.revision,translation:draft.text})});
      const result=await response.json();if(!response.ok)throw new Error(result.error);
      draft.original=draft.text;await AtlasI18n.refresh();
      if(state.page==='translate-ui')await renderUITranslationEditor(new URLSearchParams({id:entry.id}));
      if($('ui-translation-status'))$('ui-translation-status').textContent=label('Перевод сохранён.','Translation saved.');
    }catch(error){if($('ui-translation-status'))$('ui-translation-status').textContent=error.message;}
    finally{if(event.target.isConnected)event.target.disabled=false;}
  });
  await renderTranslationHistory('@ui',entry.id,bundle.ui,key,()=>renderUITranslationEditor(new URLSearchParams({id:entry.id})));
}

async function renderTranslationHistory(path,unitId,current,draftKey,rerender){
  const en=AtlasI18n.language==='en',label=(ru,english)=>en?english:ru;
  const response=await fetch('/api/translations/history?'+new URLSearchParams({path,unit_id:unitId}),{cache:'no-store'});
  const result=await response.json();if(!response.ok)throw new Error(result.error);
  if((path==='@ui'&&state.page!=='translate-ui')||(path!=='@ui'&&state.page!=='translate'))return;
  const versions=result.versions;
  $('main').insertAdjacentHTML('beforeend',`<section id="translation-history"><h2>${label('История этого фрагмента','History of this unit')}</h2><p>${label('Сохраняются изменённые фрагменты. Повторное сохранение без изменений не создаёт версию.','Only changed units are saved. Saving unchanged text creates no version.')}</p>${versions.length?`<label class="form-label" for="translation-history-choice">${label('Прежняя версия','Previous version')}</label><select id="translation-history-choice" class="text-input" data-original>${versions.map((v,i)=>`<option value="${i}">${escapeHTML(new Date(v.at).toLocaleString(en?'en':'ru'))} · ${label({legacy:'Старая копия',batch:'Пакетный перевод',edit:'Правка'}[v.kind],{legacy:'Legacy backup',batch:'Batch translation',edit:'Edit'}[v.kind])} · ${v.side==='before'?label('до правки','before edit'):label('после правки','after edit')}</option>`).join('')}</select><div data-translation-content><h3>${label('Основание перевода','Translation source')}</h3><pre id="translation-history-source" class="translation-original"></pre><h3>English</h3><pre id="translation-history-text" class="translation-original"></pre></div><p id="translation-history-warning"></p><p><a id="translation-history-file" class="secondary-button" hidden></a></p><button id="translation-history-restore" class="secondary-button">${label('Восстановить выбранную версию','Restore selected version')}</button><p id="translation-history-status" role="status"></p>`:`<p>${label('Прежних версий пока нет.','No previous versions yet.')}</p>`}</section>`);
  if(!versions.length)return;
  const preview=()=>{
    const selected=versions[Number($('translation-history-choice').value)],value=selected.value;
    const file=$('translation-history-file');file.hidden=!selected.archive_sha;
    if(selected.archive_sha){file.href='/api/translations/history/file?'+new URLSearchParams({sha:selected.archive_sha});file.download='';file.textContent=label('Скачать исходную архивную копию JSON','Download original archived JSON');}
    $('translation-history-source').textContent=value.translated_source||value.source||'';
    $('translation-history-text').textContent=value.translation||'';
    const unit=current.units?.find(u=>u.unit_id===unitId);
    $('translation-history-warning').textContent=unit&&value.translated_source_sha256!==unit.source_sha256?label('Русский оригинал изменился. После восстановления этот перевод будет отмечен как требующий обновления.','The Russian source changed. This restored translation will need an update.'):label('Восстановление заменит текущий перевод и сохранит его в истории. Несохранённый черновик будет заменён.','Restoring replaces the current translation and keeps it in history. The unsaved draft will be replaced.');
  };
  preview();$('translation-history-choice').addEventListener('change',preview);
  $('translation-history-restore').addEventListener('click',async event=>{
    event.target.disabled=true;
    try{
      const response=await fetch('/api/translations/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,unit_id:unitId,version:versions[Number($('translation-history-choice').value)].version,revision:current.revision,source_sha256:current.source_sha256})});
      const result=await response.json();if(!response.ok)throw new Error(result.error);
      translationDrafts.delete(draftKey);await AtlasI18n.refresh();await rerender();
      if($('translation-history-status'))$('translation-history-status').textContent=label('Версия восстановлена.','Version restored.');
    }catch(error){if($('translation-history-status'))$('translation-history-status').textContent=error.message;}
    finally{if(event.target.isConnected)event.target.disabled=false;}
  });
}
