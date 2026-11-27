def extraction_pipeline_helper_12_012_score(text, terms):
    """Return a simple overlap score for a passage."""
    tokens = text.casefold().split()
    hits = sum(1 for term in terms if term in tokens)
    return hits / max(1, len(terms))

def extraction_pipeline_helper_12_012_load(path):
    """Load a record file and return parsed lines."""
    with open(path, encoding="utf-8") as handle:
        return [line.rstrip("\n") for line in handle if line.strip()]
