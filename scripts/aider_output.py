"""Helpers for reading aider's stdout."""

# aider prints a reasoning model's thinking before this separator and the
# actual response after it (REASONING_END in aider/reasoning_tags.py). The
# thinking can draft its own `## Summary` or ```json``` block, so only what
# follows the separator counts.
REASONING_END = "------------\n► **ANSWER**"


def answer_text(text: str) -> str:
    """The response proper: everything after aider's reasoning separator, or
    the whole text when the model produced no separate reasoning.

    aider writes the separator once, but a model can quote it. Matching the
    full two-line form keeps a quote inside a JSON string (where the newline
    is escaped) from counting, and splitting on the *first* one keeps a quote
    in the answer from discarding the real response before it. A quote in the
    thinking only leaves some thinking ahead of the answer, where the
    extractors' last-block / last-heading rules still pick the answer.
    """
    _, sep, answer = text.partition(REASONING_END)
    return answer if sep else text
