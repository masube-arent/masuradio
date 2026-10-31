import json
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'episodes'
items=[]
for f in sorted(p.glob('????-??-??.json'),reverse=True):
 try:
  d=json.loads(f.read_text(encoding='utf-8'))
  if (p/(f.stem+'.mp3')).exists():items.append({k:d[k] for k in ('date','title','duration_seconds','audio')})
 except (KeyError,ValueError):pass
(p/'index.json').write_text(json.dumps(items[:7],ensure_ascii=False,indent=2),encoding='utf-8')
