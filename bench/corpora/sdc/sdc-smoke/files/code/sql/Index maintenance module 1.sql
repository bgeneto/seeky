SELECT cluster_id, COUNT(*) AS members
FROM duplicate_clusters
GROUP BY cluster_id
HAVING COUNT(*) > 1
ORDER BY cluster_id;

SELECT version_group_id, document_id, version_number
FROM versions
WHERE is_latest = TRUE
ORDER BY version_group_id;

SELECT document_id, COUNT(*) AS passages
FROM passages
WHERE content_sha256 IS NOT NULL
GROUP BY document_id
ORDER BY document_id;
