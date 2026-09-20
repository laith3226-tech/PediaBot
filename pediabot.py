import os, html, requests, feedparser, hashlib, random
from datetime import datetime, timezone

TOKEN=os.environ["TELEGRAM_BOT_TOKEN"]
CHAT=os.getenv("TELEGRAM_CHAT_ID","@LaythPeds")
API=f"https://api.telegram.org/bot{TOKEN}"

FEEDS=[
 ("AAP Pediatrics","https://publications.aap.org/rss/site_1000000/1000000.xml"),
 ("WHO","https://www.who.int/rss-feeds/news-english.xml"),
]

QUESTIONS=[
 {
  "q":"A 4-year-old presents with barking cough, hoarseness and stridor at rest. What is the most appropriate initial pharmacologic treatment?",
  "options":["Nebulized salbutamol only","Dexamethasone plus nebulized epinephrine","IV ceftriaxone","Nebulized hypertonic saline"],
  "answer":1,
  "explanation":"Stridor at rest indicates at least moderate croup. Give corticosteroid; nebulized epinephrine is indicated for moderate–severe symptoms.",
  "pearl":"Observe after nebulized epinephrine because its clinical effect is transient."
 },
 {
  "q":"An 8-year-old with asthma has symptoms 4 days/week and wakes with asthma twice/month. Which feature is most useful when selecting long-term therapy?",
  "options":["Worst impairment/risk domain","Age alone","Presence of fever","Chest X-ray appearance"],
  "answer":0,
  "explanation":"Asthma control/severity assessment integrates impairment and future risk; treatment is based on the more severe relevant domain.",
  "pearl":"Always assess technique, adherence, triggers and comorbidities before stepping up."
 },
 {
  "q":"A child with anaphylaxis has wheeze, urticaria and hypotension. What is the first-line treatment?",
  "options":["IM epinephrine","IV hydrocortisone","Nebulized salbutamol","Oral antihistamine"],
  "answer":0,
  "explanation":"IM epinephrine in the anterolateral thigh is first-line treatment; adjuncts must not delay it.",
  "pearl":"Repeat IM epinephrine if clinically required while supporting airway, breathing and circulation."
 },
 {
  "q":"A 2-month-old infant has poor feeding, diaphoresis and tachypnea with a new murmur. Which diagnosis should be prioritized?",
  "options":["Heart failure from congenital heart disease","Simple viral rhinitis","Physiologic reflux","Teething"],
  "answer":0,
  "explanation":"Feeding intolerance, diaphoresis and tachypnea in early infancy are classic clues to heart failure, often as pulmonary vascular resistance falls.",
  "pearl":"In infants, feeding is exercise—sweating and respiratory distress during feeds are important cardiac clues."
 }
]

def tg(method,payload):
    r=requests.post(f"{API}/{method}",json=payload,timeout=30)
    r.raise_for_status()
    return r.json()

def news():
    out=[]; seen=set()
    for source,url in FEEDS:
        try:
            f=feedparser.parse(url)
            for e in f.entries[:8]:
                title=e.get("title","").strip(); link=e.get("link","").strip()
                key=title.lower()
                if title and link and key not in seen:
                    seen.add(key); out.append((source,title,link))
        except Exception as e: print(source,e)
    return out[:4]

def daily_questions():
    day=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rnd=random.Random(int(hashlib.sha256(day.encode()).hexdigest()[:12],16))
    return rnd.sample(QUESTIONS,2)

def post_brief():
    items=news()
    lines=["🩺 <b>Dr. Layth Pediatrics | Daily Brief</b>",
           "🌍 <b>Selected pediatric & child-health updates</b>",""]
    if items:
        for i,(source,title,link) in enumerate(items,1):
            lines += [f"<b>{i}. {html.escape(title)}</b>",
                      f"المصدر: {html.escape(source)} | <a href=\"{html.escape(link)}\">Read source</a>",""]
    else:
        lines += ["No reliable feed items were retrieved today.",""]
    lines += ["🧠 <b>Board Challenge</b>",
              "Two interactive questions are posted below. Vote now — answers and explanations will be revealed at 22:00 Qatar time.",
              "","<i>Educational content only; not individualized medical advice.</i>"]
    tg("sendMessage",{"chat_id":CHAT,"text":"\n".join(lines),"parse_mode":"HTML","disable_web_page_preview":True})
    for idx,q in enumerate(daily_questions(),1):
        tg("sendPoll",{
            "chat_id":CHAT,
            "question":f"Q{idx}. {q['q']}",
            "options":q["options"],
            "is_anonymous":True,
            "type":"regular",
            "allows_multiple_answers":False
        })

def reveal():
    lines=["✅ <b>Board Challenge — Answer Reveal</b>",""]
    for idx,q in enumerate(daily_questions(),1):
        ans=q["options"][q["answer"]]
        lines += [f"<b>Q{idx}: {html.escape(ans)}</b>",
                  f"📌 {html.escape(q['explanation'])}",
                  f"💎 <b>Clinical pearl:</b> {html.escape(q['pearl'])}",""]
    lines += ["See you tomorrow for the next challenge. 👨‍⚕️📚"]
    tg("sendMessage",{"chat_id":CHAT,"text":"\n".join(lines),"parse_mode":"HTML","disable_web_page_preview":True})

if __name__=="__main__":
    mode=os.getenv("MODE","brief")
    if mode=="reveal": reveal()
    else: post_brief()
