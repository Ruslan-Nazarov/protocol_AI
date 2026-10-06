// Exercise connection preparation with no local AI configuration or API calls.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'..');
const elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,{value:'',innerHTML:'',textContent:'',hidden:false,scrollIntoView(){},focus(){}});return elements.get(id);};
const requests=[];
const context=vm.createContext({
  $,state:{page:'project-start'},document:{addEventListener(){}},
  localStorage:{getItem(){return null;},setItem(){}},
  protocolAboutHTML:()=>'',protocolSetupRouteHTML:()=>'',helpHint:()=>'',escapeHTML:x=>String(x),
  workspaceAPI:async url=>{
    requests.push(url);assert.equal(url,'/api/runtime-installation');
    return {configuration:null,configuration_sha256:'test-version',commands:Object.fromEntries(['codex','claude','gemini','generic','api','files'].map(client=>[client,'install --client '+client]))};
  }
});
function $(id){return element(id);}
vm.runInContext(fs.readFileSync(path.join(root,'protocol_atlas/web/project.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(root,'protocol_atlas/web/portal.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(root,'protocol_atlas/web/app.js'),'utf8').split('const ROLES =')[0],context);
(async()=>{
  assert.equal(vm.runInContext('NAV.length',context),4);
  for(const [page,parent] of [['source','rules'],['edit','rules'],['connections','project-start'],['records','results'],['labs','improvement'],['history','improvement']]){
    context.testPage=page;assert.equal(vm.runInContext('navigationSection(testPage)',context),parent);
  }
  await vm.runInContext('renderProjectStart()',context);
  assert.equal(element('project-prepare').disabled,false);
  for(const client of ['codex','claude','gemini','generic','api','files']){
    element('project-client').value=client;element('project-goal').value='';
    vm.runInContext('prepareProjectMessage()',context);
    assert.equal(element('project-handoff').hidden,false);
    assert.match(element('project-message').value,new RegExp('--client '+client));
    assert.match(element('project-message').value,/Затем уточни у меня рабочую задачу/);
    assert.doesNotMatch(element('project-message').value,/Подтверждённая настройка.*null/s);
    assert.match(element('project-download').href,/configuration_sha256=test-version/);
  }
  assert.deepEqual(requests,['/api/runtime-installation']);
  const task='Задача с "кавычками"',answer='Ответ\n</textarea><script>test</script>',evidence='Наблюдение';
  context.reviewArgs={task,answer,evidence};
  const prompt=vm.runInContext('reviewRequest(reviewArgs.task,reviewArgs.answer,reviewArgs.evidence,"sha-current")',context);
  assert.deepEqual(JSON.parse(prompt.split('Материалы для разбора (JSON):\n')[1]),{task,answer,evidence});
  assert.match(prompt,/sha-current/);
  assert.match(prompt,/недостаток свидетельств/);
  const missing=vm.runInContext('reviewRequest("","Ответ","","sha")',context);
  assert.match(missing,/Задача не предоставлена/);
  assert.match(missing,/Свидетельства выполнения проверок не предоставлены/);
  console.log('PASS: six client handoffs without local AI; review materials and missing-evidence handling.');
})().catch(error=>{console.error(error);process.exitCode=1;});
