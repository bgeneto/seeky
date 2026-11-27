export function search_ranking_utilities_14_014Percent(part, total) {
  if (total <= 0) {
    return 0;
  }
  return Math.round((part / total) * 1000) / 10;
}

export function search_ranking_utilities_14_014Normalize(value) {
  return value.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
}

export function search_ranking_utilities_14_014Unique(values) {
  const seen = new Set();
  const result = [];
  for (const value of values) {
    if (!seen.has(value)) {
      seen.add(value);
      result.push(value);
    }
  }
  return result;
}
