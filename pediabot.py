import os, html, random, requests, feedparser

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@LaythPeds")

FEEDS = [
    ("WHO", "https://www.who.int/rss-feeds/news-english.xml"),
    ("AAP Pediatrics", "https://publications.aap.org/rss/site_1000000/1000000.xml"),
]

MCQS = [
    {
        "q": "A child with anaphylaxis requires first-line treatment. What is the preferred medication and route?",
        "options": ["IM epinephrine", "IV hydrocortisone", "Nebulized salbutamol", "IV antihistamine"],
        "answer": "IM epinephrine",
        "explanation": "IM epinephrine into the anterolateral thigh is first-line treatment for anaphylaxis."
    },
    {
        "q": "Which presentation is most typical of viral croup?",
        "options": ["Barking cough with inspiratory stridor", "Drooling with tripod position", "Focal crackles", "Isolated expiratory wheeze"],
        "answer": "Barking cough with inspiratory stridor",
        "explanation": "Croup classically causes a barking cough, hoarseness, and inspiratory stridor."
    },
]

def get_news():
    items = []
    for source, url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if title and link:
                    items.append((source, title, link))
        except Exception as exc:
            print(f"Feed error {source}: {exc}")
    return items[:4]

def build_message():
    lines = [
        "🩺 <b>Dr. Layth Pediatrics — Daily Brief</b>",
        "",
        "🌍 <b>Pediatric updates | تحديثات طب الأطفال</b>",
    ]
    news = get_news()
    if news:
        for source, title, link in news:
            lines.append(
                f'• <b>{html.escape(title)}</b>\n'
                f'  {html.escape(source)} — <a href="{html.escape(link)}">Source</a>'
            )
    else:
        lines.append("• No feed items retrieved today. The bot will retry on the next run.")

    q = random.choice(MCQS)
    opts = "\n".join(f"{chr(65+i)}. {html.escape(x)}" for i, x in enumerate(q["options"]))
    lines += [
        "",
        "🧠 <b>Clinical MCQ</b>",
        html.escape(q["q"]),
        opts,
        "",
        f"✅ <b>Answer:</b> {html.escape(q['answer'])}",
        f"💡 {html.escape(q['explanation'])}",
        "",
        "<i>Educational content only; not individualized medical advice.</i>",
    ]
    return "\n".join(lines)

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    response = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=30)
    response.raise_for_status()
    print("Telegram post sent successfully.")

if __name__ == "__main__":
    send_message(build_message())
