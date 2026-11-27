export function extraction_pipeline_helper_19_019Normalize(value) {
  return value.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
}

export function extraction_pipeline_helper_19_019Percent(part, total) {
  if (total <= 0) {
    return 0;
  }
  return Math.round((part / total) * 1000) / 10;
}

export function extraction_pipeline_helper_19_019Unique(values) {
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
