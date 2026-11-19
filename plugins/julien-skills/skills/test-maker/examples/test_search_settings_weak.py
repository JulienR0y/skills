"""The "before" file: these tests pass, but most breakages go unnoticed.

Its data equals the defaults, it recomputes the expected date the way the code does,
and it never passes tools or documents.
"""

from datetime import date

from search_settings import SearchSettings, system_prompt


def test_round_trip():
    data = {"model": "small-model", "k": 20, "keyword_k": 20, "rerank_n": 5, "injection_filter": False}

    assert SearchSettings.from_dict(data).to_dict() == data


def test_prompt():
    today = date.today()

    assert system_prompt("Base", [], [], today) == f"Base\n\nCurrent date: {today.strftime('%Y-%m-%d')}."
