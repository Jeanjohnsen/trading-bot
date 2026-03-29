from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.data.metadata import infer_category
from app.domain.models import MarketQuote

GENERIC_GROUP_LABELS = {"all", "general", "default", "other", "misc", "miscellaneous", "overview"}


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


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _normalized_group_label(value: Any) -> str | None:
    if value is None:
        return None
    label = str(value).strip()
    if not label:
        return None
    compact = " ".join(label.split())
    if compact.lower() in GENERIC_GROUP_LABELS:
        return None
    return compact.lower().replace(" ", "-")


def _normalized_outcome_label(value: Any) -> str | None:
    if value is None:
        return None
    label = str(value).strip().lower()
    if label in {"yes", "true", "1"}:
        return "yes"
    if label in {"no", "false", "0"}:
        return "no"
    return None


def _infer_resolution_outcome(market: dict[str, Any], payload: dict[str, Any], yes_price: float, no_price: float) -> int | None:
    candidates = [
        market.get("resolvedOutcome"),
        market.get("winningOutcome"),
        market.get("winner"),
        market.get("result"),
        payload.get("resolvedOutcome"),
        payload.get("winningOutcome"),
        payload.get("winner"),
        payload.get("result"),
    ]
    for candidate in candidates:
        normalized = _normalized_outcome_label(candidate)
        if normalized == "yes":
            return 1
        if normalized == "no":
            return 0
    if yes_price >= 0.999 and no_price <= 0.001:
        return 1
    if no_price >= 0.999 and yes_price <= 0.001:
        return 0
    return None


def normalize_event_payload(payload: dict[str, Any]) -> list[MarketQuote]:
    event_id = str(payload.get("id") or payload.get("eventId") or "")
    event_slug = payload.get("slug") or payload.get("ticker") or event_id
    event_title = payload.get("title") or payload.get("question") or event_slug
    event_category = payload.get("category")
    event_group_seed = event_id or str(event_slug or event_title)

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
        expires_at = _parse_datetime(
            market.get("endDate")
            or market.get("end_date")
            or market.get("resolveDate")
            or market.get("resolutionDate")
            or payload.get("endDate")
            or payload.get("end_date")
            or payload.get("resolveDate")
            or payload.get("resolutionDate")
        )
        group_label = _normalized_group_label(
            market.get("groupItemTitle")
            or market.get("groupTitle")
            or market.get("subtitle")
            or payload.get("groupItemTitle")
            or payload.get("groupTitle")
        )
        neg_risk = bool(market.get("negRisk", payload.get("negRisk", False)))
        related_group = f"{event_group_seed}:{group_label}" if group_label else (f"{event_group_seed}:event-tree" if neg_risk else None)
        market_closed = (
            _parse_bool(market.get("closed"))
            or _parse_bool(market.get("resolved"))
            or _parse_bool(market.get("archived"))
            or _parse_bool(payload.get("closed"))
            or _parse_bool(payload.get("resolved"))
            or _parse_bool(payload.get("archived"))
        )
        market_active = not (
            market.get("active") is False
            or payload.get("active") is False
            or str(market.get("active", "")).strip().lower() == "false"
            or str(payload.get("active", "")).strip().lower() == "false"
        )
        resolution_outcome = _infer_resolution_outcome(market, payload, yes_price, no_price) if market_closed else None

        normalized.append(
            MarketQuote(
                market_id=str(market.get("id") or market.get("conditionId") or market.get("questionID") or question),
                event_id=event_id or None,
                slug=market.get("slug") or event_slug,
                question=question,
                category=category,
                related_group=related_group,
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
                    "neg_risk": neg_risk,
                    "event_slug": event_slug,
                    "event_title": event_title,
                    "series": payload.get("seriesSlug"),
                    "group_label": group_label,
                    "closed": market_closed,
                    "active": market_active,
                    "cross_market_eligible": bool(related_group),
                    "resolved_outcome": resolution_outcome,
                },
            )
        )
    return normalized
