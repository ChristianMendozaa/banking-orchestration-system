"""Column helpers shared by every model module."""

from sqlalchemy import Enum


def string_enum(enum_type: type) -> Enum:
    return Enum(enum_type, native_enum=False, validate_strings=True, length=40)
