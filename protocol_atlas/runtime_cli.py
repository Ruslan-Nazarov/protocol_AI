"""One JSON contract through CLI, stdio MCP, HTTP and portable files."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

from protocol_atlas.project_runtime import ProjectRuntime
from protocol_atlas.source_editor import SourceConflict


def invoke(runtime, action, payload=None):
    if action=='events':return {'events':runtime.events()}
    return runtime.dispatch(action,payload)


def mcp(runtime, incoming=None, outgoing=None):
    incoming,outgoing=incoming or sys.stdin,outgoing or sys.stdout
    for line in incoming:
        try:
            request=json.loads(line)
            method=request.get('method');ident=request.get('id')
            if ident is None:continue
            if method=='initialize':
                version=request.get('params',{}).get('protocolVersion','2025-06-18')
                result={'protocolVersion':version if version in ('2024-11-05','2025-03-26','2025-06-18','2025-11-25') else '2025-06-18',
                        'capabilities':{'tools':{}},'serverInfo':{'name':'protocol-ai','version':'1.0.0'}}
            elif method=='ping':result={}
            elif method=='tools/list':
                result={'tools':[{'name':'protocol_'+action,'description':description(action),
                                 'inputSchema':schema(action),
                                 'annotations':{'readOnlyHint':action in ('status','context','export','logic_profiles','admit_result'),'destructiveHint':action=='check','openWorldHint':action=='check'}}
                                for action in runtime.actions]}
            elif method=='tools/call':
                params=request.get('params',{});name=params.get('name','')
                if not name.startswith('protocol_'):raise ValueError('Неизвестный инструмент.')
                try:
                    value=runtime.dispatch(name[9:],params.get('arguments',{}))
                    result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'structuredContent':value,'isError':False}
                except (ValueError,SourceConflict,OSError) as exc:
                    result={'content':[{'type':'text','text':str(exc)}],'isError':True}
            else:
                outgoing.write(json.dumps({'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Method not found'}})+'\n');outgoing.flush();continue
            outgoing.write(json.dumps({'jsonrpc':'2.0','id':ident,'result':result},ensure_ascii=False)+'\n')
        except (ValueError,KeyError,TypeError) as exc:
            outgoing.write(json.dumps({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':str(exc)}})+'\n')
        outgoing.flush()


def description(action):
    return {'init':'Initialize this workspace only; no atlas memory is imported.',
            'set_verification':'Select criteria/formal/empirical/manual mode with reason; invalidate prior checks.',
            'admit_result':'Read only currently admitted formal conclusions. Does not certify semantics or execute external actions.',
            'status':'Current tasks, stages, checks and detected stale artifacts.',
            'context':'Restore current goal, constraints, feedback and next stage.',
            'start':'Record the human goal; the agent supplies stages or proposes a plan next.',
            'plan':'Agent-authored stages: id,title,requires,type,volume,complexity,criteria(id,text,kind),gate.',
            'begin_stage':'Begin an available stage; verified input results are required.',
            'select_logic':'Pin an explicit logic contract for a stage. Changes need a newer version and change_reason.',
            'logic_profiles':'Read supported logic profiles, languages, semantics, rules and checker version.',
            'check_logic':'Execute the fixed logic checker on candidate_path; preserve raw input and violations. Include candidate and results in artifacts.',
            'check':'Execute argv for a command criterion, or label agent/human review evidence. Bind artifacts.',
            'complete_stage':'Verify current artifacts against all criteria. This does not accept for the human.',
            'review':'Record an actual human_message: accepted/revise/rejected; target stage_ids when needed.',
            'observe':'Record a client observation with its origin; reports are not executed checks.',
            'interrupt':'Save interruption without inventing a completed result.',
            'connection':'Record declared capabilities and actually observed events.',
            'export':'Portable versioned snapshot and continuation context.',
            'import':'Import a matching package with optimistic version checks. Recheck imported evidence.',
            'storage':'Set host_event_limit (0–100000); no full prompts, tool bodies or artifact copies are kept.'}.get(action,action)+' Mutations require expected_revision; request_id enables retries.'


def schema(action):
    properties={'expected_revision':{'type':'integer','minimum':0},'request_id':{'type':'string'},
                'task_id':{'type':'string'},'stage_id':{'type':'string'},'goal':{'type':'string'},
                'stages':{'type':'array','items':{'type':'object'}},'criterion_id':{'type':'string'},
                'executor':{'type':'object','properties':{'client':{'type':'string'},'model':{'type':'string'}},'required':['client','model']},
                'artifacts':{'type':'array','items':{'type':'string'}},'argv':{'type':'array','items':{'type':'string'}},
                'timeout':{'type':'integer','minimum':1,'maximum':120},'passed':{'type':'boolean'},
                'evidence':{'type':'string'},'summary':{'type':'string'},'reason':{'type':'string'},
                'human_message':{'type':'string'},'outcome':{'enum':['accepted','revise','rejected']},
                'stage_ids':{'type':'array','items':{'type':'string'}},'package':{'type':'object'},
                'reply':{'type':'object'},
                'client':{'type':'string'},'capabilities':{'type':'object'},'host_event_limit':{'type':'integer'},
                'workflow_event_limit':{'type':'integer'},'command_output':{'enum':['none','errors','all']}}
    properties.update({'mode':{'enum':['criteria','formal','empirical','manual']},'name':{'type':'string'},'kind':{'type':'string'},'origin':{'type':'string'},'details':{'type':'object'},'event_id':{'type':'string'},
                       'contract':{'type':'object'},'candidate_path':{'type':'string'},'change_reason':{'type':'string'}})
    properties['stages']['items']={'type':'object','required':['id','title','requires','type','volume','complexity','criteria'],
        'properties':{'id':{'type':'string'},'title':{'type':'string'},'requires':{'type':'array','items':{'type':'string'}},
                      'type':{'type':'string'},'volume':{'type':'string'},'complexity':{'type':'string'},'gate':{'enum':['automatic','human']},
                      'criteria':{'type':'array','minItems':1,'items':{'type':'object','required':['id','text','kind'],
                                  'properties':{'id':{'type':'string'},'text':{'type':'string'},'kind':{'enum':['command','agent_review','human']}}}}}}
    fields={'init':['name'],'status':[],'context':[],'export':[],'logic_profiles':[],
            'set_verification':['task_id','stage_id','mode','reason'],'admit_result':['task_id','stage_id'],
            'start':['goal','stages','executor'],'plan':['task_id','stages'],'begin_stage':['task_id','stage_id'],
            'select_logic':['task_id','stage_id','contract','change_reason'],
            'check_logic':['task_id','stage_id','candidate_path','artifacts'],
            'check':['task_id','stage_id','criterion_id','artifacts','argv','timeout','passed','evidence'],
            'complete_stage':['task_id','stage_id','summary','artifacts'],'review':['task_id','outcome','human_message','stage_ids'],
            'observe':['task_id','kind','summary','origin','details','event_id'],'interrupt':['task_id','reason'],
            'connection':['client','capabilities'],'import':['package','reply'],'storage':['host_event_limit','workflow_event_limit','command_output']}
    names=fields[action]+([] if action in ('status','context','export','logic_profiles','admit_result') else ['expected_revision','request_id'])
    properties={key:value for key,value in properties.items() if key in names}
    required=[] if action in ('init','status','context','export','logic_profiles','admit_result') else ['expected_revision']
    required+= {'start':['goal'],'plan':['stages'],'begin_stage':['stage_id'],'check':['stage_id','criterion_id'],
                'set_verification':['stage_id','mode','reason'],'admit_result':['stage_id'],
                'select_logic':['stage_id','contract'],'check_logic':['stage_id','candidate_path','artifacts'],
                'complete_stage':['stage_id','summary','artifacts'],'review':['outcome','human_message'],
                'connection':['client']}.get(action,[])
    return {'type':'object','properties':properties,'required':required,'additionalProperties':True}


def handler(runtime):
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,value):
            body=json.dumps(value,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
        def local(self):
            port=self.server.server_address[1]
            host=self.headers.get('Host')
            return host in ('127.0.0.1:'+str(port),'localhost:'+str(port)) and self.headers.get('Origin') in (None,'http://'+host)
        def do_GET(self):
            if not self.local():self.reply(403,{'error':'Local origin required'});return
            path=urlsplit(self.path).path
            static={'/':('runtime_dashboard.html','text/html'),'/runtime_dashboard.js':('runtime_dashboard.js','text/javascript'),'/runtime_dashboard.css':('runtime_dashboard.css','text/css')}
            if path in static:
                name,media=static[path];body=(Path(__file__).resolve().parent/'web'/name).read_bytes()
                self.send_response(200);self.send_header('Content-Type',media+'; charset=utf-8');self.send_header('Content-Length',str(len(body)))
                self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body);return
            action=path.removeprefix('/protocol/')
            if action not in ('status','context','export','events','logic_profiles'):self.reply(404,{'error':'Unknown read operation'});return
            try:self.reply(200,invoke(runtime,action))
            except (ValueError,OSError) as exc:self.reply(400,{'error':str(exc)})
        def do_POST(self):
            if not self.local():self.reply(403,{'error':'Local origin required'});return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=1000000:raise ValueError('JSON body must be 1–1000000 bytes.')
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('Use application/json.')
                action=urlsplit(self.path).path.removeprefix('/protocol/')
                self.reply(200,invoke(runtime,action,json.loads(self.rfile.read(size))))
            except SourceConflict as exc:self.reply(409,{'error':str(exc)})
            except (ValueError,OSError) as exc:self.reply(400,{'error':str(exc)})
        def log_message(self,*args):pass
    return Handler


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stdin,'reconfigure'):sys.stdin.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=(*ProjectRuntime.actions,'events','install','hook','mcp','serve'))
    parser.add_argument('--project',type=Path,default=Path.cwd())
    parser.add_argument('--input',default=None,help='JSON file or - for stdin')
    parser.add_argument('--client',default='codex',choices=('codex','claude','gemini','generic','api','files'))
    parser.add_argument('--port',type=int,default=8770)
    args=parser.parse_args()
    try:
        runtime=ProjectRuntime(args.project)
        if args.action=='mcp':mcp(runtime);return
        if args.action=='serve':
            server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(runtime))
            print('Protocol runtime: http://127.0.0.1:'+str(server.server_address[1]),file=sys.stderr,flush=True)
            try:server.serve_forever()
            except KeyboardInterrupt:pass
            finally:server.server_close()
            return
        if args.action=='hook':
            from protocol_atlas.runtime_install import hook
            result=hook(runtime,json.load(sys.stdin))
            print(json.dumps(result,ensure_ascii=False));return
        if args.action=='install':
            from protocol_atlas.runtime_install import install
            result=install(args.project,args.client)
        else:
            payload=json.load(sys.stdin) if args.input=='-' else json.loads(Path(args.input).read_text(encoding='utf-8-sig')) if args.input else {}
            result=invoke(runtime,args.action,payload)
        print(json.dumps(result,ensure_ascii=False))
    except (ValueError,OSError,SourceConflict,subprocess.TimeoutExpired) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr);raise SystemExit(1)


if __name__=='__main__':main()
