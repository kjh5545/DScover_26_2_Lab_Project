"""팀원이 채운 시트에서 판정을 뽑아 labels.json으로 모은다."""
import re, json, glob, os
VALID = {"통과","탈락","모름","등록 후 확인"}
def norm(v):
    v=v.strip().strip('*`').strip()
    v=v.replace(' ','') 
    m={"통과":"통과","탈락":"탈락","모름":"모름","등록후확인":"등록 후 확인"}
    return m.get(v, v)
def parse_file(path):
    t=open(path,encoding='utf-8').read()
    pid=re.search(r'시트 · (S\d+)',t).group(1)
    trials=[]
    for sec in re.split(r'\n## 시험 \d+ · ',t)[1:]:
        nct=sec.split('\n',1)[0].strip()
        rows=[]
        for line in sec.splitlines():
            m=re.match(r'^\|\s*([IE]\d+)\s*\|',line)
            if not m: continue
            cells=[c.strip() for c in re.split(r'(?<![\\])[|]',line)[1:-1]]
            rows.append({"id":cells[0],"verdict_raw":cells[4],"verdict":norm(cells[4]),"evidence":cells[5],"question":cells[6] if len(cells)>6 else ""})
        fin=re.search(r'\*\*최종 판단\*\*[^\n]*\):\s*(.*)',sec)
        reason=re.search(r'\*\*최종 판단 이유[^\n]*\*\*\s*(.*)',sec)
        conf=re.search(r'\*\*헷갈렸던 점:\*\*\s*\n(.*?)(?:\n---|\Z)',sec,re.S)
        trials.append({"nct":nct,"rows":rows,"final":(fin.group(1).strip() if fin else ""),"reason":(reason.group(1).strip() if reason else ""),"confusions":(conf.group(1).strip() if conf else "")})
    tail=t.split('## 두 시험 비교')[-1] if '## 두 시험 비교' in t else (t.split('## 이 환자에게 맞는 임상시험')[-1] if '## 이 환자에게 맞는 임상시험' in t else "")
    return pid, trials, tail.strip()
out={}
for who,folder in (("팀원1","스크리닝1/팀원1"),("팀원2","스크리닝2/팀원2")):
    for f in sorted(glob.glob(folder+"/*.md")):
        pid,trials,tail=parse_file(f)
        out.setdefault(pid,{})[who]={"trials":trials,"extra":tail,"file":f}
json.dump(out,open('labels_raw.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
# 점검
for pid in sorted(out):
    for who,d in out[pid].items():
        for tr in d["trials"]:
            bad=[r for r in tr["rows"] if r["verdict"] not in VALID]
            noev=[r["id"] for r in tr["rows"] if r["verdict"] in VALID and not r["evidence"]]
            noq=[r["id"] for r in tr["rows"] if r["verdict"]=="모름" and (not r["question"] or r["question"] in ("없음","-"))]
            cnt={v:sum(r["verdict"]==v for r in tr["rows"]) for v in VALID}
            print(f'{pid} {who} {tr["nct"]} | 기준 {len(tr["rows"])} | 통과 {cnt["통과"]} 탈락 {cnt["탈락"]} 모름 {cnt["모름"]} 등록후 {cnt["등록 후 확인"]} | 최종: {tr["final"][:20]}'
                  + (f' | ⚠ 판정 이상: {[(r["id"],r["verdict_raw"]) for r in bad]}' if bad else '')
                  + (f' | 근거 없음: {noev}' if noev else '') + (f' | 질문 없음(모름): {noq}' if noq else ''))
