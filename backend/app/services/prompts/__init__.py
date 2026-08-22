"""Model-facing prompt text, kept apart from the code that transports it.

Every string in this package is business policy that happens to be addressed to a
model: the kiosk's persona, the consultation-level rules, the grounding rules. They
used to live inside `app.services.openai_provider` next to `httpx` calls and embedding
batching, which made the most important policy in the system the hardest thing in it
to find.

Nothing here imports anything from the application. Prompts are data.
"""

from app.services.prompts.classification import CLASSIFICATION_SYSTEM_PROMPT
from app.services.prompts.grounding import GROUNDED_ANSWER_SYSTEM_PROMPT
from app.services.prompts.voice import KIOSK_VOICE_INSTRUCTIONS

__all__ = [
    "CLASSIFICATION_SYSTEM_PROMPT",
    "GROUNDED_ANSWER_SYSTEM_PROMPT",
    "KIOSK_VOICE_INSTRUCTIONS",
]
