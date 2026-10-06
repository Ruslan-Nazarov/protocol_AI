"""Offline structural checks for linked translations. No model or network calls."""
import sys,re,json,collections
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from protocol_atlas.translations import TranslationStore,document_paths,preserve_identifiers,write_json
ROOT=Path(__file__).resolve().parents[1];store=TranslationStore(ROOT)
def numbers(text):
    text=re.sub(r'(\d)[ \u00a0\u202f](?=\d{3}\b)',r'\1',text)
    text=re.sub(r'(\d+)\s+(?:тысяч|тыс\.?)',lambda m:str(int(m[1])*1000),text)
    text=re.sub(r'(?<!\d)([1-9]\d{0,2})(?:,\d{3})+(?!\d)',lambda m:m[0].replace(',',''),text)
    text=re.sub(r'(\d+)\s*[kK]\b',lambda m:str(int(m[1])*1000),text)
    return collections.Counter(x.replace(',','.') for x in re.findall(r'(?<!\w)\d+(?:[.,]\d+)*',text))
issues=[];pending={};repaired=0
for path in document_paths(ROOT):
    doc=store.read(path)
    if doc['pending']:pending[path]=doc['pending']
    changed=False
    for u in doc['units']:
        if u['status']!='current':continue
        source=u['source'];target=u['translation']
        corrected=preserve_identifiers(source,target)
        if '--repair-identifiers' in sys.argv and corrected!=target:
            u['translation']=target=corrected;changed=True;repaired+=1
        ids=set(re.findall(r'(?<!\w)[А-ЯЁ]\.\d+(?:\.\d+)*[а-я]?',source))
        for identifier in ids:
            if identifier not in target:issues.append([path,u['start_line'],'rule_id',identifier])
        for link in re.findall(r'https?://[^\s)<>]+',source):
            link=link.rstrip('.,;')
            if link not in target:issues.append([path,u['start_line'],'url',link])
        for literal in re.findall(r'`([^`\n]+)`',source):
            if not re.search('[А-Яа-яЁё]',literal) and literal not in target:issues.append([path,u['start_line'],'literal',literal])
        if numbers(source)!=numbers(target):issues.append([path,u['start_line'],'numbers',dict(numbers(source)),dict(numbers(target))])
        if len(re.findall(r'^```',source,re.M))!=len(re.findall(r'^```',target,re.M)):issues.append([path,u['start_line'],'code_fences'])
        if u['kind']=='table':
            a=[row.count('|') for row in source.splitlines() if row.strip()]
            b=[row.count('|') for row in target.splitlines() if row.strip()]
            if a!=b:issues.append([path,u['start_line'],'table_shape',a,b])
    if changed:write_json(store.target(path)[1],{'schema_version':1,'path':path,'units':doc['units'],'archived':doc['archived']})
ui_path=ROOT/'locales/en/ui.json'
if '--repair-identifiers' in sys.argv and ui_path.is_file():
    ui=json.loads(ui_path.read_text(encoding='utf-8'));changed=False
    for e in ui['entries']:
        corrected=preserve_identifiers(e['source'],e['translation'])
        if corrected!=e['translation']:e['translation']=corrected;changed=True
    if changed:write_json(ui_path,ui)
print(json.dumps({'documents':len(document_paths(ROOT)),'pending_documents':pending,'ui_pending':store.ui()['pending'],'structural_issues':issues,'repaired_units':repaired},ensure_ascii=False,indent=2))
sys.exit(1 if issues or pending or store.ui()['pending'] else 0)
