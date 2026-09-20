import os, sys, json, html, re, time, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
import xml.etree.ElementTree as ET
import requests

BASE=Path(__file__).resolve().parent
STATE_FILE=BASE/"data/state.json"
TG_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","")
GEMINI_KEY=os.getenv("GEMINI_API_KEY","")
CHAT=os.getenv("TELEGRAM_CHAT_ID","@LaythPeds")
MODEL=os.getenv("GEMINI_MODEL","gemini-2.5-flash")
TG=f"https://api.telegram.org/bot{TG_TOKEN}" if TG_TOKEN else ""
UA={"User-Agent":"DrLaythPediatricsBot/2.0"}
DOMAINS=["General Pediatrics","Neonatology","Emergency","PICU","Pulmonology","Cardiology",
"Infectious Disease","Gastroenterology","Neurology","Nephrology","Endocrinology",
"Hematology/Oncology","Rheumatology","Genetics/Metabolic","Development","Adolescent Medicine"]
MAX_MSG=3900
PUBMED_TERM='(infant[Title/Abstract] OR child[Title/Abstract] OR pediatric*[Title/Abstract] OR adolescent*[Title/Abstract]) AND (guideline[Publication Type] OR practice guideline[Publication Type] OR meta-analysis[Publication Type] OR systematic review[Publication Type] OR randomized controlled trial[Publication Type] OR clinical trial[Publication Type])'

def qatar_now(): return datetime.now(timezone.utc)+timedelta(hours=3)
def daykey(): return qatar_now().strftime("%Y-%m-%d")
def load_state():
    try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception: return {"days":{},"question_history":[],"article_history":[]}
def save_state(s): STATE_FILE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding="utf-8")

def request(method,url,**kw):
    err=None
    for n in range(3):
        try:
            r=requests.request(method,url,headers=UA,timeout=(10,40),**kw); r.raise_for_status(); return r
        except requests.RequestException as e:
            err=e
            if n<2: time.sleep(2**n)
    raise err

def tg(method,payload):
    if not TG_TOKEN: raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
    x=request("POST",f"{TG}/{method}",json=payload).json()
    if not x.get("ok"): raise RuntimeError(f"Telegram error: {x}")
    return x

def send_html(text):
    while text:
        if len(text)<=MAX_MSG: part,text=text,""
        else:
            cut=text.rfind("\n\n",0,MAX_MSG)
            if cut<800: cut=MAX_MSG
            part,text=text[:cut],text[cut:].lstrip()
        tg("sendMessage",{"chat_id":CHAT,"text":part,"parse_mode":"HTML","disable_web_page_preview":True})

def pubmed_candidates(n=10):
    e=request("GET","https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
      params={"db":"pubmed","term":PUBMED_TERM,"retmode":"json","retmax":str(n),"sort":"pub date","datetype":"pdat","reldate":"21"}).json()
    ids=e.get("esearchresult",{}).get("idlist",[])
    if not ids:return []
    xml=request("GET","https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
      params={"db":"pubmed","id":",".join(ids),"retmode":"xml"}).text
    root=ET.fromstring(xml); out=[]
    for a in root.findall(".//PubmedArticle"):
        pmid=(a.findtext(".//PMID") or "").strip()
        te=a.find(".//ArticleTitle"); title=re.sub(r"\s+"," ","".join(te.itertext()) if te is not None else "").strip()
        journal=(a.findtext(".//Journal/Title") or a.findtext(".//Journal/ISOAbbreviation") or "PubMed").strip()
        pd=a.find(".//PubDate")
        date=((pd.findtext("MedlineDate") if pd is not None else None) or (pd.findtext("Year") if pd is not None else None) or "Recent").strip()
        absx=" ".join(re.sub(r"\s+"," ","".join(x.itertext())).strip() for x in a.findall(".//Abstract/AbstractText"))
        if title and absx:
            out.append({"pmid":pmid,"title":title,"journal":journal,"date":date,"abstract":absx[:6000],"url":f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})
    return out

def gemini_json(prompt):
    if not GEMINI_KEY: raise RuntimeError("GEMINI_API_KEY missing")
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_KEY}"
    body={"contents":[{"parts":[{"text":prompt}]}],
          "generationConfig":{"temperature":0.35,"responseMimeType":"application/json"}}
    raw=request("POST",url,json=body).json()
    txt=raw["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(txt)

def similarity(a,b):
    a=re.sub(r"\W+"," ",a.lower()); b=re.sub(r"\W+"," ",b.lower())
    sa=set(a.split()); sb=set(b.split())
    jac=len(sa&sb)/max(1,len(sa|sb))
    return max(jac,SequenceMatcher(None,a,b).ratio())

def choose_domains(state):
    # deterministic balanced rotation, persisted by number of successful days
    k=len(state.get("days",{}))*2
    return [DOMAINS[k%len(DOMAINS)],DOMAINS[(k+1)%len(DOMAINS)]]

def generate_questions(state,domains,evidence):
    recent=[x["question"] for x in state.get("question_history",[])[-200:]]
    ev="\n\n".join(f"{x['title']}\n{x['abstract'][:1800]}\n{x['url']}" for x in evidence[:4])
    avoid="\n".join("- "+q for q in recent[-80:])
    prompt=f"""You are a pediatric chief resident writing TWO original Arab Board/QBMS-level MCQs.
Domains, in order: {domains[0]} ; {domains[1]}.
Create exactly one question per domain. Questions must be clinically accurate, case-based, concise, resident-level, and not simple trivia.
Each has exactly four plausible options and exactly one unambiguous best answer.
Use standard current pediatric practice. Do not invent a guideline, trial, dose, statistic, or citation.
If a dose is tested, use a widely established emergency/board-standard dose and name a trustworthy guideline in reference.
Recent evidence below is optional context; do not force it into a question:
{ev}
Previously posted stems to AVOID semantically:
{avoid}
Return JSON object only:
{{"questions":[{{"domain":"...","question":"<=300 chars","options":["...","...","...","..."],"answer":0,"explanation":"2-4 sentences","distractors":["reason option A is wrong or empty if correct","...","...","..."],"pearl":"one high-yield pearl","reference":"named authoritative guideline/society or PubMed URL"}} , {{...}}]}}
Do not copy a prior stem. Do not create controversial or institution-specific answers without stating that in the explanation."""
    for _ in range(4):
        obj=gemini_json(prompt)
        qs=obj.get("questions",[])
        if len(qs)!=2: continue
        valid=True
        for i,q in enumerate(qs):
            if q.get("domain")!=domains[i] or len(q.get("options",[]))!=4 or not 0<=int(q.get("answer",-1))<4 or len(q.get("distractors",[]))!=4 or len(q.get("question",""))>300:
                valid=False; break
            if any(similarity(q["question"],old)>=0.72 for old in recent):
                valid=False; break
        if valid:return qs
        prompt+="\nYour previous attempt failed validation or was too similar. Generate substantially different cases."
    raise RuntimeError("Could not generate two unique validated questions after retries")

def summarize_evidence(state,cands):
    used=set(state.get("article_history",[]))
    fresh=[x for x in cands if x["pmid"] not in used][:4]
    if not fresh:return []
    payload="\n\n".join(f"PMID {x['pmid']}\nTITLE: {x['title']}\nJOURNAL: {x['journal']}\nDATE: {x['date']}\nABSTRACT: {x['abstract']}" for x in fresh)
    prompt=f"""Summarize these pediatric PubMed records for a pediatric resident Telegram brief.
Use ONLY facts explicitly present in each title/abstract. Never add numbers, conclusions, recommendations, or causality not present.
Return JSON: {{"items":[{{"pmid":"...","summary":"2 concise sentences","why":"one clinically useful sentence; if practice change cannot be supported, say what question the evidence informs"}}]}}
Records:
{payload}"""
    try:
        obj=gemini_json(prompt); by={x["pmid"]:x for x in obj.get("items",[])}
    except Exception:
        by={}
    out=[]
    for x in fresh:
        y=by.get(x["pmid"])
        if y and y.get("summary") and y.get("why"):
            z=dict(x); z.update(y); out.append(z)
    return out

def post_brief():
    state=load_state(); d=daykey()
    if d in state["days"]:
        # idempotency: never create a second set for the same day
        day=state["days"][d]; qs=day["questions"]; items=day.get("evidence",[])
    else:
        cands=pubmed_candidates(12)
        items=summarize_evidence(state,cands)
        domains=choose_domains(state)
        qs=generate_questions(state,domains,cands)
        day={"questions":qs,"evidence":items,"created_at":qatar_now().isoformat()}
        # persist BEFORE posting so reveal always matches even if Telegram partially fails
        state["days"][d]=day
        for q in qs:
            state["question_history"].append({"date":d,"domain":q["domain"],"question":q["question"],"hash":hashlib.sha256(q["question"].encode()).hexdigest()})
        state["article_history"] += [x["pmid"] for x in items]
        state["question_history"]=state["question_history"][-2000:]
        state["article_history"]=state["article_history"][-2000:]
        save_state(state)
    lines=["🩺 <b>Dr. Layth Pediatrics — Daily Brief</b>","<i>Evidence + Board Review | تحديثات الأطفال</i>",""]
    if items:
        for i,x in enumerate(items,1):
            lines += [f"<b>{i}. {html.escape(x['title'])}</b>",
             f"📅 {html.escape(x['date'])} | 🏛 {html.escape(x['journal'])}",
             f"🧠 {html.escape(x['summary'])}",f"💎 <b>Why it matters:</b> {html.escape(x['why'])}",
             f"🔗 <a href=\"{html.escape(x['url'])}\">PubMed / original indexed record</a>",""]
    else: lines += ["📚 No sufficiently supported new evidence summary today; filler was intentionally omitted.",""]
    lines += ["<b>Board Challenge</b>","Two new resident-level cases. Vote now; answer reveal at 22:00 Qatar."]
    send_html("\n".join(lines))
    for i,q in enumerate(qs,1):
        tg("sendMessage",{"chat_id":CHAT,"text":f"<b>Q{i} • {html.escape(q['domain'])}</b>","parse_mode":"HTML"})
        tg("sendPoll",{"chat_id":CHAT,"question":q["question"],
          "options":[{"text":f"{chr(65+j)}. {o}"} for j,o in enumerate(q["options"])],
          "is_anonymous":True,"type":"regular","allows_multiple_answers":False})

def reveal():
    state=load_state(); d=daykey()
    if d not in state.get("days",{}): raise RuntimeError("No persisted questions for today. Run brief first.")
    qs=state["days"][d]["questions"]
    lines=["✅ <b>Daily Board Challenge — Answer Reveal</b>",""]
    for i,q in enumerate(qs,1):
        a=int(q["answer"])
        lines += [f"<b>Q{i} • {html.escape(q['domain'])}</b>",f"🎯 <b>{chr(65+a)}. {html.escape(q['options'][a])}</b>",
          f"🧠 {html.escape(q['explanation'])}","❌ <b>Why the others are wrong:</b>"]
        for j in range(4):
            if j!=a: lines.append(f"• <b>{chr(65+j)}.</b> {html.escape(q['distractors'][j])}")
        lines += [f"💎 <b>Clinical pearl:</b> {html.escape(q['pearl'])}",f"📚 <b>Reference:</b> {html.escape(q['reference'])}",""]
    send_html("\n".join(lines))

def selfcheck():
    assert len(DOMAINS)==16 and len(set(DOMAINS))==16
    s={"days":{},"question_history":[],"article_history":[]}
    assert choose_domains(s)==DOMAINS[:2]
    assert MAX_MSG<4096
    print("SELF-CHECK OK")

if __name__=="__main__":
    m=(sys.argv[1] if len(sys.argv)>1 else os.getenv("MODE","brief")).lower()
    {"brief":post_brief,"reveal":reveal,"selfcheck":selfcheck}.get(m,lambda:(_ for _ in ()).throw(SystemExit("brief|reveal|selfcheck")))()
