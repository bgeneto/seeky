export function index_maintenance_module_13_013Normalize(value) {
  return value.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
}

export function index_maintenance_module_13_013Unique(values) {
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

export function index_maintenance_module_13_013Percent(part, total) {
  if (total <= 0) {
    return 0;
  }
  return Math.round((part / total) * 1000) / 10;
}
