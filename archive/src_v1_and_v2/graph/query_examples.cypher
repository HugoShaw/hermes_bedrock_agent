-- ============================================================
-- Neptune Analytics openCypher Query Examples
-- ============================================================

-- 1. Query all relationships
MATCH (a)-[r]->(b)
RETURN a.`~id` AS from_id, type(r) AS rel_type, b.`~id` AS to_id
LIMIT 100;

-- 2. Query nodes with name containing payment or 付款
MATCH (n)
WHERE n.name CONTAINS 'payment' OR n.name CONTAINS '付款'
RETURN n.`~id` AS id, labels(n) AS labels, n.name AS name
LIMIT 50;

-- 3. One-hop relationships from a specific node
MATCH (n {`~id`: 'node_xxx'})-[r]-(m)
RETURN n.`~id` AS source, type(r) AS rel_type, m.`~id` AS target, m.name AS target_name;

-- 4. Two-hop relationships from a specific node
MATCH (n {`~id`: 'node_xxx'})-[r1]-(m)-[r2]-(o)
WHERE n <> o
RETURN n.`~id` AS source, type(r1) AS rel1, m.`~id` AS mid,
       type(r2) AS rel2, o.`~id` AS target
LIMIT 100;

-- 5. Vector similarity top-k query
CALL neptune.algo.vectors.topKByEmbedding([0.1, 0.2, ...], {topK: 10})
YIELD node, score
RETURN node, score
ORDER BY score DESC;

-- 6. GraphRAG query - vector search + graph traversal
CALL neptune.algo.vectors.topKByEmbedding([0.1, 0.2, ...], {topK: 5})
YIELD node, score
WITH node, score
MATCH (node)-[r]-(neighbor)
RETURN node.`~id` AS node_id, node.name AS node_name, node.text AS node_text,
       score, type(r) AS rel_type,
       neighbor.`~id` AS neighbor_id, neighbor.name AS neighbor_name
ORDER BY score DESC
LIMIT 50;
