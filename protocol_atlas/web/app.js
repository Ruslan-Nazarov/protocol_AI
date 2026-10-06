'use strict';

const NAV = [
  ['rules','Протокол','≡'],['project-start','Подключение','⇌'],
  ['results','Результаты и память','▤'],['improvement','Улучшение','↗']
];
function navigationSection(page){
  if(['project-start','connections','settings','reader','onboarding'].includes(page))return 'project-start';
  if(['results','memory','records','project-state'].includes(page))return 'results';
  if(['improvement','protocol-setup','history','comments','labs','lab-plan','regulator','regulator-previous'].includes(page))return 'improvement';
  return 'rules';
}
function learningIntro(){return '';}
function appendLearningTransition(){}
const ROLES = {
  'STATE.md':['Состояние проекта','Цель, сделанное, текущая работа и следующий шаг.'],
  'DECISIONS.md':['Принятые решения','Выбор человека, его причины и история пересмотра.'],
  'OPEN_QUESTIONS.md':['Открытые вопросы','Непроверенные гипотезы и нерешённые развилки.'],
  'GLOSSARY.md':['Словарь протокола','Точные значения терминов, на которые опираются правила.'],
  'READER.md':['Профиль читателя','Что человеку известно и что требует объяснения.'],
  'CALIBRATION.md':['Калибровка','Нагрузка, самостоятельность и результаты проверок по ситуациям.'],
  'ARCHITECTURES.md':['Архитектуры задач','Шаблоны блоков, их входов, выходов и проверок.'],
  'ERRORS.md':['Разбор ошибок','Событие, причина, исправление и способ повторной проверки.']
};
const DOCUMENT_DESCRIPTIONS = {
  'PROTOCOL.md':'Главные правила работы человека с ИИ: проверка утверждений, память между сессиями, самостоятельность ИИ и понятность ответов.',
  'check_answer.py':'Скрипт проверки черновика ответа: ищет признаки необъяснённых терминов, длинные абзацы и другие нарушения формы. Правильность смысла не проверяет.',
  'docs/LAB_CONTRACT.md':'Правила лабораторных опытов: как учитывать расход токенов, сохранять ошибки API, ограничивать чтение источников и оценивать результаты.',
  'memory/ARCHITECTURES.md':'Шаблоны разбиения сложной задачи на части: определяют порядок работы, вход, результат и проверку каждой части.',
  'memory/CALIBRATION.md':'Настройки допустимой сложности одного шага и самостоятельности ИИ для разных задач и моделей. Хранит результаты проверок, по которым эти настройки пересматривают.',
  'memory/DECISIONS.md':'Журнал принятых человеком решений: что выбрано, почему и при каких условиях. Помогает ИИ продолжать работу без повторного выбора.',
  'memory/ERRORS.md':'Журнал ошибок ИИ: что произошло, какое правило нарушено, как исправили и чем проверяют исправление.',
  'memory/GLOSSARY.md':'Словарь терминов протокола: закрепляет значения слов и обозначений, чтобы человек и ИИ понимали правила одинаково.',
  'memory/OPEN_QUESTIONS.md':'Нерешённые вопросы и гипотезы: показывает, что ещё нужно обсудить или проверить и что пока нельзя считать принятым решением.',
  'memory/READER.md':'Профиль читателя: какие темы и термины ему известны, что нужно объяснять и насколько подробно излагать материал.',
  'memory/STATE.md':'Текущее состояние проекта: цель, сделанное, незавершённая работа и следующий шаг. Нужен для продолжения после смены сессии.'
};
const state = {catalog:null, page:'home', historyTab:'errors', rulesTab:'sections', busy:false};
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const plain = text => String(text).replace(/[*`#]/g,'').trim();
const extraSources=new Map();
const docByPath = path => state.catalog.documents.find(doc => doc.path === path)||extraSources.get(path);
async function sourceDocument(path){
  const core=state.catalog.documents.find(doc=>doc.path===path);if(core)return core;
  const response=await fetch('/api/source/document?'+new URLSearchParams({path}),{cache:'no-store'}),doc=await response.json();
  if(!response.ok)throw new Error(doc.error);extraSources.set(path,doc);return doc;
}
const textOf = doc => doc.blocks.map(block => block.text).join('');
const protocol = () => docByPath('PROTOCOL.md');
const findSection = (doc,prefix) => doc.sections.find(section => section.title === prefix || section.title.startsWith(prefix+' ') || section.title.startsWith(prefix+' ·'));
const sectionBlocks = (doc,section) => doc.blocks.filter(block => block.start_line >= section.start_line && block.start_line <= section.end_line);
const sectionText = (doc,section) => sectionBlocks(doc,section).map(block => block.text).join('');

function inline(text) {
  // Escape source data first. Only these formatting tags are ever introduced.
  return escapeHTML(text).replace(/`([^`\n]+)`/g,'<code>$1</code>')
    .replace(/\[([^\]\n]+)\]\(((?:memory|docs)\/[A-Za-z0-9_/-]+\.md|PROTOCOL\.md)\)/g,(match,label,path)=>{
      const doc=docByPath(path);if(!doc)return match;
      const section=findSection(doc,label);
      return `<a href="#source?${escapeHTML(new URLSearchParams({path,line:String(section?.start_line||1),sha:doc.sha256}).toString())}">${label}</a>`;
    })
    .replace(/\[([^\]\n]+)\]\((https:\/\/[^\s<>"()]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')
    .replace(/\*([^*\n]+)\*/g,'<em>$1</em>');
}

function fileDownloadLink(path,label='Скачать файл',extra='secondary-button'){
  return `<a class="${extra}" data-connection-download href="/api/connection-files?${new URLSearchParams({language:AtlasI18n.language,path})}" download="${escapeHTML(path.split('/').pop())}">${escapeHTML(label)}</a>`;
}
function connectionBundleLink(bundle,label){
  const filename=bundle==='project'?'protocol-ai-app.zip':`protocol-ai-${AtlasI18n.language}-memory.zip`;
  return `<a class="secondary-button" data-connection-download href="/api/connection-files?${new URLSearchParams({language:AtlasI18n.language,bundle})}" download="${filename}">${label}</a>`;
}
function linkMentionedFiles(container){
  const paths=new Set([...state.catalog.documents.map(doc=>doc.path),...AtlasI18n.documents.map(doc=>doc.path),'protocol_atlas/memory.py','protocol_atlas/context.py','protocol_atlas/retrieval.py','protocol_atlas/task_analysis.py','protocol_atlas/math_checks.py','protocol_atlas/workflows.py','protocol_atlas/project_checks.py','protocol_atlas/runtime_rules.py','protocol_atlas/answer_checks.py','protocol_atlas/adaptive.py','atlas/rule_runtime.json']);
  for(const code of container.querySelectorAll('code')){
    if(code.closest('pre,a,textarea'))continue;
    const path=code.textContent.trim();
    if(!paths.has(path)&&path!=='memory/')continue;
    const link=document.createElement('a');link.setAttribute('data-connection-download','');
    link.href='/api/connection-files?'+new URLSearchParams({language:AtlasI18n.language,...(path==='memory/'?{bundle:'memory'}:{path})});
    link.download=path==='memory/'?`protocol-ai-${AtlasI18n.language}-memory.zip`:path.split('/').pop();
    link.title=AtlasI18n.text('Скачать файл');code.replaceWith(link);link.append(code);
  }
}

function blockHTML(block, original=false) {
  const value = (original === true ? block.text : AtlasI18n.source(block.text,block)).trim();
  if (block.kind === 'blank') return '';
  if (block.kind === 'separator') return '<hr>';
  if (block.kind === 'heading') {
    const match = value.replace(/^\uFEFF/,'').match(/^(#{1,6})\s+(.+)$/);
    return match ? `<h${match[1].length}>${inline(match[2])}</h${match[1].length}>` : `<p>${inline(value)}</p>`;
  }
  if (block.kind === 'code') {
    const code = value.replace(/^\s*(`{3,}|~{3,})[^\n]*\n/,'').replace(/\n\s*(`{3,}|~{3,})\s*$/,'');
    return `<pre><code>${escapeHTML(code)}</code></pre>`;
  }
  if (block.kind === 'table') {
    const rows = value.split(/\r?\n/).filter(line => !/^\s*\|[\s:|\-]+\|?\s*$/.test(line));
    const cells = row => row.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(cell=>cell.trim());
    return `<div class="table-wrap"><table><thead><tr>${cells(rows[0]).map(cell=>`<th scope="col">${inline(cell)}</th>`).join('')}</tr></thead><tbody>${rows.slice(1).map(row=>`<tr>${cells(row).map(cell=>`<td>${inline(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  return `<p>${inline(value).replace(/\r?\n/g,'<br>')}</p>`;
}

function sourceButton(path,line=1,label=null,extra='') {
  const doc = docByPath(path);
  if (!doc) return '';
  return `<button class="source-button ${extra}" data-source="${escapeHTML(path)}" data-line="${line}">${escapeHTML(label || path)} <span aria-hidden="true">↗</span></button>`;
}

function sectionButton(prefix,label=null,path='PROTOCOL.md',className='link-button') {
  const doc = docByPath(path), section = doc && findSection(doc,prefix);
  return section ? `<button class="${className}" data-source="${escapeHTML(path)}" data-line="${section.start_line}">${escapeHTML(label || prefix)} <span aria-hidden="true">↗</span></button>` : '';
}

function header(eyebrow,title,description) {
  return `<div class="page-header"><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p class="intro">${description}</p></div>${learningIntro(state.page)}`;
}

function badge(label,kind='neutral') { return `<span class="badge ${kind}">${escapeHTML(label)}</span>`; }
function renderHome() { return renderRules(new URLSearchParams()); }

async function renderConnections() {
  $('main').innerHTML=`<div class="page-header"><div class="eyebrow">ПОДКЛЮЧЕНИЕ</div><h1>Подключение протокола к ИИ</h1><p class="intro">Подготовим папку рабочего проекта, положим в неё файлы и передадим ИИ инструкцию.</p></div><section class="card connection-picker"><label class="form-label" for="connection-client">Где вы будете работать? ${helpHint('Чем отличаются приложения ИИ','Браузерный чат получает приложенные файлы. Codex, Claude Code и Gemini CLI могут читать папку проекта. «Мой агент» — ваша программа, которая сама обращается к API модели. Для разработки в Codex выберите «Codex — локальный агент».')}</label><select id="connection-client" class="text-input"><option value="">Выберите вариант</option>${Object.entries(CONNECTION_CLIENTS).map(([key,item])=>`<option value="${key}">${escapeHTML(item.label)}</option>`).join('')}</select><div id="connection-mode-container" hidden><label class="form-label" for="connection-mode">Как подключить правила и память? ${helpHint('Чем отличаются способы подключения','Файлы в папке проекта: ИИ читает PROTOCOL.md и Markdown-память напрямую; это простой старт для Codex. Локальный сервис: дополнительно хранит версии записей, собирает контекст и проверяет ссылки; его сервер должен работать и быть доступен агенту. Передача файлов в чат — снимок, который нужно обновлять вручную.')}</label><select id="connection-mode" class="text-input"></select></div><div id="connection-path-container" hidden><label class="form-label" for="connection-path">Полный путь к папке вашего проекта ${helpHint('Зачем нужен путь к проекту','Это адрес папки, которую вы открыли в Codex или другом локальном агенте, например D:\\Projects\\bridge-infographics. Внутри создайте папку .protocol и распакуйте туда скачанный протокол. Путь нужен, чтобы сформировать инструкцию с правильным местом файлов; сайт не создаёт папку на вашем диске.')}</label><input id="connection-path" class="text-input" placeholder="Например: D:\\Projects\\bridge-infographics" autocomplete="off"><p class="small-note">Создайте папку для своего приложения и откройте её как проект в Codex. Скопируйте полный адрес этой папки из Проводника и вставьте сюда.</p><p id="connection-folder-preview" class="small-note"></p></div></section><section id="connection-instruction" class="card" hidden aria-live="polite"></section><details class="source-details"><summary>Полное руководство по подключению</summary><div id="connection-full-guide"></div></details>`;
  $('connection-client').value=connectionChoice.client;
  updateConnectionModes(false);
  try{await loadHandoffDescription();if(state.page==='connections')updateConnectionInstruction();}
  catch(error){if($('handoff-status'))$('handoff-status').textContent='Не удалось подставить описание: '+error.message+'. Можно ввести его выше.';}
}

const CONNECTION_CLIENTS={
  chat:{label:'ChatGPT, Claude или Gemini — чат в браузере',type:'chat'},
  codex:{label:'Codex — локальный агент',type:'agent',file:'AGENTS.md',docs:'https://learn.chatgpt.com/docs/agent-configuration/agents-md'},
  claude:{label:'Claude Code — локальный агент',type:'agent',file:'CLAUDE.md',docs:'https://code.claude.com/docs/en/memory'},
  gemini:{label:'Gemini CLI — локальный агент',type:'agent',file:'GEMINI.md',docs:'https://geminicli.com/docs/cli/gemini-md/'},
  api:{label:'Мой агент — программа с вызовами API модели',type:'program'},
  local:{label:'Локальная модель в моём приложении',type:'program'}
};
const connectionChoice=(()=>{try{return {client:'',mode:'files',path:'',...JSON.parse(localStorage.getItem('protocol-connection-choice')||'{}')};}catch{return {client:'',mode:'files',path:''};}})();

function updateConnectionModes(reset=true){
  connectionChoice.client=$('connection-client').value;
  const client=CONNECTION_CLIENTS[connectionChoice.client];
  $('connection-mode-container').hidden=!client;
  if(!client){$('connection-path-container').hidden=true;$('connection-instruction').hidden=true;return;}
  const modes=client.type==='chat'?[['snapshot','Правила и память — передать файлы в чат']]:[['files','Файлы в папке проекта — простой старт'],['service','Версионная память через локальный сервис']];
  if(reset||!modes.some(([key])=>key===connectionChoice.mode))connectionChoice.mode=modes[0][0];
  $('connection-mode').innerHTML=modes.map(([key,label])=>`<option value="${key}">${label}</option>`).join('');
  $('connection-mode').value=connectionChoice.mode;
  $('connection-path').value=connectionChoice.path;
  updateConnectionInstruction();
}

function updateConnectionInstruction(){
  const client=CONNECTION_CLIENTS[connectionChoice.client];if(!client)return;
  connectionChoice.mode=$('connection-mode').value;
  const service=connectionChoice.mode==='service',chat=client.type==='chat',agent=client.type==='agent';
  $('connection-path-container').hidden=!agent;
  const projectPath=connectionChoice.path.trim().replace(/[\\/]+$/,'');
  const separator=projectPath.includes('\\')?'\\':'/';
  const path=projectPath?projectPath+separator+'.protocol':'<папка вашего проекта>/.protocol';
  if($('connection-folder-preview'))$('connection-folder-preview').textContent=projectPath?'Распакуйте файлы протокола в: '+path:'';
  try{localStorage.setItem('protocol-connection-choice',JSON.stringify(connectionChoice));}catch{}

  let steps,available,limit,prompt='';
  if(chat){
    steps=['Приложите PROTOCOL.md, memory/STATE.md и memory/DECISIONS.md к сообщению. Добавьте файлы по текущей задаче.','Отправьте инструкцию ниже. Если чат не принимает файлы, вставьте их текст в сообщение.','Для новой сессии передайте актуальные файлы снова. Предложенные изменения памяти сохраните после проверки.'];
    prompt='Прочитай приложенный PROTOCOL.md и файлы памяти. Назови полученные документы. Применяй протокол к моей задаче; гипотезы не считай принятыми решениями. Если нужного файла нет, сообщи об этом.';
    available='Правила и переданный снимок памяти.';
    limit='Чат не видит обновления вашей папки и не записывает в неё результаты. Проверки запускает человек.';
  }else if(agent){
    steps=[
      `Создайте отдельную папку для своего приложения, например D:\\Projects\\bridge-infographics. Откройте её как проект в ${connectionChoice.client==='codex'?'Codex':client.label}. Если проект уже открыт, используйте его папку.`,
      `Внутри папки проекта создайте подпапку .protocol. Скачайте «Протокол и память · ZIP» ниже и распакуйте содержимое в ${path}. В этой подпапке должны лежать PROTOCOL.md и папка memory/, без лишнего уровня вложенности.`,
      `Вставьте полный путь к папке проекта в поле выше. Скачайте инструкцию ниже. В корне проекта создайте ${client.file} и добавьте в него содержимое инструкции. Если файл уже есть, дополните его, сохранив действующие инструкции.`,
      'Файлы memory/ в ZIP описывают этот атлас и служат примерами. В чате рабочего проекта опишите своё приложение и попросите ИИ создать его собственные STATE.md, DECISIONS.md и OPEN_QUESTIONS.md в .protocol/memory/, сохранив загруженные примеры в архиве.',
      ...(service?['Для локального сервиса скачайте приложение с сервером отдельно. Запустите его из папки: py -3 -m protocol_atlas.server. Дайте агенту доступ к адресу сервера и выберите память именно вашего проекта; память атласа относится к другому проекту.']:[]),
      'Начните новый чат в рабочем проекте. Попросите ИИ прочитать инструкцию, назвать заголовок протокола и привести короткую точную цитату. Сверьте её с файлом.'
    ];
    prompt=`Папка протокола: ${path}.\nПеред задачей прочитай PROTOCOL.md и актуальные memory/STATE.md и memory/DECISIONS.md из этой папки.\nПамять должна относиться к этому рабочему проекту. Загруженные примеры памяти атласа не являются состоянием этого проекта. При первой настройке сохрани их в архиве и создай память проекта по описанию человека; неизвестное обозначай явно.\nПрименяй протокол в рамках разрешений клиента. Гипотезы не считай принятыми решениями.\nСообщи, какие файлы прочитаны и какие недоступны.\nПосле смены чата перечитай актуальную память.\n${service?'Обращайся к локальному сервису памяти только после проверки, что он настроен на этот проект. Для правки существующей записи передавай expected_revision; предложения не помечай принятыми решениями.':'Обновляй память этого проекта по результатам работы; решения человека сохраняй вместе с основаниями.'}`;
    available=service?'Правила, версионная память и проверки через локальный API.':'Правила и файлы памяти, доступные агенту. Скрипт проверки можно запускать его инструментами.';
    limit=service?'Локальный API должен быть доступен из среды агента. Симулятор нагрузки и самостоятельности не ограничивает действия агента автоматически.':'Доступ к папке не гарантирует применение правил; проверьте чтение и результат работы.';
  }else{
    steps=[service?'Скачайте приложение с сервером и распакуйте ZIP. Из его папки запустите: py -3 -m protocol_atlas.server. Импортируйте источники в разделе «Ведение памяти проекта».':'Скачайте протокол и всю память, распакуйте ZIP. В программе задайте путь к этой папке и чтение PROTOCOL.md вместе с нужными memory/*.md.',service?'Добавьте в программу чтение GET /api/catalog и GET /api/memory, затем сборку контекста через POST /api/memory/assemble. Адрес: http://127.0.0.1:8765.':'Передавайте правила в поле инструкций вашего API модели, а записи памяти — в контекст задачи. После новой сессии подгружайте актуальные файлы.',service?'Передавайте собранный контекст модели. Обрабатывайте запрет сборки, проверяйте ответ и сохраняйте предложения через API памяти с контролем версии.':'Проверяйте ответы программой или человеком. Сохраняйте результаты в общую память через одного автора изменений.'];
    available=service?'Правила, выбранные записи с основаниями и серверные проверки.':'Правила и те файлы памяти, которые программа передала модели.';
    limit='Нужна реализация чтения и передачи контекста в вашем приложении. Ключ API или установка модели сами по себе память не подключают.';
  }
  const target=$('connection-instruction');target.hidden=false;
  if(prompt)prompt=AtlasI18n.text(agent?prompt.replace(path,'__ATLAS_PROTOCOL_FOLDER__'):prompt).replace('__ATLAS_PROTOCOL_FOLDER__',path);
  const individual=['PROTOCOL.md','memory/STATE.md','memory/DECISIONS.md'].map(file=>fileDownloadLink(file,file)).join('');
  const downloads=`<div class="connection-downloads"><strong>Файлы для подключения</strong><div class="button-row">${chat?`<a class="primary-button" data-connection-download href="/api/connection-files?${new URLSearchParams({language:AtlasI18n.language})}" download>Скачать все файлы · ZIP</a>${individual}`:connectionBundleLink('memory','Протокол и память · ZIP')}${service?connectionBundleLink('project','Скачать приложение с сервером · ZIP'):''}</div>${!chat?`<details><summary>Отдельные файлы</summary><div class="button-row">${individual}${fileDownloadLink('check_answer.py','Скачать скрипт проверки')}${fileDownloadLink('docs/CONNECTING_AI.md','Скачать руководство')}</div></details>`:''}<p class="small-note">ZIP сохраняет папку memory/. Язык файлов соответствует языку сайта.</p>${service?'<p class="small-note">Приложение содержит RU/EN. Для запуска нужен Python 3.10+. <a href="https://www.python.org/downloads/" target="_blank" rel="noopener noreferrer">Скачать Python ↗</a></p>':''}<a href="#rules?tab=documents">Другие документы →</a><p id="connection-download-status" class="small-note" role="status"></p></div>`;
  target.innerHTML=`<h2>Как подключить: ${escapeHTML(client.label)}</h2><ol class="connection-steps">${steps.map(step=>`<li>${escapeHTML(step)}</li>`).join('')}</ol>${downloads}<p><strong>Доступно:</strong> ${escapeHTML(available)}</p><p class="small-note">${escapeHTML(limit)}</p>${prompt?`<details open><summary>Инструкция для ИИ${agent?' · '+escapeHTML(client.file):''}</summary><pre class="raw-source" id="connection-prompt">${escapeHTML(prompt)}</pre><button type="button" id="connection-copy" class="secondary-button" ${agent&&!connectionChoice.path.trim()?'disabled':''}>Скопировать инструкцию</button><a class="secondary-button" data-connection-download href="/api/connection-instruction?${new URLSearchParams({text:prompt,filename:agent?client.file.replace('.md','.protocol.md'):'PROTOCOL_INSTRUCTION.md'})}" download="${agent?client.file.replace('.md','.protocol.md'):'PROTOCOL_INSTRUCTION.md'}" ${agent&&!connectionChoice.path.trim()?'aria-disabled="true" tabindex="-1"':''}>Скачать инструкцию</a><span id="connection-copy-status" class="small-note" role="status"></span>${agent?'<p class="small-note">Добавьте содержимое скачанной инструкции в файл клиента. Сохраните существующие инструкции.</p>':''}</details>`:''}<p class="small-note"><strong>Проверка подключения:</strong> попросите ИИ назвать заголовок PROTOCOL.md и привести короткую точную цитату. Сверьте её с файлом.</p>${client.docs?`<a href="${client.docs}" target="_blank" rel="noopener noreferrer">Инструкция клиента ↗</a>`:''}${service?'<details><summary>Операции локального API</summary><p>GET /api/catalog — чтение правил; GET /api/memory — список записей; POST /api/memory/assemble — сборка контекста (ids, goal, budget); POST /api/memory/save — запись с expected_revision; POST /api/memory/check-response — проверка ссылок ответа. POST отправляется в формате JSON. Сервис доступен только на локальном компьютере.</p></details>':''}`;
  mountProjectHandoff(client,path);
}

document.addEventListener('change',event=>{
  if(event.target.id==='connection-client')updateConnectionModes();
  if(event.target.id==='connection-mode')updateConnectionInstruction();
});
document.addEventListener('input',event=>{
  if(event.target.id==='connection-path'){connectionChoice.path=event.target.value;updateConnectionInstruction();}
});
document.addEventListener('click',async event=>{
  const download=event.target.closest('[data-connection-download]');
  if(download){
    if(download.getAttribute('aria-disabled')==='true'){
      event.preventDefault();
      if(download.id==='handoff-download')return;
      if($('connection-copy-status'))$('connection-copy-status').textContent=' Сначала укажите полный путь к папке проекта в поле выше.';
      return;
    }
    const status=$('connection-download-status');
    if(status)status.textContent='Открываем загрузку файла. Проверьте загрузки браузера.';
    // Keep the original user gesture and attachment URL: the in-app browser
    // cannot download blob URLs or clicks synthesized after an awaited fetch.
    return;
  }
  if(event.target.closest('#connection-copy')){
    try{await navigator.clipboard.writeText($('connection-prompt').textContent);$('connection-copy-status').textContent=' Скопировано.';}
    catch(error){$('connection-copy-status').textContent=' Выделите и скопируйте текст инструкции вручную.';}
  }
});
document.addEventListener('toggle',async event=>{
  const content=event.target.querySelector?.('#connection-full-guide');
  if(!content||!event.target.open||content.dataset.loaded)return;
  content.textContent='Загружаем руководство…';
  try{const response=await fetch('/api/connections');const guide=await response.json();if(!response.ok)throw Error(guide.error);content.innerHTML=`<div class="button-row">${connectionBundleLink('memory','Протокол и память · ZIP')}${connectionBundleLink('project','Скачать приложение с сервером · ZIP')}${fileDownloadLink('docs/CONNECTING_AI.md','Скачать руководство')}</div><p class="small-note">Приложение содержит RU/EN. Для запуска нужен Python 3.10+. <a href="https://www.python.org/downloads/" target="_blank" rel="noopener noreferrer">Скачать Python ↗</a></p>`+guide.blocks.map(blockHTML).join('');linkMentionedFiles(content);content.dataset.loaded='1';}
  catch(error){content.textContent='Не удалось прочитать руководство: '+error.message;}
},true);

function renderRules(params) {
  const tab = params.get('tab') || state.rulesTab; state.rulesTab = tab;
  const doc = protocol();
  let body='';
  if (tab==='questions') {
    body=state.catalog.annotations.filter(note=>note.kind==='open_question').map(note=>`<article class="annotation-card">${badge(note.status==='proposal'?'Предложение':'Не решено','proposal')}<h3>${escapeHTML(note.title)}</h3><p>${escapeHTML(note.body)}</p><button class="link-button" data-note="${escapeHTML(note.id)}">Открыть основания →</button></article>`).join('');
  } else if (tab==='documents') {
    body=`<div class="cards-grid">${state.catalog.documents.map(item=>`<div class="card"><h3>${escapeHTML(item.path)}</h3><p>${escapeHTML(DOCUMENT_DESCRIPTIONS[item.path]||ROLES[item.path.split('/').pop()]?.[1]||'Назначение документа пока не описано. Откройте исходный текст, чтобы ознакомиться с содержанием.')}</p><p class="small-note">${item.line_count} строк · ${item.sections.length} разделов</p>${sourceButton(item.path,1,'Открыть документ','link-button')} ${fileDownloadLink(item.path,'Скачать файл','link-button')}</div>`).join('')}</div>`;
  } else {
    const groups=doc.sections.filter(section=>section.level===2);
    body=groups.map(group=>{
      const children=doc.sections.filter(section=>section.parent_id===group.id);
      const title=group.title.replace(/^[\dА-Яа-я]+\.\s*/,'');
      return `<details class="rule-group portal-stage"><summary class="rule-group-title"><span data-original class="group-id">${escapeHTML(group.title.split(' ')[0])}</span>${escapeHTML(title)}</summary>${(children.length?children:[group]).map(section=>`<button class="rule-row" data-source="PROTOCOL.md" data-line="${section.start_line}"><span data-original class="rule-number">${escapeHTML(section.title.split(' ')[0])}</span><span>${escapeHTML(section.title.replace(/^[\dА-Яа-я]+(?:\.\d+)*\.?\s*/,''))}<small>Исходный текст · строка ${section.start_line}</small></span><span class="arrow" aria-hidden="true">↗</span></button>`).join('')}</details>`;
    }).join('');
  }
  $('main').innerHTML=header('ПРОТОКОЛ РАБОТЫ С ИИ','Протокол','Читайте, редактируйте и подключайте протокол к своему агенту или чату. Задачи выполняются в выбранном приложении; здесь собраны правила, их механика и результаты проверки.')+`<div class="button-row portal-actions"><a class="primary-button" href="#source?path=PROTOCOL.md&amp;full=1">Читать целиком</a><a class="secondary-button" href="#edit?path=PROTOCOL.md">Редактировать</a><a class="secondary-button" href="#workflow">Как устроены этапы</a></div>`+`<div class="view-tabs" role="tablist" aria-label="Вид каталога"><button class="tab" role="tab" aria-selected="${tab==='sections'}" data-rule-tab="sections">Разделы протокола</button><button class="tab" role="tab" aria-selected="${tab==='questions'}" data-rule-tab="questions">Открытые вопросы · ${state.catalog.annotations.filter(note=>note.kind==='open_question').length}</button><button class="tab" role="tab" aria-selected="${tab==='documents'}" data-rule-tab="documents">Все документы</button></div>${body}`;
}

function formRules(){
  const doc=protocol();
  return doc.sections.filter(item=>item.level===3).map(item=>({id:item.title.split(' ')[0],title:item.title.replace(/^\S+\s+/,''),line:item.start_line,text:sectionText(doc,item)}));
}

function renderWorkflow() {
  const doc=protocol(),stages=doc.sections.filter(item=>item.level===2);
  $('main').innerHTML=header('ВЫПОЛНЕНИЕ ЗАДАЧИ ПО ПРОТОКОЛУ','От задачи до завершения','У каждого правила есть действие, проверка и переход при успехе, несоответствии или недоступности проверки.')+
    `<div class="workflow">${stages.map(stage=>`<button class="workflow-step" data-source="PROTOCOL.md" data-line="${stage.start_line}"><span class="step-number">${escapeHTML(stage.title.split('.')[0])}</span><span><h3>${escapeHTML(stage.title.replace(/^\d+\.\s*/,''))}</h3><p>${escapeHTML(doc.blocks.find(block=>block.section_id===stage.id&&block.kind==='paragraph')?.text||'')}</p></span></button>`).join('')}</div>`;
}

function renderMemory() {
  const files=state.catalog.documents.filter(doc=>doc.path.startsWith('memory/'));
  $('main').innerHTML=header('ПРОДОЛЖЕНИЕ РАБОТЫ МЕЖДУ СЕССИЯМИ','Устройство памяти проекта','Память проекта связывает цель, решения, основания и результаты проверок между сессиями.')+`<div class="memory-layers"><div class="memory-layer"><div class="layer-number">УРОВЕНЬ 01</div><h3>Диалог</h3><p>Текущая беседа. При сжатии и смене сессии детали могут потеряться.</p></div><div class="memory-layer featured"><div class="layer-number">УРОВЕНЬ 02 · ИСТОЧНИК ИСТИНЫ</div><h3>Файлы проекта</h3><p>Состояние, решения и проверки доступны человеку и разным инструментам.</p></div><div class="memory-layer"><div class="layer-number">УРОВЕНЬ 03</div><h3>Память инструмента</h3><p>Указатель на проект и особенности инструмента. Правила и решения остаются в файлах.</p></div></div>${sectionButton('10.1','Открыть правило трёх уровней')}<div class="section-heading"><h2>Письменная память проекта</h2></div><div class="cards-grid">${files.map(doc=>{const name=doc.path.split('/').pop(),role=ROLES[name]||[name,'Дополнительный документ памяти.'];return `<button class="memory-file" data-source="${escapeHTML(doc.path)}" data-line="1"><span class="file-icon" aria-hidden="true">▤</span><span><b>${escapeHTML(name)}</b><h3>${escapeHTML(role[0])}</h3><p>${escapeHTML(role[1])}</p></span></button>`;}).join('')}</div><div class="section-heading"><h2>Как память входит в следующий шаг</h2>${badge('Механизм реализован')}</div><div class="memory-map"><div class="map-node"><strong>Источники и основания</strong><p>Версии записей, условия применимости, решения и открытые вопросы.</p></div><span class="flow-arrow" aria-hidden="true">→</span><div class="map-node accent"><strong>Контекст текущего шага</strong><p>Цель + ограничения + необходимые основания. Основания включаются вместе с точными версиями; сохранённые снимки доступны для чтения.</p></div></div><p class="small-note">Сжатие должно позволять восстановить основания результата. Полезность такого механизма проверяется опытом продолжения в новой сессии.</p><div class="button-row"><a class="primary-button" href="#records">Открыть записи памяти →</a><a class="secondary-button" href="#labs">Сценарий проверки памяти →</a></div>`;
  const suggestions=[
    ['Цель исчезает среди деталей','Закреплять цель текущего шага','Хранить цель, действующее решение, запреты и следующий проверяемый шаг отдельной краткой записью. Обновлять её при изменении основания задачи.','Проверить, продолжает ли модель именно принятую задачу после отвлекающей истории.','10.1'],
    ['Резюме сохраняет итог, но теряет причину','Сжимать с сохранением основания','Передавать потребность → ограничение прежнего средства → выбранный переход → результат. Добавлять условия применимости и нерешённые вопросы.','Сравнить с обычным резюме при одинаковом пределе объёма: может ли новая сессия объяснить необходимость перехода?','6.3'],
    ['Удалённое условие меняет вывод','Делать сжатие обратимым','Краткая запись ссылается на точный фрагмент и версию. Полный материал остаётся доступным для восстановления; без инструмента чтения ссылка служит только указанием происхождения.','Дать случай с исключением и проверить восстановление условия. Пятый вариант стенда разрешает ограниченное чтение сохранённых снимков.','6.3'],
    ['Исправлена опора, а старый вывод живёт','Хранить зависимости выводов','Запись результата указывает основания. При изменении источника зависимые выводы получают статус «требует повторной проверки»; прежняя версия остаётся в истории.','Изменить одно основание и проверить, найдены ли все известные зависимые результаты.','6.1'],
    ['Большой объём вытесняет нужное','Собирать контекст по задаче и основаниям','Сначала цель и обязательные ограничения, затем нужные записи и их основания. Если цепь не помещается в бюджет, показывать пробел и дробить шаг.','Измерять потери условий и качество продолжения, а также реальный расход. Короткий текст сам по себе не критерий успеха.','2.3'],
    ['Последняя запись вытесняет обоснованную','Различать новизну и пересмотр','Новое утверждение хранить вместе с источником и статусом. Замена решения требует основания и связи с прежним; противоречие нельзя стирать при сжатии.','Дать конфликт версий и проверить, отличает ли модель новое свидетельство от необоснованного утверждения.','3.2']
  ];
  const fields=[['Содержание','Что сохраняется: факт, решение, ограничение или вопрос.'],['Потребность','Какая проблема потребовала записи: например, ИИ потерял условие решения при смене сессии.'],['Основания','Источник, его версия и точный фрагмент; либо ссылка на запись.'],['Переход','Что изменили и почему это должно помочь: например, сохраняем условие вместе с решением.'],['Условия','Где вывод применим, какие исключения и пробелы известны.'],['Проверка','Способ, материал, исход и свидетельство проверки.'],['История','Статус, прежняя версия и причина пересмотра.']];
  $('main').insertAdjacentHTML('beforeend',`<div class="section-heading"><h2>Где лежат тексты и результаты</h2></div><div class="card storage-map"><div><strong>PROTOCOL.md + memory/</strong><p>Действующие правила, состояние, решения и история. ${sourceButton('memory/STATE.md',1,'Открыть состояние','link-button')}</p></div><div><strong>data/memory.sqlite3</strong><p>Неизменяемые версии записей, снимки источников, события и очередь пересмотра. <a href="#records">Открыть хранилище →</a></p></div><div><strong>atlas/annotations.json</strong><p>Пояснения и вопросы с цитатами и версиями. Это отдельный слой редакторских заметок.</p></div><div><strong>docs/LAB_CONTRACT.md</strong><p>Отдельные правила измерений стенда. ${sourceButton('docs/LAB_CONTRACT.md',1,'Прочитать контракт','link-button')}</p></div><div><strong>runs/идентификатор/result.json</strong><p>Снимок источников, все запросы и ответы, расход и оценки одного опыта. Другой прогон получает отдельную папку.</p></div><div><strong>Производный каталог</strong><p>Сервер собирает его из источников для экрана. Команда сборки может сохранить его в build/catalog.json; этот файл пересоздаётся.</p></div></div><div class="section-heading"><h2>Устройство версионной записи</h2>${badge('Схема реализована')}</div><p class="small-note">Markdown остаётся источником действующих правил. SQLite хранит отдельные записи, их версии, основания и очередь проверки; импорт переносит точные цитаты.</p><div class="table-wrap markdown"><table><thead><tr><th scope="col">Поле</th><th scope="col">Зачем оно нужно</th></tr></thead><tbody>${fields.map(([name,description])=>`<tr><td>${name}</td><td>${description}</td></tr>`).join('')}</tbody></table></div><div class="card"><h3>Пример основания из истории</h3><p>После E-001 появилось правило о введении терминов. В E-002 нарушение повторилось уже после записи правила. Тогда добавили проверку черновика. У проверки остались ограничения, поэтому запись результата должна сохранять и их.</p>${sectionButton('E-002','Полный разбор E-002','memory/ERRORS.md')}</div>`);
  $('main').insertAdjacentHTML('beforeend',`<div class="section-heading"><h2>Рекомендации и способы их проверки</h2>${badge('Гипотезы для проверки','proposal')}</div><p class="small-note">Каждый механизм отвечает на конкретную потерю. В записи нужно объяснить, какая проблема возникла, почему выбрано исправление и в каких условиях оно поможет. Полезность механизмов ещё не установлена.</p><div class="cards-grid">${suggestions.map(([problem,title,mechanism,test,prefix])=>`<article class="card"><div class="eyebrow">${escapeHTML(problem)}</div><h3>${escapeHTML(title)}</h3><p>${escapeHTML(mechanism)}</p><p><strong>Проверка:</strong> ${escapeHTML(test)}</p>${sectionButton(prefix,'Основание предложения')}</article>`).join('')}</div>`);
}

function getBullet(text,label) {
  const line=text.split(/\r?\n/).find(line=>line.includes(`**${label}:**`) || line.includes(`**${label}:`));
  return line?plain(line.replace(/^-\s*/, '').replace(new RegExp(`^\\*\\*${label}:\\*\\*\\s*`),'')):'';
}

function renderHistory(params) {
  const tab=params.get('tab')||state.historyTab;state.historyTab=tab;
  const doc=docByPath(tab==='decisions'?'memory/DECISIONS.md':'memory/ERRORS.md');
  const sections=doc.sections.filter(section=>/^[ED]-\d{3}\s/.test(section.title));
  const body=sections.map(section=>{
    const text=sectionText(doc,section),id=section.title.split(' ')[0];
    const summary=tab==='decisions'?(text.split(/\r?\n/).find(line=>line.startsWith('Решение:'))||'').replace(/^Решение:\s*/,''):getBullet(text,'Что произошло');
    const status=tab==='decisions'?(text.split(/\r?\n/).find(line=>line.startsWith('Статус:'))||'').replace(/^Статус:\s*/,''):getBullet(text,'Статус');
    return `<article class="timeline-item"><div class="timeline-id">${escapeHTML(id)}</div><div class="timeline-card"><h3>${escapeHTML(section.title.replace(/^[ED]-\d{3}\s*·\s*/,''))}</h3><p>${escapeHTML(plain(summary))}</p>${status?`<div class="status-text"><strong>Статус в журнале:</strong> ${escapeHTML(plain(status))}</div>`:''}${sourceButton(doc.path,section.start_line,'Открыть полный разбор','link-button')}</div></article>`;
  }).join('');
  $('main').innerHTML=header('ОТ ОГРАНИЧЕНИЯ К НОВОМУ СРЕДСТВУ','Развитие протокола','Ошибки и решения сохранены вместе с причинами. Каждая запись открывается в исходном журнале.')+`<div class="view-tabs" role="tablist" aria-label="История"><button class="tab" role="tab" aria-selected="${tab==='errors'}" data-history-tab="errors">Разбор ошибок · ${docByPath('memory/ERRORS.md').sections.filter(s=>/^E-\d{3}\s/.test(s.title)).length}</button><button class="tab" role="tab" aria-selected="${tab==='decisions'}" data-history-tab="decisions">Решения · ${docByPath('memory/DECISIONS.md').sections.filter(s=>/^D-\d{3}\s/.test(s.title)).length}</button></div>${body}`;
}

function renderLabs() {
  $('main').innerHTML=protocolAboutHTML()+protocolSetupRouteHTML('labs')+header('ПРОВЕРКА ПРОТОКОЛА НА ПРАКТИКЕ','Проверки ответов и памяти','Механизмы проверяются на конкретных ответах и задачах. Результат проверки всегда имеет границы.')+`<section class="card lab-card">${badge('Работает локально','')}<h2>Проверка черновика</h2><p>Скрипт ищет ссылки на ещё не объяснённое, длинные абзацы, неопределённые термины, расплывчатые слова и формулы без пояснений.</p><form id="checker-form"><label class="form-label" for="draft">Текст ответа</label><textarea id="draft" class="draft-input" placeholder="Вставьте черновик ответа для проверки…" required maxlength="80000"></textarea><label class="form-label" for="terms">Термины, которым нужно определение</label><input id="terms" class="text-input" placeholder="Например: простое число; предел" maxlength="3000"><p class="small-note">Необязательно. Разделяйте термины точкой с запятой; проверяется буквальное написание.</p><label class="checkbox-label"><input id="require-tokens" type="checkbox" checked>Проверить упоминание отчёта о токенах</label><div class="button-row"><button type="submit" class="primary-button">Проверить ответ →</button><button type="button" class="secondary-button" id="load-example">Вставить пример нарушения</button></div></form><div id="check-results" class="check-results" aria-live="polite"></div></section><section class="card lab-card">${badge('Стенд реализован','')}<h2>Сжатие и восстановление памяти</h2><p>Один снимок передаём в новую сессию шестью способами. Проверяем, сохранились ли цель, актуальные решения и основания.</p><div class="memory-layers"><div class="memory-layer"><h3>Полный материал</h3><p>Контроль без сокращения.</p></div><div class="memory-layer"><h3>Обычное резюме</h3><p>Краткий связный пересказ.</p></div><div class="memory-layer featured"><h3>Точные записи</h3><p>Версии, статусы и проверка ссылок. Структура и чтение доступны отдельными условиями.</p></div></div><button class="secondary-button" id="open-lab-plan">Прочитать сценарий опыта →</button><p class="small-note">Эффективность сжатия устанавливается оценкой результатов. Наличие стенда не доказывает преимущество метода.</p><div id="memory-error" role="status"></div><div id="memory-setup"><p class="small-note">Читаем снимок и настройки подключения…</p></div><div id="saved-runs"></div><div id="memory-run"></div><div id="memory-review"></div></section><div class="section-heading"><h2>Что добавляется по мере проверки</h2></div><div class="cards-grid"><div class="card">${badge('Стенд реализован')}<h3>Удержание цели</h3><p>Ограничение в начале, середине и конце отвлекающей истории.</p><button class="secondary-button" data-episode="attention-start">Открыть сценарий</button></div><div class="card">${badge('Стенд реализован')}<h3>Пересмотр основания</h3><p>Новые данные меняют опору. Проверяем прямые и транзитивные зависимости, сохраняем независимые выводы.</p><button class="secondary-button" data-episode="revision">Открыть сценарий</button></div></div><div class="section-heading"><h2>Сравнение сохранённых прогонов</h2></div><div id="comparison-report"></div>`;
  mountMemoryLab();
}

async function renderSource(params) {
  const path=params.get('path');let doc;try{doc=await sourceDocument(path);}catch{doc=null;}
  if(state.page!=='source')return;
  if(!doc){$('main').innerHTML='<div class="error-state"><h2>Документ недоступен</h2><p>В каталоге нет такого источника.</p><a href="#rules?tab=documents">Открыть доступные документы →</a></div>';return;}
  const requestedSha=params.get('sha');
  if(requestedSha && requestedSha!==doc.sha256){
    $('main').innerHTML=`<div class="error-state"><h2>Источник изменился</h2><p>Ссылка относится к другой версии ${escapeHTML(path)}. Прежний номер строки может указывать на другое содержание.</p>${sourceButton(path,1,'Открыть актуальный документ','secondary-button')}</div>`;
    return;
  }
  const line=Math.max(1,Number(params.get('line'))||1);
  const section=doc.sections.filter(s=>s.start_line<=line && s.end_line>=line).sort((a,b)=>b.level-a.level)[0];
  const full=params.get('full')==='1'||!section||!path.endsWith('.md');
  const blocks=full?doc.blocks:doc.blocks.filter(block=>block.section_id===section.id);
  const children=doc.sections.filter(item=>item.parent_id===section?.id);
  const pages=doc.sections;
  const pageIndex=pages.findIndex(item=>item.id===section?.id);
  const ancestors=[];
  for(let parent=section?.parent_id;parent;){const item=pages.find(item=>item.id===parent);if(!item)break;ancestors.unshift(item);parent=item.parent_id;}
  const readerNav=path.endsWith('.md')?`<nav class="source-reader-nav" aria-label="Чтение документа"><div class="reader-breadcrumbs">${ancestors.map(item=>sourceButton(path,item.start_line,item.title,'link-button')).join(' / ')}</div><div class="reader-controls">${pageIndex>0?sourceButton(path,pages[pageIndex-1].start_line,'← Предыдущий пункт','secondary-button'):''}<div class="reader-select-label"><label for="reader-section">Перейти к пункту</label><select id="reader-section" data-reader-path="${escapeHTML(path)}">${pages.map(item=>`<option value="${item.start_line}" ${item.id===section?.id?'selected':''}>${escapeHTML(item.title)}</option>`).join('')}</select></div>${pageIndex<pages.length-1?sourceButton(path,pages[pageIndex+1].start_line,'Следующий пункт →','secondary-button'):''}</div>${full?sourceButton(path,section?.start_line||1,'Читать по пунктам','secondary-button'):''}</nav>`:'';
  const childLinks=!full&&children.length?`<nav class="source-reader-children" aria-label="Пункты раздела"><h3>Пункты раздела</h3>${children.map(item=>sourceButton(path,item.start_line,item.title,'reader-child')).join('')}</nav>`:'';
  const title=full?(doc.sections[0]?.title||path):section.title;
  const translationDocument=AtlasI18n.documents.find(item=>item.path===path);
  const pendingTranslations=translationDocument?.pending||0;
  const related=state.catalog.annotations.filter(note=>note.sources.some(ref=>ref.path===path && ref.start_line>=(section?.start_line||line) && ref.start_line<=(section?.end_line||line)));
  $('main').innerHTML=header('ИСХОДНЫЙ ДОКУМЕНТ',escapeHTML(title),path.endsWith('.md')?(full?'Полный текст · ':'Чтение по пунктам · ')+path:'Исходный код проверки доступен для чтения и комментариев.')+`${readerNav}${!full?'<details class="reader-tools"><summary>Файл, редактирование и полный текст</summary>':''}<div class="source-bar"><div><strong>${escapeHTML(path)}</strong><br><span class="version">версия ${doc.sha256.slice(0,12)} · ${full?doc.line_count+' строк':'строки '+section.start_line+'–'+section.end_line}</span></div><div class="button-row">${fileDownloadLink(path)}${path==='README.md'||path==='docs/CONNECTING_AI.md'?connectionBundleLink('project','Скачать приложение с сервером · ZIP')+'<a class="secondary-button" href="https://www.python.org/downloads/" target="_blank" rel="noopener noreferrer">Скачать Python ↗</a>':''}${!full?`<button class="secondary-button" data-full-source="${escapeHTML(path)}">Показать весь документ</button>`:''}${path.endsWith('.md')?`<a class="secondary-button" href="#translate?${new URLSearchParams({path})}">Русский ↔ English</a><a class="primary-button" href="#edit?${new URLSearchParams({path})}">Редактировать</a>`:''}<a class="secondary-button" href="#rules?tab=documents">Все документы</a></div></div>${!full?'</details>':''}${AtlasI18n.language==='en'&&pendingTranslations?`<p class="notice">${pendingTranslations} units need an English update. Those units show the current Russian original. <a href="#translate?${new URLSearchParams({path})}">Update translation</a></p>`:''}<div class="source-content markdown">${blocks.filter(block=>full||block.kind!=='heading').map(block=>`<div data-translation-content class="source-block ${block.start_line<=line&&block.end_line>=line?'highlighted':''}" id="block-${block.start_line}">${blockHTML(block)}</div>`).join('')}</div>${childLinks}${path==='PROTOCOL.md'?'<div id="rule-implementation"></div>':''}`;
  linkMentionedFiles($('main'));
  if(path==='PROTOCOL.md')await mountRuleImplementation(section,full);
  if(related.length){$('main').insertAdjacentHTML('beforeend',`<hr><div class="inspector-label">СВЯЗАННЫЕ ВОПРОСЫ</div>${related.map(note=>`<p><button class="link-button" data-note="${escapeHTML(note.id)}">${escapeHTML(note.title)}</button></p>`).join('')}`);}
}

function marked(text,query){
  const lower=text.toLocaleLowerCase('ru'),needle=query.toLocaleLowerCase('ru');
  const at=lower.indexOf(needle);if(at<0)return escapeHTML(text);
  return escapeHTML(text.slice(0,at))+'<mark>'+escapeHTML(text.slice(at,at+query.length))+'</mark>'+escapeHTML(text.slice(at+query.length));
}

function renderSearch(params) {
  const query=(params.get('q')||'').trim();$('search-input').value=query;
  if(!query){$('main').innerHTML=header('ПОИСК ПО ИСХОДНИКАМ','Найти основание','Введите слово, обозначение правила или название решения в поле поиска.');return;}
  const results=[];
  for(const rule of formRules())if(rule.id.toLocaleLowerCase('ru')===query.toLocaleLowerCase('ru'))results.push({path:'PROTOCOL.md',line:rule.line,title:rule.id+' '+rule.title,snippet:rule.text});
  for(const doc of state.catalog.documents){
    for(const block of doc.blocks){
      const translated=AtlasI18n.source(block.text,block);
      const searched=translated.toLocaleLowerCase().includes(query.toLocaleLowerCase())?translated:block.text;
      if(!searched.toLocaleLowerCase().includes(query.toLocaleLowerCase()))continue;
      const lines=searched.split(/\r?\n/),offset=lines.findIndex(line=>line.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru')));
      const hit=lines[offset],at=hit.toLocaleLowerCase('ru').indexOf(query.toLocaleLowerCase('ru'));
      const snippet=hit.slice(Math.max(0,at-90),Math.min(hit.length,at+query.length+180));
      const section=doc.sections.find(section=>section.id===block.section_id);
      results.push({path:doc.path,line:searched===block.text?block.start_line+offset:block.start_line,title:section?.title||doc.path,snippet});
    }
  }
  $('main').innerHTML=header('ПОИСК ПО ИСХОДНИКАМ',`«${escapeHTML(query)}»`,`Найдено фрагментов: ${results.length}. Поиск по правилам, памяти и коду проверки.`)+(results.length?results.map(result=>`<button class="search-result" data-source="${escapeHTML(result.path)}" data-line="${result.line}"><strong>${escapeHTML(result.title)}</strong><p>${marked(result.snippet,query)}</p><small>${escapeHTML(result.path)} · строка ${result.line} ↗</small></button>`).join(''):'<div class="empty-state">Совпадений нет. Попробуйте другое слово или обозначение правила.</div>');
}

function showNote(id){
  const note=state.catalog.annotations.find(note=>note.id===id);if(!note)return;
  $('main').querySelector('.outline-note')?.remove();
  $('main').insertAdjacentHTML('beforeend',`<aside class="card outline-note"><h2>${escapeHTML(note.title)}</h2><p>${escapeHTML(note.body)}</p>${note.sources.map(ref=>sourceButton(ref.path,ref.start_line,ref.label)).join('')}</aside>`);
  $('main').querySelector('.outline-note').scrollIntoView({block:'center'});
  $('announcer').textContent='Открыты основания: '+note.title;
}

function navigateSource(path,line=1,full=false){
  const doc=docByPath(path);if(!doc)return;
  location.hash='source?'+new URLSearchParams({path,line:String(line),sha:doc.sha256,...(full?{full:'1'}:{})});
}

function render(){
  if(!state.catalog)return;
  CSS.highlights?.delete('comment-location');
  const [page,query='']=location.hash.slice(1).split('?');state.page=page==='home'||!page?'rules':page;
  const params=new URLSearchParams(query);
  const active=navigationSection(state.page);
  $('page-label').textContent=NAV.find(item=>item[0]===active)?.[1]||'Протокол';
  const navLink=([key,label,icon])=>`<a href="#${key}" class="nav-item ${active===key?'active':''}" ${active===key?'aria-current="page"':''}><span class="nav-icon" aria-hidden="true">${icon}</span>${label}</a>`;
  $('navigation').innerHTML=NAV.map(navLink).join('');

  const renderers={translations:renderTranslationsOverview,'translate-ui':()=>renderUITranslationEditor(params),translate:()=>renderTranslationEditor(params),home:renderHome,'protocol-setup':renderImprovement,results:renderResults,improvement:renderImprovement,'project-start':renderProjectStart,onboarding:renderStart,'project-state':renderProjectState,settings:renderSettings,edit:()=>renderSourceEditor(params),connections:renderConnections,rules:()=>renderRules(params),workflow:renderWorkflow,memory:renderMemory,records:()=>renderRecords(params),requirements:()=>{location.replace('#rules');},regulator:()=>renderAdaptive(),'regulator-previous':renderRegulator,history:()=>renderHistory(params),labs:renderLabs,source:()=>renderSource(params),search:()=>renderSearch(params),comments:renderComments,'lab-plan':renderLabPlan};
  const renderedPage=state.page;
  renderers.reader=renderReader;
  const renderRevision=(state.renderRevision||0)+1;state.renderRevision=renderRevision;
  Promise.resolve().then(()=>(renderers[state.page]||renderHome)()).then(()=>{
    if(state.renderRevision===renderRevision){
      refreshSetupRoute();
      appendLearningTransition(renderedPage);
      if(renderedPage==='source'&&params.get('full')!=='1')requestAnimationFrame(()=>window.scrollTo(0,0));
      if(state.page==='source' && params.get('full')==='1' && Number(params.get('line'))>1)requestAnimationFrame(()=>{document.querySelector('.source-block.highlighted')?.scrollIntoView({block:'start'});updateOutlinePosition();});
    }
  }).catch(error=>{
    if(state.renderRevision!==renderRevision)return;
    $('main').innerHTML='<div class="check-message" role="alert">Не удалось открыть раздел: '+escapeHTML(error.message)+'</div>';
  });
  $('main').scrollTop=0;window.scrollTo(0,0);
  document.querySelector('.sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');
  $('announcer').textContent='Открыт раздел: '+$('page-label').textContent;
}

async function loadCatalog(refresh=false){
  try{
    await AtlasI18n.ready;
    if(refresh)await AtlasI18n.refresh();
    const response=await fetch('/api/catalog',{cache:'no-store'}),data=await response.json();
    if(!response.ok)throw new Error(data.detail||data.error||'Не удалось загрузить каталог.');
    if(data.schema_version!==1)throw new Error('Версия каталога не поддерживается интерфейсом.');
    state.catalog=data;
    $('revision-label').textContent='Версия '+data.catalog_revision.slice(0,8);
    $('coverage-footer').textContent=`${data.coverage.documents} документов · полный исходный текст`;
    $('document-links').innerHTML=[['PROTOCOL.md','PROTOCOL.md'],['memory/STATE.md','Состояние проекта'],['memory/DECISIONS.md','Журнал решений'],['check_answer.py','Код проверки']].map(([path,label])=>`<a class="doc-link" href="#source?${new URLSearchParams({path,sha:docByPath(path).sha256})}">${label}</a>`).join('')+'<a class="doc-link" href="#translations">RU ↔ EN</a>';
    $('notice').classList.add('hidden');render();
    const staleNotes=data.annotations.filter(note=>note.source_warnings?.length);
    if(staleNotes.length){$('notice').textContent=`У ${staleNotes.length} редакторских пояснений изменились цитаты источников. Их ссылки требуют обновления; документы доступны для чтения и редактирования.`;$('notice').classList.remove('hidden');}
    if(refresh)$('announcer').textContent='Источники обновлены.';
  }catch(error){
    $('notice').classList.remove('hidden');$('notice').textContent='Источники недоступны: '+error.message;
    if(!state.catalog)$('main').innerHTML='<div class="error-state"><h2>Не удалось открыть атлас</h2><p>'+escapeHTML(error.message)+'</p><button class="secondary-button" data-retry>Повторить загрузку</button></div>';
  }
}

async function runChecker(form){
  const submit=form.querySelector('button[type=submit]'),caption=submit.textContent,revision=state.renderRevision;submit.disabled=true;submit.textContent='Проверяем…';
  $('check-results').innerHTML='';
  try{
    const response=await fetch('/api/check-answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({language:AtlasI18n.language,text:$('draft').value,terms:$('terms').value.split(';').map(term=>term.trim()).filter(Boolean),require_tokens:$('require-tokens').checked})});
    const result=await response.json();if(state.renderRevision!==revision)return;if(!response.ok)throw new Error(result.error||'Ошибка проверки.');
    $('check-results').innerHTML=`<div class="check-summary"><strong>${result.warning_count===0?'Предупреждений не найдено':`Найдено предупреждений: ${result.warning_count??'не установлено'}`}</strong><p class="small-note">${escapeHTML(result.limits)}</p></div>${result.messages.map(message=>`<div data-original class="check-message">${escapeHTML(message)}</div>`).join('')}<p class="version">Проверено скриптом версии ${escapeHTML(result.checker_sha256.slice(0,12))}</p>`;
  }catch(error){if(state.renderRevision===revision)$('check-results').innerHTML=`<div class="error-state">${escapeHTML(error.message)}</div>`;}
  finally{submit.disabled=false;submit.textContent=caption;}
}

document.addEventListener('click',async event=>{
  if(event.target.closest('.skip-link')){event.preventDefault();$('main').focus();return;}
  const target=event.target.closest('button');if(!target)return;
  if(target.dataset.source){navigateSource(target.dataset.source,Number(target.dataset.line)||1);return;}
  if(target.dataset.prefix){const doc=docByPath(target.dataset.doc||(/^2\./.test(target.dataset.prefix)?'memory/REGULATOR_PREVIOUS.md':'PROTOCOL.md')),section=doc&&findSection(doc,target.dataset.prefix);if(section)navigateSource(doc.path,section.start_line);return;}
  if(target.dataset.note){showNote(target.dataset.note);return;}
  if(target.dataset.fullSource){navigateSource(target.dataset.fullSource,1,true);return;}
  if(target.dataset.ruleTab){location.hash='rules?tab='+target.dataset.ruleTab;return;}
  if(target.dataset.historyTab){location.hash='history?tab='+target.dataset.historyTab;return;}
  if(target.hasAttribute('data-retry')){loadCatalog(true);return;}
  if(target.id==='load-example'){$('draft').value=AtlasI18n.text('Очевидно, простые числа обладают особым свойством. Подробнее объясню ниже.\n\n2 + 2 = 4');$('terms').value=AtlasI18n.text('простые числа');$('draft').focus();return;}
  if(target.id==='open-lab-plan'){location.hash='lab-plan';return;}
});

async function renderLabPlan(){
  $('main').innerHTML='<div class="loading">Читаем сценарий…</div>';
  try{
    const doc=await sourceDocument('docs/EXPERIMENT_MEMORY.md');
    if(state.page!=='lab-plan')return;
    $('main').innerHTML=header('СЦЕНАРИЙ ПЕРВОГО ОПЫТА','Сжатие и восстановление','Сценарий и границы интерпретации результатов.')+`<a class="secondary-button" href="#labs">← К проверкам ответов и памяти</a><div class="source-content markdown">${doc.blocks.map(block=>blockHTML(block)).join('')}</div>`;
  }catch(error){if(state.page==='lab-plan')$('main').innerHTML='<div class="error-state">'+escapeHTML(error.message)+'</div>';}
}
document.addEventListener('submit',event=>{if(event.target.id==='checker-form'){event.preventDefault();runChecker(event.target);} });
$('search-form').addEventListener('submit',event=>{event.preventDefault();location.hash='search?'+new URLSearchParams({q:$('search-input').value.trim()});});
$('search-input').addEventListener('input',()=>{clearTimeout(state.searchTimer);state.searchTimer=setTimeout(()=>{if($('search-input').value.trim())location.hash='search?'+new URLSearchParams({q:$('search-input').value.trim()});},300);});
$('refresh').addEventListener('click',()=>loadCatalog(true));
$('menu-toggle').addEventListener('click',()=>{const opened=document.querySelector('.sidebar').classList.toggle('open');$('menu-toggle').setAttribute('aria-expanded',String(opened));});
document.addEventListener('keydown',event=>{if(event.key==='/'&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)){event.preventDefault();$('search-input').focus();}if(event.key==='Escape'){document.querySelector('.sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');}});
window.addEventListener('hashchange',render);
document.addEventListener('DOMContentLoaded',()=>loadCatalog(),{once:true});
setInterval(async()=>{
  if(!state.catalog||document.hidden)return;
  try{const response=await fetch('/api/catalog',{cache:'no-store'});const data=await response.json();if(!response.ok)throw new Error(data.error);if(data.catalog_revision!==state.catalog.catalog_revision){$('notice').innerHTML='Документы проекта изменились. Открытый атлас показывает прежний снимок. <button class="link-button" data-retry>Обновить источники</button>';$('notice').classList.remove('hidden');}}
  catch(error){$('notice').textContent='Не удалось проверить актуальность источников: '+error.message;$('notice').classList.remove('hidden');}
},20000);

'use strict';

// Navigation follows the content actually rendered, including asynchronous previews.
let outlineTargets = [];
let outlineSignature = '';
let outlineFrame;
function refreshOutline() {
  const main = $('main'), panel = $('inspector');
  const params = new URLSearchParams(location.hash.split('?')[1]);
  const catalogView = state.page === 'rules' && state.rulesTab === 'sections';
  const sourceDoc = state.page === 'source' ? docByPath(params.get('path')) : null;
  let entries;
  if (catalogView || sourceDoc?.path.endsWith('.md')) {
    const doc = sourceDoc || protocol();
    const selected=sourceDoc&&doc.sections.filter(item=>item.start_line<=(Number(params.get('line'))||1)&&item.end_line>=(Number(params.get('line'))||1)).sort((a,b)=>b.level-a.level)[0];
    const branch=new Set();
    for(let item=selected;item;item=doc.sections.find(parent=>parent.id===item.parent_id))branch.add(item.id);
    entries = doc.sections.filter(section => section.level > 1 && (!sourceDoc||params.get('full')==='1'||section.level===2||branch.has(section.id)||branch.has(section.parent_id))).map(section => ({
      title: AtlasI18n.source(doc.blocks.find(block => block.start_line === section.start_line)?.text || section.title).replace(/^#+\s*/, '').trim(),
      level: section.level,
      target: sourceDoc ? document.getElementById('block-' + section.start_line) : null,
      path: doc.path, line: section.start_line
    }));
  } else {
    const container = state.page === 'edit' ? $('source-edit-preview') : main;
    entries = [...(container?.querySelectorAll('h2,h3,h4,h5,h6') || [])]
      .filter(heading => !heading.closest('dialog,[hidden],.learning-transition,.outline-note'))
      .map(heading => ({title: heading.textContent.trim(), level: Number(heading.tagName.slice(1)), target: heading}));
  }
  const visible = entries.length > 1 && !['rules','results','improvement','project-start'].includes(state.page);
  panel.hidden = !visible;
  document.querySelector('.content-layout').classList.toggle('without-outline', !visible);
  const signature = JSON.stringify([state.page, location.hash, entries.map(({title,level,line}) => [title,level,line])]);
  outlineTargets = entries;
  if (signature === outlineSignature) return;
  outlineSignature = signature;
  const label = AtlasI18n.language === 'en' ? 'Contents' : 'Оглавление';
  panel.setAttribute('aria-label', label);
  panel.innerHTML = visible ? `<details class="document-outline" ${window.matchMedia('(max-width:1000px)').matches?'':'open'}><summary class="eyebrow">${label}</summary><nav aria-label="${label}"><ol>${entries.map((entry,index) => `<li style="--outline-depth:${Math.max(0,entry.level-2)}"><button type="button" class="outline-link" data-outline="${index}">${escapeHTML(entry.title)}</button></li>`).join('')}</ol></nav></details>` : '';
  updateOutlinePosition();
}

function updateOutlinePosition() {
  let active = -1;
  outlineTargets.forEach((entry,index) => {
    if (entry.target?.getBoundingClientRect().top <= 140) active = index;
  });
  if(state.page==='source'&&!location.hash.includes('full=1')){const line=Number(new URLSearchParams(location.hash.split('?')[1]).get('line'))||1;active=outlineTargets.findIndex(entry=>entry.line===line);}
  if (active < 0) active = outlineTargets.findIndex(entry => entry.target);
  $('inspector').querySelectorAll('[data-outline]').forEach(button => {
    if (Number(button.dataset.outline) === active) button.setAttribute('aria-current','location');
    else button.removeAttribute('aria-current');
  });
}

document.addEventListener('click', event => {
  const button = event.target.closest('[data-outline]');
  if (!button) return;
  const entry = outlineTargets[Number(button.dataset.outline)];
  if (!entry) return;
  if (entry.target) {
    for (let parent = entry.target.parentElement; parent; parent = parent.parentElement) {
      if (parent.tagName === 'DETAILS') parent.open = true;
    }
    entry.target.scrollIntoView({block:'start'});
    entry.target.setAttribute('tabindex','-1');
    entry.target.focus({preventScroll:true});
    updateOutlinePosition();
  } else if (entry.path) navigateSource(entry.path,entry.line);
});
new MutationObserver(() => {
  cancelAnimationFrame(outlineFrame);
  outlineFrame = requestAnimationFrame(refreshOutline);
}).observe($('main'), {subtree:true,childList:true,characterData:true});
window.addEventListener('scroll', updateOutlinePosition, {passive:true});

document.addEventListener('change',event=>{
  const select=event.target.closest('[data-reader-path]');
  if(select)navigateSource(select.dataset.readerPath,Number(select.value));
});
