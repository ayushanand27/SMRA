from typing import Literal

OutputLanguage = Literal["english", "hindi", "roman_hindi"]

OUTPUT_LANGUAGE_ALIASES: dict[str, OutputLanguage] = {
    "english": "english",
    "en": "english",
    "hindi": "hindi",
    "hi": "hindi",
    "devanagari": "hindi",
    "roman_hindi": "roman_hindi",
    "roman": "roman_hindi",
    "hinglish": "roman_hindi",
    "latin_hindi": "roman_hindi",
}


def normalize_output_language(raw: str | None) -> OutputLanguage:
    if raw is None or not str(raw).strip():
        return "english"
    key = str(raw).lower().strip().replace("-", "_")
    return OUTPUT_LANGUAGE_ALIASES.get(key, "english")
