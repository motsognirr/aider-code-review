"""Helpers for reading aider's stdout."""

# aider prints a reasoning model's thinking before this marker and the actual
# response after it (aider/reasoning_tags.py). The thinking can draft its own
# `## Summary` or ```json``` block, so only what follows the marker counts.
ANSWER_MARKER = "► **ANSWER**"


def answer_text(text: str) -> str:
    """The response proper: everything after aider's last ANSWER marker, or
    the whole text when the model produced no separate reasoning."""
    return text.rpartition(ANSWER_MARKER)[2]
