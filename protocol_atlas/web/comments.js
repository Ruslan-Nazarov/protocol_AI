'use strict';

const commentKinds = {fix:'Исправить', change:'Изменить', wording:'Переформулировать', question:'Вопрос'};
const commentState = {selection:null, editing:null, records:[], jump:null};

function commentToast(message, link=false) {
  $('comment-toast').innerHTML = escapeHTML(message) + (link ? ' <a href="#comments">Открыть замечания →</a>' : '');
  $('comment-toast').hidden = false;
  clearTimeout(commentState.toastTimer);
  commentState.toastTimer = setTimeout(() => {$('comment-toast').hidden=true;}, 7000);
}

function selectionLocation(quote, anchor, startElement) {
  let page = location.hash || '#home';
  // Detail panels have their own stable links even when opened within a page.
  if (state.page==='records' && startElement.closest('#record-detail') && workspaceState.selected) {
    page='#records?'+new URLSearchParams({id:workspaceState.selected.id, revision:workspaceState.selected.revision});
  }
  if (state.page==='labs' && startElement.closest('#memory-run') && labState.run) {
    page='#labs?'+new URLSearchParams({run:labState.run.id});
  }
  let source=null;
  if (state.page==='source') {
    const params=new URLSearchParams(page.split('?')[1]||'');
    const doc=docByPath(params.get('path'));
    const block=startElement.closest('.source-block');
    if(doc) {
      const line=block ? Number(block.id.replace('block-','')) : Number(params.get('line'))||1;
      source={path:doc.path, sha256:doc.sha256, line};
      // Keep the exact view: an offset into the full document differs from a section's offset.
      const link=new URLSearchParams(params);link.set('line',String(line));page='#source?'+link;
    }
  }
  return {quote, anchor, page, source, language:AtlasI18n.language,
    page_title:$('main').querySelector('h1')?.textContent||$('page-label').textContent,
    catalog_revision:state.catalog?.catalog_revision||''};
}

function captureCommentSelection() {
  if ($('comment-dialog').open) return;
  const active=document.activeElement;
  let selection=null;
  if ($('main').contains(active) && active.matches('textarea,input[type=text],input:not([type]),input[type=search]')
      && active.selectionEnd>active.selectionStart) {
    const start=active.selectionStart, end=active.selectionEnd;
    const quote=active.value.slice(start,end);
    if(quote.trim())selection=selectionLocation(quote,{field:true,element_id:active.id,offset:start,
      prefix:active.value.slice(Math.max(0,start-100),start),suffix:active.value.slice(end,end+100)},active);
  } else {
    const selected=window.getSelection();
    if(selected && !selected.isCollapsed && selected.rangeCount) {
      const range=selected.getRangeAt(0);
      if($('main').contains(range.startContainer)&&$('main').contains(range.endContainer)) {
        const quote=range.toString();
        if(quote.trim()) {
          const before=document.createRange();before.selectNodeContents($('main'));before.setEnd(range.startContainer,range.startOffset);
          const offset=before.toString().length;
          const text=$('main').textContent;
          const element=range.startContainer.nodeType===Node.ELEMENT_NODE?range.startContainer:range.startContainer.parentElement;
          selection=selectionLocation(quote,{offset,prefix:text.slice(Math.max(0,offset-100),offset),
            suffix:text.slice(offset+quote.length,offset+quote.length+100),element_id:element.closest('[id]')?.id||'',field:false},element);
        }
      }
    }
  }
  commentState.selection=selection;
  $('selection-toolbar').hidden=!selection;
}

function openCommentDialog(record=null) {
  const selected=record||commentState.selection;
  if(!selected)return;
  commentState.editing=record;
  commentState.draft=selected;
  $('comment-dialog-title').textContent=record?'Изменить замечание':'Замечание к выделенному тексту';
  $('comment-quote').textContent=selected.quote;
  $('comment-location').textContent=selected.page_title+(selected.source?' · '+selected.source.path+' · строка '+selected.source.line:'');
  $('comment-kind').innerHTML=options(commentKinds,record?.kind||'change');
  $('comment-text').value=record?.text||'';
  $('comment-error').textContent='';
  $('comment-submit').disabled=false;
  $('selection-toolbar').hidden=true;
  $('comment-dialog').showModal();
  $('comment-text').focus();
}

async function renderComments() {
  $('main').innerHTML=header('ЗАМЕТКИ К ТЕКСТУ','Замечания к тексту','Выделите текст в центральной области и нажмите «Комментарий». Здесь сохраняются цитаты, предложения правок и ссылки на их место.')+
    `<div id="comment-summary"></div><div class="comment-filters"><div><label class="form-label" for="comment-status-filter">Статус</label><select id="comment-status-filter" class="text-input"><option value="open">К исправлению</option><option value="done">Выполнено</option><option value="all">Все замечания</option></select></div><div><label class="form-label" for="comment-kind-filter">Что сделать</label><select id="comment-kind-filter" class="text-input"><option value="all">Все типы</option>${options(commentKinds,'')}</select></div><div><label class="form-label" for="comment-search">Поиск по цитате и замечанию</label><input id="comment-search" type="search" class="text-input" placeholder="Найти замечание…"></div></div><div class="button-row comment-export"><button class="secondary-button" id="comments-export-md">Скачать список правок</button><button class="secondary-button" id="comments-export-json">Скачать JSON</button></div><p class="small-note">Выгружается текущий отфильтрованный список. Отметка «Выполнено» сохраняет замечание в истории.</p><div id="comment-list" aria-live="polite"><p class="loading">Загружаем замечания…</p></div>`;
  try {
    const result=await workspaceAPI('/api/comments');
    if(state.page!=='comments')return;
    commentState.records=result.comments;filterComments();
  }catch(error){if($('comment-list'))$('comment-list').innerHTML='<div class="error-state">'+escapeHTML(error.message)+'</div>';}
}

function visibleComments() {
  const status=$('comment-status-filter')?.value||'open',kind=$('comment-kind-filter')?.value||'all';
  const query=($('comment-search')?.value||'').toLocaleLowerCase('ru');
  return commentState.records.filter(record=>(status==='all'||record.status===status)&&(kind==='all'||record.kind===kind)
    &&(record.quote+' '+record.text+' '+record.page_title).toLocaleLowerCase('ru').includes(query));
}

function filterComments() {
  if(!$('comment-list'))return;
  const records=visibleComments();
  const open=commentState.records.filter(r=>r.status==='open').length;
  $('comment-summary').innerHTML=`<p class="muted">К исправлению: <strong>${open}</strong> · выполнено: <strong>${commentState.records.length-open}</strong> · показано: ${records.length}</p>`;
  $('comment-list').innerHTML=records.map(record=>`<article class="card reader-comment" id="comment-${record.id}"><div class="section-heading">${badge(commentKinds[record.kind],'proposal')}${badge(record.status==='done'?'Выполнено':'К исправлению')}</div><p class="comment-origin">${escapeHTML(record.page_title)}${record.source?' · '+escapeHTML(record.source.path)+' · строка '+record.source.line:''}</p><blockquote class="comment-quotation">${escapeHTML(record.quote)}</blockquote><p class="comment-body">${escapeHTML(record.text)}</p><div class="button-row"><button class="secondary-button" data-comment-jump="${record.id}">К выделенному месту →</button><button class="secondary-button" data-comment-edit="${record.id}">Изменить замечание</button><button class="secondary-button" data-comment-status="${record.id}">${record.status==='done'?'Вернуть к исправлению':'Отметить выполненным'}</button></div><p class="small-note comment-date">${escapeHTML(new Date(record.created_at).toLocaleString('ru-RU'))}</p></article>`).join('')||'<div class="empty-state">Здесь пока нет замечаний. Выделите текст на любой странице атласа и оставьте комментарий.</div>';
}

function exportComments(markdown) {
  const records=visibleComments();
  if(!records.length){commentToast('В выбранном списке нет замечаний.');return;}
  if(!markdown){downloadJSON('protocol-comments.json',{comments:records});return;}
  const label=value=>AtlasI18n.text(value);
  const text=label('# Замечания к протоколу')+'\n\n'+records.map((record,index)=>
    `## ${index+1}. ${label(commentKinds[record.kind])} · ${label(record.status==='done'?'Выполнено':'К исправлению')}\n\n`+
    `${label('Раздел')}: ${record.page_title}\n${label('Место')}: http://127.0.0.1:${location.port}${record.page}\n`+
    (record.source?`${label('Источник')}: ${record.source.path}, ${label('строка')} ${record.source.line}, ${label('версия')} ${record.source.sha256}\n`:'')+
    `\n${label('Цитата')}:\n${record.quote.split('\n').map(line=>'> '+line).join('\n')}\n\n${label('Замечание')}:\n${record.text}\n`).join('\n');
  const url=URL.createObjectURL(new Blob([text],{type:'text/markdown;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download='protocol-comments.md';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function findQuote(text,record) {
  const offsets=[];let at=text.indexOf(record.quote);
  while(at>=0){offsets.push(at);at=text.indexOf(record.quote,at+1);}
  if(!offsets.length)return -1;
  const score=at=>(record.anchor.prefix&&text.slice(Math.max(0,at-record.anchor.prefix.length),at)===record.anchor.prefix?2:0)
    +(record.anchor.suffix&&text.slice(at+record.quote.length,at+record.quote.length+record.anchor.suffix.length)===record.anchor.suffix?2:0);
  offsets.sort((a,b)=>score(b)-score(a)||Math.abs(a-record.anchor.offset)-Math.abs(b-record.anchor.offset));
  return offsets[0];
}

function locateComment() {
  const record=commentState.jump;if(!record)return;
  if((location.hash||'#home')!==record.page||state.page!==record.page.slice(1).split('?')[0])return;
  // Never attach an old quote to a newly changed source version.
  if(record.source&&docByPath(record.source.path)?.sha256!==record.source.sha256)return;
  if(record.anchor.field) {
    const field=document.getElementById(record.anchor.element_id);
    if(!field||!$('main').contains(field)||typeof field.value!=='string')return;
    const at=findQuote(field.value,record);if(at<0)return;
    finishCommentJump();field.focus();field.setSelectionRange(at,at+record.quote.length);field.scrollIntoView({block:'center'});return;
  }
  const at=findQuote($('main').textContent,record);if(at<0)return;
  const walker=document.createTreeWalker($('main'),NodeFilter.SHOW_TEXT);
  let offset=0,node,start=null,startOffset=0,end=null,endOffset=0;
  while((node=walker.nextNode())) {
    const next=offset+node.textContent.length;
    if(!start&&at<next){start=node;startOffset=at-offset;}
    if(start&&at+record.quote.length<=next){end=node;endOffset=at+record.quote.length-offset;break;}
    offset=next;
  }
  if(!start||!end)return;
  const range=document.createRange();range.setStart(start,startOffset);range.setEnd(end,endOffset);
  const element=start.parentElement;
  for(let parent=element;parent&&parent!==$('main');parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
  finishCommentJump();
  if(window.CSS?.highlights&&window.Highlight)CSS.highlights.set('comment-location',new Highlight(range));
  else {element.classList.add('comment-target');setTimeout(()=>element.classList.remove('comment-target'),6000);}
  element.scrollIntoView({block:'center'});
  commentToast('Открыта сохранённая цитата.');
}

function finishCommentJump() {
  commentState.jump=null;clearTimeout(commentState.jumpTimer);commentState.observer?.disconnect();
}

async function jumpToComment(record) {
  await AtlasI18n.setLanguage(record.language||'ru');
  finishCommentJump();commentState.jump=record;
  commentState.observer=new MutationObserver(locateComment);
  commentState.observer.observe($('main'),{childList:true,subtree:true});
  commentState.jumpTimer=setTimeout(()=>{
    if(commentState.jump){finishCommentJump();commentToast('Страница открыта, но цитата недоступна или текст изменился. Сохранённая цитата остаётся в замечаниях.',true);}
  },5000);
  if(location.hash!==record.page)location.hash=record.page;
  else locateComment();
  requestAnimationFrame(locateComment);
}

let atlasDepth=Number.isInteger(history.state?.atlasDepth)?history.state.atlasDepth:0;
history.replaceState({...history.state,atlasDepth,atlasHash:location.hash},'');
function updateBackButton() {
  $('go-back').disabled=atlasDepth===0&&(!location.hash||location.hash==='#home');
}
updateBackButton();
window.addEventListener('hashchange',()=>{
  if(history.state?.atlasHash===location.hash&&Number.isInteger(history.state?.atlasDepth))atlasDepth=history.state.atlasDepth;
  else {atlasDepth++;history.replaceState({...history.state,atlasDepth,atlasHash:location.hash},'');}
  commentState.selection=null;$('selection-toolbar').hidden=true;
  updateBackButton();
});
$('go-back').addEventListener('click',()=>{if(atlasDepth>0)history.back();else location.hash='home';});
document.addEventListener('selectionchange',captureCommentSelection);
$('main').addEventListener('select',captureCommentSelection,true);
for(const id of ['selection-comment']) {
  $(id).addEventListener('pointerdown',event=>event.preventDefault());
  $(id).addEventListener('click',()=>openCommentDialog());
}
$('comment-cancel').addEventListener('click',()=>$('comment-dialog').close());
$('comment-dialog').addEventListener('close',()=>{captureCommentSelection();$('main').focus({preventScroll:true});});
$('comment-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=$('comment-submit');button.disabled=true;$('comment-error').textContent='';
  try {
    const edited=commentState.editing;
    const payload={...(edited?{id:edited.id,revision:edited.revision,status:edited.status}:commentState.draft),
      text:$('comment-text').value,kind:$('comment-kind').value};
    await workspaceAPI('/api/comments/save',payload);
    $('comment-dialog').close();window.getSelection()?.removeAllRanges();
    captureCommentSelection();commentToast('Замечание сохранено.',true);
    if(state.page==='comments')await renderComments();
  }catch(error){$('comment-error').textContent=error.message;}
  finally{button.disabled=false;}
});
document.addEventListener('keydown',event=>{
  if(event.ctrlKey&&event.altKey&&event.code==='KeyM'){event.preventDefault();captureCommentSelection();openCommentDialog();}
});
document.addEventListener('change',event=>{if(['comment-status-filter','comment-kind-filter'].includes(event.target.id))filterComments();});
document.addEventListener('input',event=>{if(event.target.id==='comment-search')filterComments();});
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.id==='comments-export-md')exportComments(true);
  if(button.id==='comments-export-json')exportComments(false);
  const id=button.dataset.commentEdit||button.dataset.commentJump||button.dataset.commentStatus;
  const record=commentState.records.find(item=>item.id===id);if(!record)return;
  if(button.dataset.commentEdit)openCommentDialog(record);
  if(button.dataset.commentJump)jumpToComment(record);
  if(button.dataset.commentStatus) {
    button.disabled=true;
    try {
      const result=await workspaceAPI('/api/comments/save',{id:record.id,revision:record.revision,text:record.text,
        kind:record.kind,status:record.status==='done'?'open':'done'});
      commentState.records=commentState.records.map(item=>item.id===record.id?result:item);filterComments();
    }catch(error){button.disabled=false;commentToast(error.message);}
  }
});
