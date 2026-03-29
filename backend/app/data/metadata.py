from __future__ import annotations

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "weather": ("weather", "rain", "storm", "temperature", "snow"),
    "crypto": ("crypto", "bitcoin", "ethereum", "btc", "eth", "solana"),
    "finance": ("finance", "stock", "earnings", "fed", "inflation", "macro", "economy"),
    "politics": ("election", "president", "senate", "policy", "politics", "government"),
    "sports": ("sports", "match", "game", "tournament", "goal", "nba", "nfl", "fifa"),
}


def infer_category(question: str, event_category: str | None = None) -> str:
    candidate = (event_category or "").strip().lower()
    if candidate:
        return candidate

    haystack = question.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return category
    return "all"

