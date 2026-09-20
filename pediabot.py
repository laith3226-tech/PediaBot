import os
import sys
import json
import html
import re
import time
import hashlib
import random
from pathlib import Path
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
import xml.etree.ElementTree as ET

import requests


# ============================================================
# CONFIG
# ============================================================

BASE = Path(__file__).resolve().parent
STATE_FILE = BASE / "data" / "state.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@LaythPeds").strip()

TG_BASE = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    if TELEGRAM_BOT_TOKEN
    else ""
)

USER_AGENT = {
    "User-Agent": "DrLaythPediatricsBot/3.0"
}

MAX_TELEGRAM_MESSAGE = 3900

DOMAINS = [
    "General Pediatrics",
    "Neonatology",
    "Emergency",
    "PICU",
    "Pulmonology",
    "Cardiology",
    "Infectious Disease",
    "Gastroenterology",
    "Neurology",
    "Nephrology",
    "Endocrinology",
    "Hematology/Oncology",
    "Rheumatology",
    "Genetics/Metabolic",
    "Development",
    "Adolescent Medicine",
]

PUBMED_TERM = (
    "(infant[Title/Abstract] OR child[Title/Abstract] "
    "OR pediatric*[Title/Abstract] OR adolescent*[Title/Abstract]) "
    "AND (guideline[Publication Type] "
    "OR practice guideline[Publication Type] "
    "OR meta-analysis[Publication Type] "
    "OR systematic review[Publication Type] "
    "OR randomized controlled trial[Publication Type] "
    "OR clinical trial[Publication Type])"
)


# ============================================================
# TIME / STATE
# ============================================================

def qatar_now():
    return datetime.now(timezone.utc) + timedelta(hours=3)


def day_key():
    return qatar_now().strftime("%Y-%m-%d")


def empty_state():
    return {
        "days": {},
        "question_history": [],
        "article_history": [],
    }


def load_state():
    if not STATE_FILE.exists():
        return empty_state()

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))

        data.setdefault("days", {})
        data.setdefault("question_history", [])
        data.setdefault("article_history", [])

        return data

    except Exception:
        return empty_state()


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ============================================================
# HTTP
# ============================================================

def http_request(method, url, **kwargs):
    last_error = None

    for attempt in range(3):
        try:
            response = requests.request(
                method,
                url,
                headers=USER_AGENT,
                timeout=(10, 45),
                **kwargs,
            )

            response.raise_for_status()
            return response

        except requests.RequestException as exc:
            last_error = exc

            if attempt < 2:
                time.sleep(2 ** attempt)

    raise last_error


# ============================================================
# TELEGRAM
# ============================================================

def telegram(method, payload):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")

    response = http_request(
        "POST",
        f"{TG_BASE}/{method}",
        json=payload,
    )

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(
            f"Telegram API error: {data}"
        )

    return data


def send_html(text):
    remaining = text

    while remaining:
        if len(remaining) <= MAX_TELEGRAM_MESSAGE:
            part = remaining
            remaining = ""

        else:
            cut = remaining.rfind(
                "\n\n",
                0,
                MAX_TELEGRAM_MESSAGE,
            )

            if cut < 800:
                cut = MAX_TELEGRAM_MESSAGE

            part = remaining[:cut]
            remaining = remaining[cut:].lstrip()

        telegram(
            "sendMessage",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )


# ============================================================
# GEMINI
# ============================================================

def available_gemini_models():
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models?key={GEMINI_API_KEY}"
    )

    response = http_request("GET", url)
    data = response.json()

    models = []

    for model in data.get("models", []):
        methods = model.get(
            "supportedGenerationMethods",
            []
        )

        if "generateContent" not in methods:
            continue

        name = model.get("name", "")

        if name.startswith("models/"):
            name = name.split("/", 1)[1]

        if name:
            models.append(name)

    return models


def choose_gemini_model():
    models = available_gemini_models()

    if not models:
        raise RuntimeError(
            "No Gemini model with generateContent "
            "is available for this API key."
        )

    preferred_fragments = [
        "flash-lite",
        "flash",
    ]

    for fragment in preferred_fragments:
        candidates = [
            model
            for model in models
            if fragment in model.lower()
            and "preview" not in model.lower()
            and "image" not in model.lower()
            and "tts" not in model.lower()
        ]

        if candidates:
            candidates.sort(reverse=True)
            return candidates[0]

    candidates = [
        model
        for model in models
        if "image" not in model.lower()
        and "tts" not in model.lower()
    ]

    if not candidates:
        raise RuntimeError(
            "No suitable text Gemini model found."
        )

    candidates.sort(reverse=True)
    return candidates[0]


def extract_json(text):
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.I,
        )

        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

    return json.loads(text)


def gemini_json(prompt):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")

    model = choose_gemini_model()

    print(
        f"Using Gemini model: {model}",
        flush=True,
    )

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{model}:generateContent"
        f"?key={GEMINI_API_KEY}"
    )

    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.35,
            "responseMimeType": "application/json",
        },
    }

    response = http_request(
        "POST",
        url,
        json=body,
    )

    data = response.json()

    candidates = data.get("candidates", [])

    if not candidates:
        raise RuntimeError(
            f"Gemini returned no candidates: {data}"
        )

    parts = (
        candidates[0]
        .get("content", {})
        .get("parts", [])
    )

    text = "".join(
        part.get("text", "")
        for part in parts
    )

    if not text.strip():
        raise RuntimeError(
            "Gemini returned empty content."
        )

    return extract_json(text)


# ============================================================
# PUBMED
# ============================================================

def pubmed_candidates(limit=12):
    search_response = http_request(
        "GET",
        (
            "https://eutils.ncbi.nlm.nih.gov/"
            "entrez/eutils/esearch.fcgi"
        ),
        params={
            "db": "pubmed",
            "term": PUBMED_TERM,
            "retmode": "json",
            "retmax": str(limit),
            "sort": "pub date",
            "datetype": "pdat",
            "reldate": "21",
        },
    )

    search_data = search_response.json()

    ids = (
        search_data
        .get("esearchresult", {})
        .get("idlist", [])
    )

    if not ids:
        return []

    fetch_response = http_request(
        "GET",
        (
            "https://eutils.ncbi.nlm.nih.gov/"
            "entrez/eutils/efetch.fcgi"
        ),
        params={
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "xml",
        },
    )

    root = ET.fromstring(fetch_response.text)

    results = []

    for article in root.findall(".//PubmedArticle"):
        pmid = (
            article.findtext(".//PMID")
            or ""
        ).strip()

        title_node = article.find(
            ".//ArticleTitle"
        )

        title = ""

        if title_node is not None:
            title = " ".join(
                "".join(
                    title_node.itertext()
                ).split()
            )

        journal = (
            article.findtext(
                ".//Journal/Title"
            )
            or article.findtext(
                ".//Journal/ISOAbbreviation"
            )
            or "PubMed"
        ).strip()

        pub_date = article.find(
            ".//PubDate"
        )

        date = "Recent"

        if pub_date is not None:
            medline_date = (
                pub_date.findtext(
                    "MedlineDate"
                )
                or ""
            ).strip()

            year = (
                pub_date.findtext("Year")
                or ""
            ).strip()

            month = (
                pub_date.findtext("Month")
                or ""
            ).strip()

            if medline_date:
                date = medline_date

            elif year and month:
                date = f"{year} {month}"

            elif year:
                date = year

        abstract_parts = []

        for node in article.findall(
            ".//Abstract/AbstractText"
        ):
            text = " ".join(
                "".join(
                    node.itertext()
                ).split()
            )

            if text:
                abstract_parts.append(text)

        abstract = " ".join(
            abstract_parts
        )

        if title and abstract and pmid:
            results.append(
                {
                    "pmid": pmid,
                    "title": title,
                    "journal": journal,
                    "date": date,
                    "abstract": abstract[:7000],
                    "url": (
                        "https://pubmed.ncbi.nlm.nih.gov/"
                        f"{pmid}/"
                    ),
                }
            )

    return results


# ============================================================
# DUPLICATE DETECTION
# ============================================================

def normalized_text(text):
    return re.sub(
        r"\W+",
        " ",
        text.lower(),
    ).strip()


def similarity(a, b):
    a = normalized_text(a)
    b = normalized_text(b)

    set_a = set(a.split())
    set_b = set(b.split())

    jaccard = (
        len(set_a & set_b)
        / max(
            1,
            len(set_a | set_b),
        )
    )

    sequence = SequenceMatcher(
        None,
        a,
        b,
    ).ratio()

    return max(
        jaccard,
        sequence,
    )


# ============================================================
# DOMAIN ROTATION
# ============================================================

def choose_domains(state):
    history = state.get(
        "question_history",
        [],
    )

    counts = {
        domain: 0
        for domain in DOMAINS
    }

    for item in history:
        domain = item.get("domain")

        if domain in counts:
            counts[domain] += 1

    shuffled = DOMAINS[:]

    random.Random(
        day_key()
    ).shuffle(shuffled)

    ordered = sorted(
        shuffled,
        key=lambda domain: counts[domain],
    )

    return ordered[:2]


# ============================================================
# QUESTION GENERATION
# ============================================================

def validate_question(question, domain, history):
    if question.get("domain") != domain:
        return False

    stem = question.get(
        "question",
        "",
    ).strip()

    if not stem:
        return False

    if len(stem) > 300:
        return False

    options = question.get(
        "options",
        [],
    )

    if len(options) != 4:
        return False

    if len(set(options)) != 4:
        return False

    try:
        answer = int(
            question.get(
                "answer",
                -1,
            )
        )

    except Exception:
        return False

    if answer not in range(4):
        return False

    distractors = question.get(
        "distractors",
        [],
    )

    if len(distractors) != 4:
        return False

    required = [
        "explanation",
        "pearl",
        "reference",
    ]

    for field in required:
        if not str(
            question.get(
                field,
                "",
            )
        ).strip():
            return False

    for previous in history:
        old_stem = previous.get(
            "question",
            "",
        )

        if old_stem and similarity(
            stem,
            old_stem,
        ) >= 0.70:
            return False

    return True


def generate_questions(
    state,
    domains,
    evidence,
):
    history = state.get(
        "question_history",
        [],
    )[-500:]

    recent_stems = "\n".join(
        f"- {item.get('question', '')}"
        for item in history[-120:]
    )

    evidence_text = "\n\n".join(
        (
            f"TITLE: {item['title']}\n"
            f"ABSTRACT: {item['abstract'][:1800]}\n"
            f"URL: {item['url']}"
        )
        for item in evidence[:5]
    )

    prompt = f"""
You are the pediatric chief resident and board-review editor
for Dr. Layth Pediatrics.

Generate EXACTLY TWO original pediatric MCQs.

Question 1 domain:
{domains[0]}

Question 2 domain:
{domains[1]}

Target:
Pediatric resident / Arab Board / QBMS level.

Requirements:
- clinically realistic case-based questions
- concise stem
- four plausible options
- exactly one best answer
- mix diagnosis, next step, investigation, management,
  emergency care, interpretation, and medication dosing
  when appropriate
- avoid trivia
- avoid obscure controversies
- avoid institution-specific answers
- do not invent doses, guidelines, trials, statistics,
  or references
- reference an authoritative pediatric guideline,
  professional society, textbook-standard guideline,
  or supplied PubMed source
- questions must be substantially different from all
  previous stems
- explanation should teach clinical reasoning
- explain why EACH incorrect option is wrong
- include one high-yield clinical pearl

Recent PubMed evidence is optional context.
Do not force it into the MCQs:

{evidence_text}

Previously posted questions that MUST NOT be repeated
or closely paraphrased:

{recent_stems}

Return JSON only in this exact structure:

{{
  "questions": [
    {{
      "domain": "{domains[0]}",
      "question": "case stem <=300 characters",
      "options": [
        "option A",
        "option B",
        "option C",
        "option D"
      ],
      "answer": 0,
      "explanation": "2-4 sentence explanation",
      "distractors": [
        "",
        "why B is wrong",
        "why C is wrong",
        "why D is wrong"
      ],
      "pearl": "one concise clinical pearl",
      "reference": "authoritative reference"
    }},
    {{
      "domain": "{domains[1]}",
      "question": "case stem <=300 characters",
      "options": [
        "option A",
        "option B",
        "option C",
        "option D"
      ],
      "answer": 0,
      "explanation": "2-4 sentence explanation",
      "distractors": [
        "",
        "why B is wrong",
        "why C is wrong",
        "why D is wrong"
      ],
      "pearl": "one concise clinical pearl",
      "reference": "authoritative reference"
    }}
  ]
}}
"""

    for attempt in range(4):
        result = gemini_json(prompt)

        questions = result.get(
            "questions",
            [],
        )

        if len(questions) != 2:
            prompt += (
                "\nPrevious output failed validation. "
                "Return exactly two questions."
            )
            continue

        valid = True

        for index, question in enumerate(
            questions
        ):
            if not validate_question(
                question,
                domains[index],
                history,
            ):
                valid = False
                break

        if valid:
            if similarity(
                questions[0]["question"],
                questions[1]["question"],
            ) >= 0.65:
                valid = False

        if valid:
            return questions

        prompt += (
            "\nYour previous attempt was invalid or too "
            "similar to a previous question. Generate "
            "two substantially different cases."
        )

    raise RuntimeError(
        "Could not generate two unique validated "
        "questions after four attempts."
    )


# ============================================================
# EVIDENCE SUMMARY
# ============================================================

def summarize_evidence(
    state,
    candidates,
):
    used = set(
        state.get(
            "article_history",
            [],
        )
    )

    fresh = [
        item
        for item in candidates
        if item["pmid"] not in used
    ][:4]

    if not fresh:
        return []

    source_text = "\n\n".join(
        (
            f"PMID: {item['pmid']}\n"
            f"TITLE: {item['title']}\n"
            f"JOURNAL: {item['journal']}\n"
            f"DATE: {item['date']}\n"
            f"ABSTRACT: {item['abstract']}"
        )
        for item in fresh
    )

    prompt = f"""
You are editing a concise pediatric evidence brief
for pediatric residents.

Summarize ONLY the information explicitly contained
in the supplied PubMed titles and abstracts.

Rules:
- never invent a number
- never invent a recommendation
- never invent causality
- never call something practice-changing unless the
  supplied abstract supports that conclusion
- do not exaggerate
- preserve uncertainty
- each summary should be 2 concise sentences
- "why" should be one clinically useful sentence
- if clinical implications are uncertain, explicitly say so

Return JSON only:

{{
  "items": [
    {{
      "pmid": "PMID",
      "summary": "2 sentences",
      "why": "1 sentence"
    }}
  ]
}}

Records:

{source_text}
"""

    try:
        generated = gemini_json(
            prompt
        )

    except Exception as exc:
        print(
            f"Evidence summarization skipped: {exc}",
            flush=True,
        )
        return []

    generated_by_pmid = {
        str(item.get("pmid")): item
        for item in generated.get(
            "items",
            [],
        )
    }

    output = []

    for article in fresh:
        summary = generated_by_pmid.get(
            article["pmid"]
        )

        if not summary:
            continue

        if not summary.get(
            "summary"
        ) or not summary.get(
            "why"
        ):
            continue

        item = dict(article)

        item["summary"] = summary[
            "summary"
        ]

        item["why"] = summary[
            "why"
        ]

        output.append(item)

    return output


# ============================================================
# DAILY BRIEF
# ============================================================

def post_brief():
    state = load_state()
    today = day_key()

    if today in state["days"]:
        day = state["days"][today]

        questions = day["questions"]
        evidence_items = day.get(
            "evidence",
            [],
        )

        print(
            "Today's questions already exist. "
            "Reusing persisted set.",
            flush=True,
        )

    else:
        candidates = pubmed_candidates(
            12
        )

        evidence_items = (
            summarize_evidence(
                state,
                candidates,
            )
        )

        domains = choose_domains(
            state
        )

        questions = generate_questions(
            state,
            domains,
            candidates,
        )

        state["days"][today] = {
            "questions": questions,
            "evidence": evidence_items,
            "created_at": (
                qatar_now().isoformat()
            ),
        }

        for question in questions:
            stem = question[
                "question"
            ]

            state[
                "question_history"
            ].append(
                {
                    "date": today,
                    "domain": question[
                        "domain"
                    ],
                    "question": stem,
                    "hash": hashlib.sha256(
                        stem.encode(
                            "utf-8"
                        )
                    ).hexdigest(),
                }
            )

        state[
            "article_history"
        ].extend(
            item["pmid"]
            for item in evidence_items
        )

        state[
            "question_history"
        ] = state[
            "question_history"
        ][-2000:]

        state[
            "article_history"
        ] = state[
            "article_history"
        ][-2000:]

        save_state(state)

    lines = [
        "🩺 <b>Dr. Layth Pediatrics — Daily Brief</b>",
        "<i>Evidence + Board Review | تحديثات الأطفال</i>",
        "",
    ]

    if evidence_items:
        for index, item in enumerate(
            evidence_items,
            start=1,
        ):
            lines.extend(
                [
                    (
                        f"<b>{index}. "
                        f"{html.escape(item['title'])}"
                        "</b>"
                    ),
                    (
                        f"📅 {html.escape(item['date'])}"
                        f" | 🏛 "
                        f"{html.escape(item['journal'])}"
                    ),
                    (
                        "🧠 "
                        + html.escape(
                            item["summary"]
                        )
                    ),
                    (
                        "💎 <b>Why it matters:</b> "
                        + html.escape(
                            item["why"]
                        )
                    ),
                    (
                        "🔗 "
                        f'<a href="{html.escape(item["url"])}">'
                        "PubMed source"
                        "</a>"
                    ),
                    "",
                ]
            )

    else:
        lines.extend(
            [
                (
                    "📚 No sufficiently supported new "
                    "pediatric evidence summary was "
                    "available today; filler was omitted."
                ),
                "",
            ]
        )

    lines.extend(
        [
            "<b>Board Challenge</b>",
            (
                "Two new resident-level cases. "
                "Vote now; answers at 22:00 Qatar."
            ),
        ]
    )

    send_html(
        "\n".join(lines)
    )

    for index, question in enumerate(
        questions,
        start=1,
    ):
        telegram(
            "sendMessage",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": (
                    f"<b>Q{index} • "
                    f"{html.escape(question['domain'])}"
                    "</b>"
                ),
                "parse_mode": "HTML",
            },
        )

        poll_options = [
            {
                "text": (
                    f"{chr(65 + option_index)}. "
                    f"{option}"
                )
            }
            for option_index, option
            in enumerate(
                question["options"]
            )
        ]

        telegram(
            "sendPoll",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "question": question[
                    "question"
                ],
                "options": poll_options,
                "is_anonymous": True,
                "type": "regular",
                "allows_multiple_answers": False,
            },
        )


# ============================================================
# ANSWER REVEAL
# ============================================================

def reveal():
    state = load_state()
    today = day_key()

    if today not in state.get(
        "days",
        {},
    ):
        raise RuntimeError(
            "No persisted questions found for today. "
            "The brief must run successfully first."
        )

    questions = state[
        "days"
    ][today]["questions"]

    lines = [
        "✅ <b>Daily Board Challenge — Answer Reveal</b>",
        "",
    ]

    for index, question in enumerate(
        questions,
        start=1,
    ):
        answer = int(
            question["answer"]
        )

        lines.extend(
            [
                (
                    f"<b>Q{index} • "
                    f"{html.escape(question['domain'])}"
                    "</b>"
                ),
                (
                    f"🎯 <b>{chr(65 + answer)}. "
                    f"{html.escape(question['options'][answer])}"
                    "</b>"
                ),
                (
                    "🧠 "
                    + html.escape(
                        question[
                            "explanation"
                        ]
                    )
                ),
                (
                    "❌ <b>Why the other options "
                    "are wrong:</b>"
                ),
            ]
        )

        distractors = question[
            "distractors"
        ]

        for option_index in range(
            4
        ):
            if option_index == answer:
                continue

            reason = (
                distractors[
                    option_index
                ]
                or "Not the best answer in this case."
            )

            lines.append(
                (
                    f"• <b>{chr(65 + option_index)}.</b> "
                    f"{html.escape(reason)}"
                )
            )

        lines.extend(
            [
                (
                    "💎 <b>Clinical pearl:</b> "
                    + html.escape(
                        question[
                            "pearl"
                        ]
                    )
                ),
                (
                    "📚 <b>Reference:</b> "
                    + html.escape(
                        question[
                            "reference"
                        ]
                    )
                ),
                "",
            ]
        )

    send_html(
        "\n".join(lines)
    )


# ============================================================
# SELF CHECK
# ============================================================

def selfcheck():
    assert (
        len(DOMAINS) == 16
    )

    assert (
        len(set(DOMAINS)) == 16
    )

    assert (
        MAX_TELEGRAM_MESSAGE
        < 4096
    )

    state = empty_state()

    domains = choose_domains(
        state
    )

    assert (
        len(domains) == 2
    )

    assert (
        domains[0]
        != domains[1]
    )

    print(
        "SELF-CHECK OK",
        flush=True,
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    mode = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.getenv(
            "MODE",
            "brief",
        )
    ).lower()

    if mode == "brief":
        post_brief()

    elif mode == "reveal":
        reveal()

    elif mode == "selfcheck":
        selfcheck()

    else:
        raise SystemExit(
            "Mode must be: brief | reveal | selfcheck"
        )
