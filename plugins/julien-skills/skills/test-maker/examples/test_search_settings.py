"""The "after" file: every test can fail on a real regression."""

from datetime import date

import pytest

from search_settings import SearchSettings, system_prompt

TODAY = date(2026, 1, 15)


@pytest.fixture
def stored():
    """Stored settings whose every value differs from its default."""
    return {"model": "large-model", "k": 12, "keyword_k": 8, "rerank_n": 3, "injection_filter": True}


class TestSettings:
    def test_from_dict_keeps_every_stored_value(self, stored):
        settings = SearchSettings.from_dict(stored)

        assert (settings.model, settings.k, settings.keyword_k, settings.rerank_n, settings.injection_filter) == (
            "large-model",
            12,
            8,
            3,
            True,
        )

    def test_to_dict_returns_the_stored_values(self, stored):
        assert SearchSettings.from_dict(stored).to_dict() == stored

    def test_omitted_values_fall_back_to_the_defaults(self):
        assert SearchSettings.from_dict({}).to_dict() == {
            "model": "small-model",
            "k": 20,
            "keyword_k": 20,
            "rerank_n": 5,
            "injection_filter": False,
        }

    @pytest.mark.parametrize("k", [pytest.param(0, id="zero"), pytest.param(-3, id="negative")])
    def test_rejects_a_k_below_one(self, stored, k):
        stored["k"] = k

        with pytest.raises(ValueError, match="k must be at least 1"):  # smell-ok: the message is the user-facing contract
            SearchSettings.from_dict(stored)


class TestSystemPrompt:
    def test_without_tools_or_documents_is_the_base_and_the_date(self):
        assert system_prompt("Base", [], [], TODAY) == "Base\n\nCurrent date: 2026-01-15."

    def test_lists_tools_in_order(self):
        prompt = system_prompt("Base", ["search", "calculator"], [], TODAY)

        assert prompt == "Base\n\nAvailable tools: search, calculator.\n\nCurrent date: 2026-01-15."

    @pytest.mark.parametrize(
        ("documents", "scope", "guidance", "other"),
        [
            pytest.param(
                ["plan.pdf", "plan.pdf"],
                "Attached documents: 'plan.pdf'.",
                "Use the attached document",
                "one summary per document",
                id="one-document-twice",
            ),
            pytest.param(
                ["plan.pdf", "notes.docx", "plan.pdf"],
                "Attached documents: 'plan.pdf', 'notes.docx'.",
                "one summary per document",
                "Use the attached document",
                id="two-documents",
            ),
        ],
    )
    def test_names_each_document_once_with_matching_guidance(self, documents, scope, guidance, other):
        prompt = system_prompt("Base", [], documents, TODAY)

        assert scope in prompt
        assert guidance in prompt
        assert other not in prompt
