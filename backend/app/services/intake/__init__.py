"""Turn-level intake planning.

Classification describes candidate needs. Planning decides which candidates represent
independent operational cases. Keeping that boundary explicit prevents model output from
being persisted one-for-one as tickets.
"""

from app.services.intake.planning import IntakePlanner

__all__ = ["IntakePlanner"]
