from newrelic_dashboard_updater.utils.variable_resolver import replace_variables

def contains_span_query(query: str) -> bool:
    """Check if query contains 'FROM Span' (case-insensitive)."""
    return "from span" in query.lower()

def build_updated_query(original_query: str, mapping: dict, variables: dict) -> str:
    """
    Apply span-to-metric mapping and replace variables using helper functions.
    """
    updated_query = original_query

    # Apply span-to-metric mapping
    for old, new in mapping.items():
        updated_query = updated_query.replace(old, new)

    # Replace variables using central logic
    updated_query = replace_variables(updated_query, {"variables": variables})

    return updated_query
