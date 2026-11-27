def search_ranking_utilities_6_006_dedupe(values):
    """Keep the first occurrence of each value."""
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

def search_ranking_utilities_6_006_score(text, terms):
    """Return a simple overlap score for a passage."""
    tokens = text.casefold().split()
    hits = sum(1 for term in terms if term in tokens)
    return hits / max(1, len(terms))

def search_ranking_utilities_6_006_load(path):
    """Load a record file and return parsed lines."""
    with open(path, encoding="utf-8") as handle:
        return [line.rstrip("\n") for line in handle if line.strip()]
