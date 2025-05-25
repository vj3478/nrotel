# Replace span keywords using mappingdef contains_span_query(query: str) -> bool:
    """Check if query contains 'FROM Span' (case-insensitive)."""
    return "from span" in query.lower()


def build_updated_query(original_query: str, mapping: dict, variables: dict) -> str:
    """Apply span-to-metric mapping and replace variables."""
    updated_query = original_query

    # Apply mapping
    for old, new in mapping.items():
        updated_query = updated_query.replace(old, new)

    # Replace variables
    for var, val in variables.items():
        try:
            if isinstance(val, dict):
                if "value" in val:
                    val = val["value"]
                elif "defaultValues" in val:
                    val = val["defaultValues"]
            if isinstance(val, list):
                val = ", ".join(f"'{v}'" if not isinstance(v, (int, float)) else str(v) for v in val)
            else:
                val = f"'{val}'" if isinstance(val, str) else str(val)
            updated_query = updated_query.replace(f"{{{var}}}", val)
        except Exception:
            continue

    return updated_query
