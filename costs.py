"""
Token cost of a run, from the usage LangChain records per model.

Prices are USD per 1M tokens from https://openai.com/api/pricing (standard tier). Update them here
when prices change or a new model is used; models missing from the table are reported, not guessed.
"""

PRICES = {
    #               input, cached input, output
    "gpt-4.1":      (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-4o":       (2.50, 1.25, 10.00),
    "gpt-4o-mini":  (0.15, 0.075, 0.60),
    "gpt-5":        (1.25, 0.125, 10.00),
    "gpt-5-mini":   (0.25, 0.025, 2.00),
    "gpt-5-nano":   (0.05, 0.005, 0.40),
}
WHISPER_PER_MINUTE = 0.006


def price_for(model: str) -> tuple[float, float, float] | None:
    """Responses name dated snapshots (e.g. "gpt-4.1-mini-2025-04-14"), so the longest matching prefix wins."""
    matches = [name for name in PRICES if model == name or model.startswith(name + "-")]
    return PRICES[max(matches, key=len)] if matches else None


def usage_cost(usage_by_model: dict[str, dict]) -> tuple[float, list[str]]:
    """
    `usage_by_model` is UsageMetadataCallbackHandler.usage_metadata: {model: {"input_tokens",
    "output_tokens", "input_token_details": {"cache_read"}}}. Returns the cost and the models with no price.
    """
    total, unknown = 0.0, []
    for model, usage in usage_by_model.items():
        price = price_for(model)
        if price is None:
            unknown.append(model)
            continue
        cached = (usage.get("input_token_details") or {}).get("cache_read", 0) or 0
        fresh = usage.get("input_tokens", 0) - cached
        total += (fresh * price[0] + cached * price[1] + usage.get("output_tokens", 0) * price[2]) / 1_000_000
    return total, unknown
