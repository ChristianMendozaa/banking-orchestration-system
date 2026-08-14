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
            re.compile(
                r"(?i)\b(?:me llamo|mi nombre es|soy)\s+"
                r"[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+){0,3}"
            ),
        ),
    )

    def mask(self, text: str) -> MaskingResult:
        masked = text
        counts: Counter[str] = Counter()
        for entity_type, pattern in self._patterns:

            def replace(match: re.Match[str], kind: str = entity_type) -> str:
                counts[kind] += 1
                return f"[{kind}]"

            masked = pattern.sub(replace, masked)
        return MaskingResult(masked_text=masked, counts=dict(counts))
