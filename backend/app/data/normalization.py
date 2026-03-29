from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.data.metadata import infer_category
from app.domain.models import MarketQuote


def _parse_jsonish_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, str):
        cleaned = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(cleaned).astimezone(UTC)
        except ValueError:
            return None
    return None


def normalize_event_payload(payload: dict[str, Any]) -> list[MarketQuote]:
    event_id = str(payload.get("id") or payload.get("eventId") or "")
    event_slug = payload.get("slug") or payload.get("ticker") or event_id
    event_category = payload.get("category")
    related_group = payload.get("slug") or payload.get("title") or event_id

    markets: list[dict[str, Any]] = payload.get("markets") or []
    normalized: list[MarketQuote] = []

    for market in markets:
        outcomes = _parse_jsonish_list(market.get("outcomes"))
        prices = _parse_jsonish_list(market.get("outcomePrices"))
        token_ids = _parse_jsonish_list(market.get("clobTokenIds"))

        mapping = {
            str(outcome).strip().lower(): _parse_float(price)
            for outcome, price in zip(outcomes, prices, strict=False)
        }
        token_mapping = {
            str(outcome).strip().lower(): str(token_id)
            for outcome, token_id in zip(outcomes, token_ids, strict=False)
        }

        yes_price = mapping.get("yes", _parse_float(market.get("yesPrice")))
        no_price = mapping.get("no", _parse_float(market.get("noPrice"), default=max(0.0, 1.0 - yes_price)))

        question = market.get("question") or payload.get("title") or payload.get("question") or "Unknown market"
        category = infer_category(question, event_category)
        expires_at = _parse_datetime(market.get("endDate") or payload.get("endDate"))

        normalized.append(
            MarketQuote(
                market_id=str(market.get("id") or market.get("conditionId") or market.get("questionID") or question),
                event_id=event_id or None,
                slug=market.get("slug") or event_slug,
                question=question,
                category=category,
                related_group=str(market.get("groupItemTitle") or related_group),
                expiry=expires_at,
                yes_token_id=token_mapping.get("yes") or market.get("yesTokenId"),
                no_token_id=token_mapping.get("no") or market.get("noTokenId"),
                yes_price=yes_price,
                no_price=no_price,
                yes_bid=_parse_float(market.get("bestBid")),
                yes_ask=_parse_float(market.get("bestAsk")),
                no_bid=_parse_float(market.get("bestNoBid")),
                no_ask=_parse_float(market.get("bestNoAsk")),
                liquidity=_parse_float(market.get("liquidity") or payload.get("liquidity")),
                volume_24h=_parse_float(market.get("volume24hr") or payload.get("volume24hr")),
                recent_move=_parse_float(market.get("priceChange24hr")),
                orderbook_enabled=bool(market.get("enableOrderBook", True)),
                last_updated=_parse_datetime(market.get("updatedAt") or payload.get("updatedAt")) or datetime.now(UTC),
                metadata={
                    "neg_risk": bool(market.get("negRisk", False)),
                    "event_slug": event_slug,
                    "series": payload.get("seriesSlug"),
                },
            )
        )
    return normalized

