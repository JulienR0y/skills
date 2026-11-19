"""Search settings for a chat agent: a small module to practise test-maker on."""

from dataclasses import dataclass
from datetime import date


@dataclass
class SearchSettings:
    model: str = "small-model"
    k: int = 20
    keyword_k: int = 20
    rerank_n: int = 5
    injection_filter: bool = False

    def __post_init__(self):
        if self.k < 1:
            raise ValueError(f"k must be at least 1, got {self.k}")

    @classmethod
    def from_dict(cls, data: dict) -> "SearchSettings":
        defaults = cls()
        return cls(
            model=data.get("model", defaults.model),
            k=data.get("k", defaults.k),
            keyword_k=data.get("keyword_k", defaults.keyword_k),
            rerank_n=data.get("rerank_n", defaults.rerank_n),
            injection_filter=data.get("injection_filter", defaults.injection_filter),
        )

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "k": self.k,
            "keyword_k": self.keyword_k,
            "rerank_n": self.rerank_n,
            "injection_filter": self.injection_filter,
        }


def system_prompt(base: str, tools: list[str], documents: list[str], today: date) -> str:
    prompt = base
    if tools:
        prompt += "\n\nAvailable tools: " + ", ".join(tools) + "."
    attached = list(dict.fromkeys(documents))
    if attached:
        prompt += "\n\nAttached documents: " + ", ".join(f"'{name}'" for name in attached) + "."
        if len(attached) == 1:
            prompt += "\nUse the attached document for any question about it."
        else:
            prompt += "\nAnswer with one summary per document."
    prompt += f"\n\nCurrent date: {today:%Y-%m-%d}."
    return prompt
