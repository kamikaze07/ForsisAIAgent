import json,time,urllib.request,re
SYS=('Eres el Planner de Forsis. Capabilities: buscar_guia(folio), buscar_operador(nombre), '
 'buscar_analitica(metric,period). Responde EXCLUSIVAMENTE con JSON, sin markdown: '
 '{"capability":"<nombre>","parameters":{...}}')
QS=["dame la guia %d","quien es el operador %d","viajes del mes %d","estatus guia %d","saldo operador %d"]
def call(model,q,rf=True):
    p={"model":model,"stream":False,"temperature":0,
       "messages":[{"role":"system","content":SYS},{"role":"user","content":q}]}
    if rf: p["response_format"]={"type":"json_object"}
    r=urllib.request.Request("http://127.0.0.1:20130/v1/chat/completions",
      data=json.dumps(p).encode(),headers={"Content-Type":"application/json"})
    t=time.time(); d=json.loads(urllib.request.urlopen(r,timeout=120).read())
    return d.get("model"),d["choices"][0]["message"]["content"],round(time.time()-t,2)
FENCE=re.compile(r"```(?:json)?\s*(.*?)\s*```",re.S)
def salvage(c):
    m=FENCE.search(c)
    if m: c=m.group(1)
    i,j=c.find("{"),c.rfind("}")
    if i>=0 and j>i: c=c[i:j+1]
    try: json.loads(c); return True
    except Exception: return False
for model in ["Forsis","claude-opus-5"]:
    raw=sal=0; lats=[]
    for i,q in enumerate(QS):
        try:
            m,c,l=call(model,q%(70000+i*311)); lats.append(l)
            ok=False
            try: json.loads(c); ok=True
            except Exception: pass
            raw+=ok; sal+=salvage(c)
            print(f"  [{model}] -> {m} lat={l} raw={ok} salvage={salvage(c)} {c[:60]!r}")
        except Exception as e: print("  ERR",model,str(e)[:80])
    n=len(QS)
    print(f"== {model}: raw_json={raw}/{n} con_salvage={sal}/{n} lat_max={max(lats) if lats else 0}\n")
