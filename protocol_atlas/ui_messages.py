"""Read UI literals without executing code; comments and regexes are not messages."""
import json,re,ast
from pathlib import Path
from html.parser import HTMLParser
RU=re.compile('[А-Яа-яЁё]')
class Messages(HTMLParser):
    def __init__(self):super().__init__();self.values=[]
    def handle_data(self,value):self.values.append(value)
    def handle_starttag(self,tag,attrs):
        self.values.extend(value for key,value in attrs if value and key in ('title','placeholder','aria-label'))
def js_literals(text):
    values=[];n=len(text)
    def scan(i,stop=False):
        depth=0
        while i<n:
            c=text[i]
            if c=='}' and stop and depth==0:return i+1
            if text.startswith('//',i):
                end=text.find('\n',i);i=n if end<0 else end+1;continue
            if text.startswith('/*',i):
                end=text.find('*/',i+2);i=n if end<0 else end+2;continue
            if c=='/':
                previous=text[:i].rstrip()[-1:]
                if previous in ('=','(', '[', ',', ':','!'):
                    i+=1;bracket=False
                    while i<n:
                        if text[i]=='\\':i+=2;continue
                        if text[i]=='[':bracket=True
                        if text[i]==']':bracket=False
                        if text[i]=='/' and not bracket:i+=1;break
                        i+=1
                    continue
            if c in ('\"',"'",'`'):
                quote=c;i+=1;parts=[]
                while i<n:
                    if text[i]=='\\' and i+1<n:
                        parts.append({'n':'\n','r':'\r','t':'\t'}.get(text[i+1],text[i+1]));i+=2;continue
                    if quote=='`' and text.startswith('${',i):
                        values.append(''.join(parts));parts=[];i=scan(i+2,True);continue
                    if text[i]==quote:i+=1;break
                    parts.append(text[i]);i+=1
                values.append(''.join(parts));continue
            if c=='{':depth+=1
            if c=='}':depth-=1
            i+=1
        return i
    scan(0);return values

def ui_sources(root):
    root=Path(root);sources=set()
    def add(value):
        value=value.strip()
        if RU.search(value) and len(value)<5000:sources.add(value)
    for path in (root/'protocol_atlas/web').glob('*'):
        if path.suffix not in ('.js','.html') or path.name=='i18n.js':continue
        text=path.read_text(encoding='utf-8')
        literals=[text] if path.suffix=='.html' else js_literals(text)
        for value in literals:
            if not RU.search(value):continue
            if re.match(r'^[\">]',value):value=('<x data-tail=\"' if value.startswith('\"') else '<x')+value
            if re.search(r'<[А-Яа-яЁё]',value):add(value);continue
            if '<' in value:
                parser=Messages();parser.feed(value)
                for part in parser.values:add(part)
            else:add(value)
    for path in list((root/'protocol_atlas').glob('*.py'))+[root/'check_answer.py']:
        if not path.is_file():continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node,ast.Constant) and isinstance(node.value,str) and RU.search(node.value) and len(node.value)<5000 and '\0' not in node.value:add(node.value)
    def collect(value):
        if isinstance(value,str):add(value)
        elif isinstance(value,list):
            for item in value:collect(item)
        elif isinstance(value,dict):
            for item in value.values():collect(item)
    for name in ('atlas/annotations.json','locales/ui-extra-sources.json'):
        path=root/name
        if path.is_file():collect(json.loads(path.read_text(encoding='utf-8')))
    return sorted(sources)
