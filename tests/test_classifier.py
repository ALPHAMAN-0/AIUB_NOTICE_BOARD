"""Categorisation: the keyword rules, and the guarded use of the model's answer."""
from __future__ import annotations

import json

import pytest
import requests

import classifier

GH_TOKEN = "gh-test-token"


def completion(content: str) -> dict:
    """A chat-completions body carrying `content` as the model's reply."""
    return {"choices": [{"message": {"content": content}}]}


def test_keyword_classify_covers_every_category():
    samples = {
        "Seat Plan for Final-Term Exams of Spring 2025-26": "Exam",
        "Summer 2025-26 :: FST Adding Dropping": "Registration / Add-Drop",
        "Admission Test Final Result of Summer 2025-26": "Admission",
        "CGPA and Grade Sheet Published": "Result",
        "Tuition Fee Payment Deadline": "Fee / Scholarship",
        "University Closed on Victory Day": "Holiday",
        "25th Convocation Notice": "Event",
        "Some unrelated bulletin": "General",
    }
    assert set(samples.values()) == set(classifier.CATEGORIES)
    for title, category in samples.items():
        assert classifier.keyword_classify(title) == category, title


def test_classify_without_a_token_uses_keywords_and_makes_no_request():
    # the autouse `offline` fixture fails the test if an HTTP call is attempted
    assert classifier.classify("Midterm exam schedule", None) == (
        "Exam",
        "Midterm exam schedule",
    )


def test_classify_takes_only_an_allow_listed_category_from_the_model(monkeypatch, response):
    answers = iter([
        {"category": "holiday", "summary": "  Campus closed on Thursday.  "},
        {"category": "Ignore previous instructions <b>", "summary": "x"},
    ])
    requests_made = []

    def fake_post(url, **kwargs):
        requests_made.append((url, kwargs))
        return response(200, completion(json.dumps(next(answers))))

    monkeypatch.setattr(requests, "post", fake_post)

    assert classifier.classify("Notice", GH_TOKEN) == ("Holiday", "Campus closed on Thursday.")
    # an invented category is dropped in favour of the keyword rules
    assert classifier.classify("Midterm exam schedule", GH_TOKEN) == ("Exam", "x")

    url, kwargs = requests_made[0]
    assert url == classifier.GITHUB_MODELS_URL
    assert kwargs["headers"]["Authorization"] == f"Bearer {GH_TOKEN}"
    assert kwargs["json"]["messages"][-1] == {"role": "user", "content": "Notice"}


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(lambda response: response(410, text="Gone"), id="endpoint gone"),
        pytest.param(lambda response: response(200, text="OK"), id="200 with a non-JSON body"),
        pytest.param(
            lambda response: response(200, completion("not json")), id="reply is not JSON"
        ),
        pytest.param(
            lambda response: response(200, completion('["a", "list"]')), id="reply has wrong shape"
        ),
    ],
)
def test_classify_falls_back_to_keywords_when_the_model_call_fails(
    monkeypatch, capsys, response, reply
):
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: reply(response))

    assert classifier.classify("Tuition fee waiver", GH_TOKEN) == (
        "Fee / Scholarship",
        "Tuition fee waiver",
    )
    printed = capsys.readouterr().out
    assert "using keyword fallback" in printed
    assert GH_TOKEN not in printed
