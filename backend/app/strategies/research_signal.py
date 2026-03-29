from __future__ import annotations

from app.domain.models import MarketQuote


def optional_research_stub(quote: MarketQuote) -> dict[str, str]:
    return {
        "status": "disabled_by_default",
        "message": f"Research mode is optional and not required for {quote.market_id}.",
    }

