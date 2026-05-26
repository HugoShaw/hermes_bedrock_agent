# Diagram Parse Prompt

You are analyzing a diagram image (architecture diagram, flowchart, ER diagram, or sequence diagram).

## Input
- Image of a diagram

## Required Output (JSON)
```json
{
  "diagram_type": "architecture | flowchart | er_diagram | sequence | network | other",
  "title": "diagram title if visible",
  "description": "brief description of what the diagram shows",
  "nodes": [
    {"name": "node name", "label": "Component | Service | Table | Actor", "description": "what this represents"}
  ],
  "edges": [
    {"from": "source node", "to": "target node", "type": "FLOWS_TO | DEPENDS_ON | CONTAINS | CALLS_API", "label": "edge label if visible"}
  ],
  "annotations": ["any important text annotations"],
  "confidence": 0.0
}
```

## Rules
- Identify ALL nodes/boxes/shapes in the diagram
- Identify ALL connections/arrows between them
- Map connections to appropriate relationship types
- Include any text labels on edges
- Confidence based on diagram clarity
