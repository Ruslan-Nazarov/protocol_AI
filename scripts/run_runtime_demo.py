"""Reproducible synthetic conference pipeline through CLI, HTTP, MCP and files."""
import io
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from protocol_atlas.catalog import digest
from protocol_atlas.project_runtime import ProjectRuntime,canonical
from protocol_atlas.runtime_cli import handler,mcp
from protocol_atlas.runtime_install import install


def main():
    project=ROOT/'build/runtime-demo'
    if (project/'.protocol/project.sqlite3').exists():
        import uuid
        project=ROOT/'build'/('runtime-demo-'+uuid.uuid4().hex[:8])
    project.mkdir(parents=True,exist_ok=True)
    installed=install(project,'api',ROOT);runtime=ProjectRuntime(project)
    sample=[{'id':1,'track':'AI'},{'id':2,'track':'AI'},{'id':3,'track':'Fintech'}]
    (project/'source.json').write_text(json.dumps(sample),encoding='utf-8')
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(runtime))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_address[1])+'/protocol/'
    transports=[]
    def call(transport,action,payload=None):
        payload=payload or {}
        if action not in ('status','context','export'):payload={'expected_revision':runtime.status()['revision'],**payload}
        transports.append({'transport':transport,'action':action})
        if transport=='cli':
            process=subprocess.run([sys.executable,installed['runner'],action,'--project',str(project),'--input','-'],
                                   input=json.dumps(payload),capture_output=True,encoding='utf-8',cwd=project)
            if process.returncode:raise RuntimeError(process.stderr)
            return json.loads(process.stdout)
        if transport=='http':
            request=Request(base+action,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with urlopen(request) as response:return json.load(response)
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'protocol_'+action,'arguments':payload}}
        output=io.StringIO();mcp(runtime,io.StringIO(json.dumps(request)+'\n'),output)
        result=json.loads(output.getvalue())['result']
        if result['isError']:raise RuntimeError(result['content'][0]['text'])
        return result['structuredContent']
    def part(ident,title,requires,volume):
        return {'id':ident,'title':title,'requires':requires,'type':ident,'volume':volume,
                'complexity':'Малый синтетический набор; факты реальной конференции здесь не проверяются.',
                'criteria':[{'id':'valid','kind':'command','text':'Проверить воспроизводимые условия готовности результата.'}]}
    def check(transport,ident,files,code):
        return call(transport,'check',{'stage_id':ident,'criterion_id':'valid','artifacts':files,'argv':[sys.executable,'-c',code]})
    try:
        call('cli','start',{'goal':'Демонстрация: данные → статистика → инфографика на синтетическом примере',
             'stages':[part('data','Проверить исходные данные',[],'Три сессии, уникальные ID и непустой трек'),
                       part('statistics','Посчитать статистику',['data'],'Общий итог и две группы'),
                       part('graphic','Собрать изображение',['statistics'],'SVG с названиями, числами и источником')],
             'executor':{'client':'demo','model':'unknown'}})
        check('http','data',['source.json'],'import json;p=json.load(open("source.json"));assert len(p)==3;assert len({x["id"] for x in p})==3;assert all(x["track"] for x in p)')
        call('mcp','complete_stage',{'stage_id':'data','artifacts':['source.json'],'summary':'Три уникальные тестовые сессии.'})
        stats={'total':len(sample),'tracks':{track:sum(s['track']==track for s in sample) for track in sorted({s['track'] for s in sample})}}
        (project/'stats.json').write_text(json.dumps(stats),encoding='utf-8')
        check('cli','statistics',['stats.json'],'import json;s=json.load(open("stats.json"));p=json.load(open("source.json"));assert s["total"]==len(p)==sum(s["tracks"].values());assert s["tracks"]=={"AI":2,"Fintech":1}')
        call('http','complete_stage',{'stage_id':'statistics','artifacts':['stats.json'],'summary':'Всего 3, AI 2, Fintech 1.'})
        package=call('mcp','export')
        package['operations']=[{'action':'observe','payload':{'kind':'continuation','summary':'Файловый клиент прочитал результат статистики.','origin':'file_client_report'}}]
        package['sha256']=digest(canonical({k:v for k,v in package.items() if k!='sha256'}).encode())
        call('cli','import',{'package':package})
        restored=call('cli','context')
        assert restored['state']['tasks'][0]['next_stage']=='graphic'
        svg='<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#102b36"/><g fill="#e8fff5" font-family="sans-serif"><text x="70" y="100" font-size="40">Synthetic conference example</text><text x="70" y="180" font-size="30">Total: 3 sessions</text><text x="70" y="290" font-size="32">AI: 2</text><text x="70" y="420" font-size="32">Fintech: 1</text><text x="70" y="650" font-size="22">Source: source.json — test data, not Digital Bridge</text></g><rect x="350" y="250" width="700" height="65" fill="#71dbc1"/><rect x="350" y="380" width="350" height="65" fill="#ffc16d"/></svg>'
        (project/'graphic.svg').write_text(svg,encoding='utf-8')
        check('mcp','graphic',['graphic.svg'],'import xml.etree.ElementTree as E;s=E.parse("graphic.svg").getroot();text=" ".join(s.itertext());assert s.attrib["width"]=="1280" and s.attrib["height"]=="720";assert all(v in text for v in ["AI: 2","Fintech: 1","Total: 3","test data"])')
        call('cli','complete_stage',{'stage_id':'graphic','artifacts':['graphic.svg'],'summary':'Проверены размеры, подписи и численные итоги SVG.'})
        state=runtime.status();assert state['tasks'][0]['status']=='awaiting_review'
        (project/'report.json').write_text(json.dumps({'synthetic':True,'transports':transports,'state':state},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'project':str(project),'revision':state['revision'],'status':state['tasks'][0]['status'],
                          'transports':sorted({t['transport'] for t in transports})+['files'],'database_bytes':state['diagnostics']['database_bytes']},ensure_ascii=False))
    finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
