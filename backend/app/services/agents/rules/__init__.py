"""Deterministic rules the agents lean on.

Every module here is a leaf: it imports from `app.domain.enums` and nothing else in the
application. That is what makes them safe to read on their own, and it is why the
agents can import them without any risk of a cycle.
"""
