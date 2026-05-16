def estimate_tokens(text: str):
    """
    Rough token estimate.
    1 token ≈ 4 characters for English text.
    """
    return len(text) // 4


def trim_to_budget(text: str, max_tokens: int):

    tokens = estimate_tokens(text)

    if tokens <= max_tokens:
        return text

    # trim oldest content
    chars_allowed = max_tokens * 4
    return text[-chars_allowed:]
