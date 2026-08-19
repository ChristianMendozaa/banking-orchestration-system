import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class MaskingResult:
    masked_text: str
    counts: dict[str, int]

    @property
    def pii_types(self) -> list[str]:
        return sorted(self.counts)


class PIIMaskingService:
    """Local, deterministic masking for the Bolivian banking context."""

    _patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        (
            "EMAIL",
            re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        ),
        (
            "TARJETA",
            re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
        ),
        (
            "CUENTA",
            re.compile(
                r"(?i)\b(?:cuenta|n[uú]mero de cuenta)\s*(?:n(?:ro)?\.?|#)?\s*[:\-]?\s*\d{6,20}\b"
            ),
        ),
        (
            "TELEFONO",
            re.compile(r"(?<!\d)(?:\+?591[ -]?)?[67]\d{7}(?!\d)"),
        ),
        (
            "IDENTIFICADOR",
            re.compile(
                r"(?i)\b(?:ci|c\.i\.|nit|carnet|documento)\s*(?:n(?:ro)?\.?|#)?\s*[:\-]?\s*[A-Z0-9-]{5,16}\b"
            ),
        ),
        (
            "MONTO",
            re.compile(r"(?i)(?:bs\.?|bolivianos?|usd|d[oó]lares?|\$)\s*\d[\d.,]*"),
        ),
        (
            "NOMBRE",
            # The `(?i)` used to cover the name characters too, so "soy" plus any one-to-four
            # following words became [NOMBRE]: a live session stored its own greeting as
            # "Hola, [NOMBRE]." after eating "soy tu asistente virtual", and "soy adulto mayor y
            # no puedo entrar a mi cuenta" lost both the preferential-attention and the access
            # signal before the classifier ever saw it. The trigger stays case-insensitive; the
            # name itself must now actually look like a name.
            re.compile(
                r"(?i:\b(?:me llamo|mi nombre es|soy)\s+)"
                r"(?-i:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,3})"
            ),
        ),
    )

    # Words that are capitalised only because they open a sentence ("Soy cliente del banco") and
    # never identify anyone. Without this, sentence-initial "Soy Jubilado" would still be masked.
    _NOT_A_NAME = frozenset(
        {
            "cliente",
            "clienta",
            "jubilado",
            "jubilada",
            "titular",
            "adulto",
            "adulta",
            "mayor",
            "nuevo",
            "nueva",
            "usuario",
            "usuaria",
            "beneficiario",
            "beneficiaria",
            "estudiante",
            "tu",
            "su",
            "el",
            "la",
            "un",
            "una",
        }
    )

    def mask(self, text: str) -> MaskingResult:
        masked = text
        counts: Counter[str] = Counter()
        for entity_type, pattern in self._patterns:

            def replace(match: re.Match[str], kind: str = entity_type) -> str:
                if kind == "NOMBRE" and self._opens_with_common_word(match.group(0)):
                    return match.group(0)
                counts[kind] += 1
                return f"[{kind}]"

            masked = pattern.sub(replace, masked)
        return MaskingResult(masked_text=masked, counts=dict(counts))

    @classmethod
    def _opens_with_common_word(cls, matched: str) -> bool:
        """True when the first captured 'name' word is an ordinary noun, not a name."""
        words = matched.split()
        # The trigger is one word ("soy") or three ("mi nombre es" / "me llamo" is two).
        for index, word in enumerate(words):
            if word.lower() in {"soy", "llamo", "es"}:
                candidate = words[index + 1] if index + 1 < len(words) else ""
                return candidate.lower() in cls._NOT_A_NAME
        return False
