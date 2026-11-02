"""Read extension grants at consumer boundaries.

Session-only callers carry the records returned by extension enable in the
``extensions`` payload field. This is routing context, not a security boundary.
Persistent tasks always use their own stored records instead.
"""
from .models import DomainError
from .tasks import EXTENSIONS


def grants(records):
    if not isinstance(records, list):
        raise DomainError("invalid_extension", "extensions context must be a list")
    result = {}
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get("id"), str)
                or record.get("id") not in EXTENSIONS):
            raise DomainError("invalid_extension", "Unknown extension in context")
        package = record["id"]
        included, excluded = record.get("included"), record.get("excluded")
        if (package in result or not isinstance(record.get("scope"), str)
                or record.get("scope") not in {"full", "custom"}
                or not isinstance(included, list) or not isinstance(excluded, list)
                or any(not isinstance(x, str) for x in included + excluded)
                or not set(included + excluded) <= EXTENSIONS[package]
                or set(included) & set(excluded)
                or (record["scope"] == "full" and set(included) != EXTENSIONS[package])):
            raise DomainError("invalid_extension", "Invalid extension scope in context", {"id": package})
        result[package] = set(included)
    return result


def includes(context, package, member):
    return member in context.get(package, set())
