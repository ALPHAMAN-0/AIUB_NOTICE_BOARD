from __future__ import annotations

import json

import requests

CATEGORIES: list[str] = [
    "Exam",
    "Registration / Add-Drop",
    "Admission",
    "Result",
    "Fee / Scholarship",
    "Holiday",
    "Event",
    "General",
]

CATEGORY_EMOJI: dict[str, str] = {
    "Exam": "📝",
    "Registration / Add-Drop": "🗓️",
    "Admission": "🎓",
    "Result": "📊",
    "Fee / Scholarship": "💳",
    "Holiday": "🏖️",
    "Event": "🎉",
    "General": "📢",
}

_KEYWORDS: dict[str, list[str]] = {
    "Exam": ["exam", "midterm", "mid-term", "final term", "final-term",
             "seat plan", "retake", "makeup", "make-up", "quiz", "schedule of"],
    "Registration / Add-Drop": ["adding dropping", "add drop", "add/drop",
             "registration", "register", "advising", "course offer", "enrollment step"],
    "Admission": ["admission", "admit", "orientation", "freshman", "freshmen"],
    "Result": ["result", "grade", "gpa", "cgpa", "transcript", "published"],
    "Fee / Scholarship": ["fee", "payment", "tuition", "installment",
             "waiver", "scholarship", "stipend"],
    "Holiday": ["holiday", "closed", "closure", "vacation", "off day"],
    "Event": ["event", "seminar", "workshop", "fest", "competition",
             "ceremony", "convocation", "world cup", "webinar", "fair",
             "exchange program", "survey"],
}

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"

_SYSTEM_PROMPT = (
    "You classify university notice titles from American International "
    "University-Bangladesh (AIUB). Given a single notice title, choose the ONE "
    "best category from this exact list:\n"
    + "\n".join(f"- {c}" for c in CATEGORIES)
    + "\n\nAlso write a concise one-line summary (max ~20 words) in plain English "
    "describing what the notice is about, inferred from the title. "
    'Respond ONLY with strict JSON: {"category": "<one of the list>", '
    '"summary": "<one line>"}. The category MUST match an item from the list verbatim.'
)


def keyword_classify(title: str) -> str:
    low = title.lower()
    for category in CATEGORIES:
        for kw in _KEYWORDS.get(category, []):
            if kw in low:
                return category
    return "General"


def _coerce_category(value, title: str) -> str:
    if value:
        v = value.strip()
        for c in CATEGORIES:
            if v.lower() == c.lower():
                return c
    return keyword_classify(title)


def classify(title: str, token, model: str = DEFAULT_MODEL, timeout: int = 20):
    if not token:
        return keyword_classify(title), title

    try:
        resp = requests.post(
            GITHUB_MODELS_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            json={
                "model": model,
                "temperature": 0,
                "max_tokens": 200,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": title},
                ],
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        category = _coerce_category(data.get("category"), title)
        summary = (data.get("summary") or "").strip() or title
        return category, summary
    except Exception as exc:
        print(f"  [classifier] GitHub Models failed ({exc}); using keyword fallback")
        return keyword_classify(title), title


if __name__ == "__main__":
    samples = [
        "Seat Plan for Final-Term Exams of Spring 2025-26",
        "Announcement Notice of AIUB World Cup 2026",
        "Summer 2025-26 :: FST Adding Dropping",
        "Admission Test Final Result of Summer 2025-26",
        "25th Convocation Notice",
        "Some unrelated bulletin",
    ]
    for s in samples:
        print(f"{keyword_classify(s):28}  <-  {s}")
