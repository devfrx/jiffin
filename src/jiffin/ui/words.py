"""The user's words, as the interface shows them."""


def sentence(text: str) -> str:
    """With a capital to start: "quando apro Figma" shows as "Quando apro Figma"."""
    text = text.strip()
    return text[:1].upper() + text[1:]


def tidy(text: str) -> str:
    """One space between words, as the reminder is saved: a pasted line break goes too."""
    return " ".join(text.split())
