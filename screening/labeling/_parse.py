import json,re
raw=json.load(open('_trials_raw.json',encoding='utf-8'))
def clean(t):
    t=t.replace('\>','>').replace('\<','<').replace('\-','-').replace('\[','[').replace('\]',']').replace('\.','.')
    return t
def parse(nct):
    t=clean(raw[nct]['protocolSection']['eligibilityModule']['eligibilityCriteria'])
    m=re.split(r'(?im)^\s*exclusion criteria[^\n]*\n',t,maxsplit=1)
    inc=re.sub(r'(?im)^\s*inclusion criteria[^\n]*\n','',m[0]); exc=m[1] if len(m)>1 else ''
    def items(block):
        out=[]
        for line in block.splitlines():
            if not line.strip(): continue
            if re.match(r'(?i)^\s*note:',line): continue
            top=re.match(r'^(\*|-|\d+\.)\s+',line) or re.match(r'^\*\s+\d+\.',line)
            if top:
                txt=re.sub(r'^(\*\s+)?(-\s+)?(\d+\.\s*)?','',line).strip()
                out.append(txt)
            elif re.match(r'^\s+(\d+\.|\*|[a-zA-Z]\))',line) and out and not re.match(r'^\s+\d+\.\s',line) or (out and re.match(r'^\s{2,}',line) and not re.match(r'^\s+\d+\.\s',line)):
                out[-1]+=' / '+re.sub(r'^\s*(\*|\d+\.|[a-zA-Z]\))\s*','',line).strip()
            elif re.match(r'^\s+\d+\.\s',line):
                # 들여쓴 번호: 상위 항목이 번호 없는 블록(NCT06068179)인 경우 새 항목, 아니면 하위 항목
                out.append(re.sub(r'^\s*\d+\.\s*','',line).strip()) if nct=='NCT06068179' else out.__setitem__(-1,out[-1]+' / '+re.sub(r'^\s*\d+\.\s*','',line).strip())
            elif out:
                out[-1]+=' '+line.strip()
            else:
                out.append(line.strip())
        return [re.sub(r'\s+',' ',o).strip().rstrip(',') for o in out]
    return items(inc), items(exc)
if __name__=='__main__':
    for n in raw:
        i,e=parse(n); print('=====',n,len(i),len(e))
        for k,x in enumerate(i,1): print(f'  I{k}',x[:90])
        for k,x in enumerate(e,1): print(f'  E{k}',x[:90])
