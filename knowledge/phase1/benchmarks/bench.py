import json, time, urllib.request
SYS=('Eres el Planner de Forsis. Traduce la pregunta a UNA capability. '
 'Capabilities: buscar_guia(folio), buscar_operador(nombre), buscar_analitica(metric,period). '
 'Responde EXCLUSIVAMENTE con JSON, sin markdown, sin texto: '
 '{"capability":"<nombre>","parameters":{...}}. Si ninguna aplica: {"capability":null,"parameters":{}}')
QS=["dame la guia %d","quien es el operador %d","cuantos viajes hubo en el mes %d",
    "estatus de la guia folio %d","saldo del operador numero %d","hola, que tal %d",
    "buscame la guia %d por favor","analitica de viajes periodo %d","operador con id %d","guia %d estatus"]
rows=[]
for i,q in enumerate(QS):
    body=json.dumps({"model":"Forsis","stream":False,"temperature":0,
      "response_format":{"type":"json_object"},
      "messages":[{"role":"system","content":SYS},{"role":"user","content":q%(90000+i*137)}]}).encode()
    r=urllib.request.Request("http://127.0.0.1:20130/v1/chat/completions",data=body,
      headers={"Content-Type":"application/json"})
    t=time.time()
    try:
        d=json.loads(urllib.request.urlopen(r,timeout=180).read())
        el=time.time()-t
        c=d["choices"][0]["message"]["content"]
        try: json.loads(c); ok=True
        except Exception: ok=False
        rows.append({"i":i,"model":d.get("model"),"lat":round(el,2),"json_ok":ok,"snip":c[:70]})
    except Exception as e:
        rows.append({"i":i,"model":"ERROR","lat":round(time.time()-t,2),"json_ok":False,"snip":str(e)[:70]})
for r in rows: print(r)
lats=[r["lat"] for r in rows]; oks=sum(r["json_ok"] for r in rows)
lats_s=sorted(lats)
print("\n--- RESUMEN ---")
print("n=%d json_ok=%d (%.0f%%)"%(len(rows),oks,100*oks/len(rows)))
print("lat min=%.2f p50=%.2f p95=%.2f max=%.2f"%(lats_s[0],lats_s[len(lats_s)//2],lats_s[int(len(lats_s)*0.95)-1],lats_s[-1]))
from collections import Counter
print("modelos:",Counter(r["model"] for r in rows))
json.dump(rows,open("bench_results.json","w"),indent=1)
