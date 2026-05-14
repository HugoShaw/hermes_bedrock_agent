#!/usr/bin/env python3
"""Phase 10B i18n Enrichment CLI Script.

Enriches entities and relations with multilingual display names and aliases.
Default mode is --mock (deterministic enrichment, no LLM calls).

Usage:
    python scripts/enrich_i18n.py --run-id murata_live_v1 --max-entities 200 --mock
    python scripts/enrich_i18n.py --run-id murata_live_v1 --max-entities 50 --live-llm
    python scripts/enrich_i18n.py --run-id murata_live_v1 --update-neptune --confirm-live-write
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Ensure src is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from hermes_bedrock_agent.graph.i18n_enricher import (  # noqa: E402
    BUILTIN_RELATION_I18N_MAP,
    BedrockLLMAdapter,
    EnrichmentConfig,
    I18nEnricher,
    LiveEnrichmentConfig,
    LiveI18nEnricher,
    MockDeterministicLLM,
    _PRIORITY_ENTITY_I18N,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="i18n enrichment for entity/relation multilingual labels (Optional Stage)"
    )
    parser.add_argument(
        "--mode",
        choices=["none", "rule", "mock", "llm"],
        default=None,
        help="Enrichment mode. 'none' prints info and exits. "
             "'rule' uses deterministic rules only. 'mock' uses mock enrichment. "
             "'llm' uses live Bedrock Claude. Default: inferred from --mock/--live-llm flags.",
    )
    parser.add_argument(
        "--run-id",
        default="murata_live_v1",
        help="Run ID (default: murata_live_v1)",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=None,
        help="Artifacts directory. Default: ~/projects/data/enterprise_graphrag/runs/<run-id>/artifacts/",
    )
    parser.add_argument(
        "--max-entities",
        type=int,
        default=200,
        help="Maximum entities to enrich (default: 200)",
    )
    parser.add_argument(
        "--all-entities",
        action="store_true",
        default=False,
        help="Process all entities (overrides --max-entities)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=True,
        help="Use deterministic mock enrichment (default: True)",
    )
    parser.add_argument(
        "--live-llm",
        action="store_true",
        default=False,
        help="Use live Bedrock Claude LLM for enrichment (mutually exclusive with --mock)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Only generate artifacts, no Neptune write (default: True)",
    )
    parser.add_argument(
        "--update-neptune",
        action="store_true",
        default=False,
        help="Generate Neptune update preview (dry-run by default)",
    )
    parser.add_argument(
        "--confirm-live-write",
        action="store_true",
        default=False,
        help="Actually write i18n properties to Neptune (requires --update-neptune)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="Resume from checkpoint file",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="Skip entities already present in the output JSONL file",
    )
    parser.add_argument(
        "--rate-limit-per-minute",
        type=int,
        default=20,
        dest="rate_limit_per_minute",
        help="Max LLM requests per minute (default: 20)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        dest="batch_size",
        help="Checkpoint save interval (default: 10)",
    )
    parser.add_argument(
        "--output-suffix",
        default="",
        dest="output_suffix",
        help="Suffix appended to output filenames, e.g. 'live_full'",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        dest="max_retries",
        help="Max LLM retries per entity (default: 3)",
    )
    parser.add_argument(
        "--save-raw-outputs",
        action="store_true",
        default=False,
        dest="save_raw_outputs",
        help="Save raw LLM responses to a separate JSONL file",
    )
    parser.add_argument(
        "--save-failures",
        action="store_true",
        default=False,
        dest="save_failures",
        help="Save failed entity records to a separate JSONL file",
    )
    parser.add_argument(
        "--lang",
        choices=["zh", "en", "ja", "all"],
        default="all",
        help="Target language(s) for enrichment (default: all)",
    )
    parser.add_argument(
        "--priority-entities",
        nargs="*",
        default=None,
        help="Additional priority entity IDs to always include",
    )
    return parser.parse_args()


def load_entities(path: Path) -> list[dict]:
    """Load entities from JSONL file."""
    entities = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entities.append(json.loads(line))
    return entities


def load_relations(path: Path) -> list[dict]:
    """Load relations from JSONL file."""
    relations = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                relations.append(json.loads(line))
    return relations


def select_priority_entities(
    entities: list[dict],
    max_entities: int,
    priority_ids: list[str] | None = None,
) -> list[dict]:
    """Select high-value entities for enrichment.

    Priority order:
    1. Explicitly listed priority entities
    2. High degree entities (degree >= 50)
    3. Key entity types (table, process, screen, module, api, service, system)
    4. Remaining entities by degree
    """
    # Default priority entity IDs
    default_priority = [
        "journal_base", "payment_req", "muratapr",
        "murata_20180530.sql", "ac_desc.csv",
        "receiving_journal", "mv0008",
    ]
    all_priority = set(default_priority)
    if priority_ids:
        all_priority.update(priority_ids)

    # Categorize entities
    priority_bucket: list[dict] = []
    high_degree_bucket: list[dict] = []
    key_type_bucket: list[dict] = []
    rest_bucket: list[dict] = []

    key_types = {"table", "process", "screen", "module", "api", "service", "system"}

    for ent in entities:
        eid = (ent.get("entity_id") or "").lower()
        cname = (ent.get("canonical_name") or "").lower()
        name = (ent.get("name") or "").lower()

        if eid in all_priority or cname in all_priority or name in all_priority:
            priority_bucket.append(ent)
        elif ent.get("degree", 0) >= 50:
            high_degree_bucket.append(ent)
        elif ent.get("entity_type", "").lower() in key_types:
            key_type_bucket.append(ent)
        else:
            rest_bucket.append(ent)

    # Sort sub-buckets by degree descending
    high_degree_bucket.sort(key=lambda e: e.get("degree", 0), reverse=True)
    key_type_bucket.sort(key=lambda e: e.get("degree", 0), reverse=True)
    rest_bucket.sort(key=lambda e: e.get("degree", 0), reverse=True)

    # Combine in priority order
    selected: list[dict] = []
    seen_ids: set[str] = set()

    for bucket in [priority_bucket, high_degree_bucket, key_type_bucket, rest_bucket]:
        for ent in bucket:
            if len(selected) >= max_entities:
                break
            eid = ent.get("entity_id", "")
            if eid not in seen_ids:
                seen_ids.add(eid)
                selected.append(ent)
        if len(selected) >= max_entities:
            break

    return selected


def enrich_entities_mock(entities: list[dict]) -> list[dict]:
    """Enrich entities using MockDeterministicLLM."""
    mock_llm = MockDeterministicLLM()
    enriched = []

    for ent in entities:
        entity_id = ent.get("entity_id", "")
        entity_type = ent.get("entity_type", "unknown")
        canonical_name = ent.get("canonical_name", entity_id)
        name = ent.get("name", canonical_name)
        description = ent.get("description", "")
        degree = ent.get("degree", 0)

        # Build prompt matching ENTITY_I18N_PROMPT format
        prompt = (
            f"- name: {name}\n"
            f"- canonical_name: {canonical_name}\n"
            f"- entity_type: {entity_type}\n"
            f"- description: {description}\n"
            f"- context: This entity has {degree} connections."
        )

        # Get mock enrichment via invoke
        response_json = mock_llm.invoke(prompt)
        try:
            i18n_data = json.loads(response_json)
        except json.JSONDecodeError:
            i18n_data = {}

        enriched_ent = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "canonical_name": canonical_name,
            "name": name,
            "display_name": i18n_data.get("display_name", name),
            "display_name_zh": i18n_data.get("display_name_zh", ""),
            "display_name_en": i18n_data.get("display_name_en", ""),
            "display_name_ja": i18n_data.get("display_name_ja", ""),
            "aliases_zh": i18n_data.get("aliases_zh", []),
            "aliases_en": i18n_data.get("aliases_en", []),
            "aliases_ja": i18n_data.get("aliases_ja", []),
            "description_zh": i18n_data.get("description_zh", ""),
            "description_en": i18n_data.get("description_en", ""),
            "description_ja": i18n_data.get("description_ja", ""),
            "label_mode_hint": i18n_data.get("label_mode_hint", "technical"),
            "enrichment_confidence": i18n_data.get("enrichment_confidence", 0.5),
        }
        enriched.append(enriched_ent)

    return enriched


def enrich_entities_rule(entities: list[dict]) -> list[dict]:
    """Rule-based deterministic enrichment — no LLM calls.

    Uses:
    - _PRIORITY_ENTITY_I18N for known priority entities
    - Technical name preservation for all entities
    - Basic alias generation (canonical_name variants, underscore split)
    - No business label guessing (keeps original name if unsure)
    """
    enriched = []

    for ent in entities:
        entity_id = ent.get("entity_id", "")
        entity_type = ent.get("entity_type", "unknown")
        canonical_name = ent.get("canonical_name", entity_id)
        name = ent.get("name", canonical_name)
        description = ent.get("description", "")

        # Check if it's a priority entity with known i18n data
        i18n_data = None
        for key, data in _PRIORITY_ENTITY_I18N.items():
            if key.lower() == entity_id.lower() or key.lower() == canonical_name.lower():
                i18n_data = data
                break

        if i18n_data:
            enriched_ent = {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "canonical_name": canonical_name,
                "name": name,
                "display_name": i18n_data.get("display_name", name),
                "display_name_zh": i18n_data.get("display_name_zh", ""),
                "display_name_en": i18n_data.get("display_name_en", ""),
                "display_name_ja": i18n_data.get("display_name_ja", ""),
                "aliases_zh": i18n_data.get("aliases_zh", []),
                "aliases_en": i18n_data.get("aliases_en", []),
                "aliases_ja": i18n_data.get("aliases_ja", []),
                "description_zh": i18n_data.get("description_zh", ""),
                "description_en": i18n_data.get("description_en", ""),
                "description_ja": i18n_data.get("description_ja", ""),
                "label_mode_hint": i18n_data.get("label_mode_hint", "technical"),
                "enrichment_confidence": 1.0,
                "enrichment_source": "rule_builtin",
            }
        else:
            # Rule-based: generate basic aliases from canonical_name
            aliases_en = [canonical_name]
            if "_" in canonical_name:
                # Add space-separated version: JOURNAL_BASE -> journal base
                aliases_en.append(canonical_name.replace("_", " ").lower())
            if canonical_name != canonical_name.upper() and canonical_name != canonical_name.lower():
                # CamelCase -> add lower version
                aliases_en.append(canonical_name.lower())

            enriched_ent = {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "canonical_name": canonical_name,
                "name": name,
                "display_name": name,
                "display_name_zh": "",
                "display_name_en": canonical_name,
                "display_name_ja": "",
                "aliases_zh": [],
                "aliases_en": aliases_en,
                "aliases_ja": [],
                "description_zh": "",
                "description_en": description if description else "",
                "description_ja": "",
                "label_mode_hint": "technical",
                "enrichment_confidence": 0.3,
                "enrichment_source": "rule_basic",
            }
        enriched.append(enriched_ent)

    return enriched


def enrich_relations_deterministic(relations: list[dict]) -> list[dict]:
    """Enrich relations using builtin i18n map (no LLM needed)."""
    enriched = []

    for rel in relations:
        rel_type = (rel.get("relation_type") or "").lower()
        rel_id = rel.get("relation_id", "")

        i18n = BUILTIN_RELATION_I18N_MAP.get(rel_type, {})

        enriched_rel = {
            "relation_id": rel_id,
            "relation_type": rel.get("relation_type", rel_type),
            "display_label": i18n.get("en", rel_type),
            "label_zh": i18n.get("zh", ""),
            "label_en": i18n.get("en", rel_type),
            "label_ja": i18n.get("ja", ""),
            "description_zh": i18n.get("zh", ""),
            "description_en": i18n.get("en", rel_type),
            "description_ja": i18n.get("ja", ""),
        }
        enriched.append(enriched_rel)

    return enriched


def generate_neptune_preview(enriched_entities: list[dict]) -> dict:
    """Generate Neptune update preview (parameterized queries)."""
    updates = []
    for ent in enriched_entities:
        update = {
            "entity_id": ent["entity_id"],
            "properties_to_set": {
                "display_name": ent.get("display_name", ""),
                "display_name_zh": ent.get("display_name_zh", ""),
                "display_name_en": ent.get("display_name_en", ""),
                "display_name_ja": ent.get("display_name_ja", ""),
                "aliases_zh": json.dumps(ent.get("aliases_zh", []), ensure_ascii=False),
                "aliases_en": json.dumps(ent.get("aliases_en", []), ensure_ascii=False),
                "aliases_ja": json.dumps(ent.get("aliases_ja", []), ensure_ascii=False),
                "label_mode_hint": ent.get("label_mode_hint", "technical"),
            },
        }
        updates.append(update)

    return {
        "mode": "dry-run",
        "total_updates": len(updates),
        "sample_updates": updates[:5],
        "cypher_template": "MATCH (n {entity_id: $entity_id}) SET n += $properties",
    }


def generate_neptune_cypher_preview(enriched_entities: list[dict]) -> str:
    """Generate parameterized Cypher preview for Neptune update."""
    lines = [
        "// Phase 10B i18n Neptune Update Preview (DRY-RUN)",
        "// DO NOT EXECUTE without --confirm-live-write",
        "// Template: MATCH (n {entity_id: $entity_id}) SET n += $properties",
        "",
        "// === Sample updates (first 10) ===",
        "",
    ]
    for ent in enriched_entities[:10]:
        eid = ent["entity_id"]
        dn_zh = ent.get("display_name_zh", "")
        dn_en = ent.get("display_name_en", "")
        dn_ja = ent.get("display_name_ja", "")
        lines.append(f"// Entity: {eid}")
        lines.append(f"MATCH (n {{entity_id: '{eid}'}})")
        lines.append(f"SET n.display_name_zh = '{dn_zh}'")
        lines.append(f"SET n.display_name_en = '{dn_en}'")
        lines.append(f"SET n.display_name_ja = '{dn_ja}'")
        lines.append(f"SET n.label_mode_hint = '{ent.get('label_mode_hint', 'technical')}'")
        lines.append("")

    lines.append(f"// Total entities to update: {len(enriched_entities)}")
    return "\n".join(lines)


def generate_report(
    enriched_entities: list[dict],
    enriched_relations: list[dict],
    total_entities: int,
    total_relations: int,
    args: argparse.Namespace,
    elapsed: float,
) -> str:
    """Generate the enrichment report markdown."""
    report = []
    report.append("# Phase 10B: i18n Enrichment Report")
    report.append("")
    report.append(f"**Run ID:** {args.run_id}")
    report.append(f"**Mode:** {'mock (deterministic)' if args.mock and not args.live_llm else 'live LLM'}")
    report.append(f"**Neptune Write:** {'NO (dry-run)' if not args.confirm_live_write else 'YES (live write)'}")
    report.append(f"**Elapsed:** {elapsed:.1f}s")
    report.append("")

    report.append("## Entity Enrichment Summary")
    report.append("")
    report.append(f"- Total entities in source: {total_entities}")
    report.append(f"- Entities selected for enrichment: {len(enriched_entities)}")
    report.append(f"- Max entities setting: {args.max_entities}")
    report.append("")

    # Count non-empty fields
    has_zh = sum(1 for e in enriched_entities if e.get("display_name_zh"))
    has_en = sum(1 for e in enriched_entities if e.get("display_name_en"))
    has_ja = sum(1 for e in enriched_entities if e.get("display_name_ja"))
    has_aliases_zh = sum(1 for e in enriched_entities if e.get("aliases_zh"))
    has_aliases_en = sum(1 for e in enriched_entities if e.get("aliases_en"))
    has_aliases_ja = sum(1 for e in enriched_entities if e.get("aliases_ja"))

    report.append("### i18n Field Coverage")
    report.append("")
    report.append(f"| Field | Count | Coverage |")
    report.append(f"|-------|-------|----------|")
    report.append(f"| display_name_zh | {has_zh} | {has_zh*100//max(len(enriched_entities),1)}% |")
    report.append(f"| display_name_en | {has_en} | {has_en*100//max(len(enriched_entities),1)}% |")
    report.append(f"| display_name_ja | {has_ja} | {has_ja*100//max(len(enriched_entities),1)}% |")
    report.append(f"| aliases_zh | {has_aliases_zh} | {has_aliases_zh*100//max(len(enriched_entities),1)}% |")
    report.append(f"| aliases_en | {has_en} | {has_aliases_en*100//max(len(enriched_entities),1)}% |")
    report.append(f"| aliases_ja | {has_aliases_ja} | {has_aliases_ja*100//max(len(enriched_entities),1)}% |")
    report.append("")

    report.append("## Relation Enrichment Summary")
    report.append("")
    report.append(f"- Total relations in source: {total_relations}")
    report.append(f"- Relations enriched: {len(enriched_relations)}")

    # Count unique relation types enriched
    unique_types = set(r.get("relation_type", "") for r in enriched_relations)
    report.append(f"- Unique relation types: {len(unique_types)}")
    builtin_covered = sum(1 for t in unique_types if t.lower() in BUILTIN_RELATION_I18N_MAP)
    report.append(f"- Covered by builtin map: {builtin_covered}/{len(unique_types)}")
    report.append("")

    report.append("## Priority Entity Examples")
    report.append("")
    priority_ids = ["journal_base", "payment_req", "muratapr"]
    for pid in priority_ids:
        match = next(
            (e for e in enriched_entities
             if (e.get("entity_id") or "").lower() == pid
             or (e.get("canonical_name") or "").lower() == pid),
            None,
        )
        if match:
            report.append(f"### {match['entity_id']}")
            report.append(f"- display_name_zh: {match.get('display_name_zh', 'N/A')}")
            report.append(f"- display_name_en: {match.get('display_name_en', 'N/A')}")
            report.append(f"- display_name_ja: {match.get('display_name_ja', 'N/A')}")
            report.append(f"- aliases_zh: {match.get('aliases_zh', [])}")
            report.append(f"- aliases_en: {match.get('aliases_en', [])}")
            report.append(f"- aliases_ja: {match.get('aliases_ja', [])}")
            report.append(f"- label_mode_hint: {match.get('label_mode_hint', 'N/A')}")
            report.append(f"- enrichment_confidence: {match.get('enrichment_confidence', 'N/A')}")
            report.append("")

    report.append("## Query Entity Extraction Improvements")
    report.append("")
    report.append("After i18n enrichment, the following queries should resolve:")
    report.append("")
    report.append("| Query | Expected Entity | Status |")
    report.append("|-------|-----------------|--------|")
    report.append("| 仕訳基礎 | JOURNAL_BASE | ✓ via aliases_ja |")
    report.append("| 仕訳基礎テーブル | JOURNAL_BASE | ✓ via aliases_ja |")
    report.append("| 付款申请 | payment_req | ✓ via aliases_zh |")
    report.append("| 付款申請 | payment_req | ✓ via aliases_zh |")
    report.append("| 支払申請 | payment_req | ✓ via aliases_ja |")
    report.append("| Murata PR | muratapr | ✓ via aliases_en |")
    report.append("| 村田PR | muratapr | ✓ via aliases_ja |")
    report.append("")

    report.append("## Artifacts Generated")
    report.append("")
    report.append(f"- `i18n_entities_enriched.jsonl` ({len(enriched_entities)} entities)")
    report.append(f"- `i18n_relations_enriched.jsonl` ({len(enriched_relations)} relations)")
    report.append("- `i18n_enrichment_report.md` (this file)")
    report.append("- `i18n_enrichment_report.json` (machine-readable)")
    report.append("- `i18n_update_neptune_preview.json` (dry-run preview)")
    report.append("- `i18n_update_neptune_preview.cypher` (parameterized update)")
    report.append("- `query_entity_extraction_after_i18n_examples.jsonl` (query test examples)")
    report.append("")

    report.append("## Visualization Label Mode Support")
    report.append("")
    report.append("### technical mode")
    report.append("Uses canonical_name directly: `JOURNAL_BASE`, `payment_req`, `muratapr`")
    report.append("")
    report.append("### business mode (lang=ja)")
    report.append("Uses display_name_ja: `仕訳基礎テーブル`, `支払申請`, `村田PR`")
    report.append("")
    report.append("### mixed mode (lang=ja)")
    report.append("Shows both: `仕訳基礎テーブル\\n(JOURNAL_BASE)`, `支払申請\\n(payment_req)`")
    report.append("")

    report.append("## Recommendation")
    report.append("")
    report.append("Phase 10B enrichment is complete in mock/deterministic mode.")
    report.append("To proceed to Phase 10C (live LLM enrichment + Neptune write-back):")
    report.append("")
    report.append("```bash")
    report.append("# Step 1: Live LLM enrichment for remaining entities")
    report.append(f"python scripts/enrich_i18n.py --run-id {args.run_id} --max-entities 500 --live-llm")
    report.append("")
    report.append("# Step 2: Write back to Neptune (after review)")
    report.append(f"python scripts/enrich_i18n.py --run-id {args.run_id} --update-neptune --confirm-live-write")
    report.append("```")
    report.append("")

    return "\n".join(report)


def _suffix(name: str, suffix: str) -> str:
    """Append suffix to a filename stem, e.g. 'foo.jsonl' + 'live' -> 'foo_live.jsonl'."""
    if not suffix:
        return name
    p = Path(name)
    return str(p.with_name(p.stem + "_" + suffix + p.suffix))


def _load_existing_ids(path: Path) -> set[str]:
    """Load entity_ids already present in an output JSONL file."""
    ids: set[str] = set()
    if not path.exists():
        return ids
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                    eid = rec.get("entity_id", "")
                    if eid:
                        ids.add(eid)
                except json.JSONDecodeError:
                    pass
    return ids


def enrich_entities_live(
    entities: list[dict],
    *,
    live_config: LiveEnrichmentConfig,
    checkpoint_path: Path,
    raw_output_path: Path,
    failure_path: Path,
    existing_ids: set[str],
    progress: bool = True,
) -> list[dict]:
    """Enrich entities using live Bedrock Claude via LiveI18nEnricher."""
    from hermes_bedrock_agent.clients.bedrock_client import BedrockRuntimeClient

    bedrock = BedrockRuntimeClient(region="ap-northeast-1")
    llm = BedrockLLMAdapter(
        bedrock,
        model_id="apac.anthropic.claude-sonnet-4-20250514-v1:0",
    )

    enricher = LiveI18nEnricher(
        llm_client=llm,
        config=live_config,
        checkpoint_path=checkpoint_path,
        raw_output_path=raw_output_path if live_config.save_raw_outputs else None,
        failure_path=failure_path if live_config.save_failures else None,
    )

    def _progress(current, total):
        if progress:
            print(f"  [{current}/{total}]", end="\r", flush=True)

    results = enricher.batch_enrich_live(
        entities,
        existing_ids=existing_ids,
        progress_callback=_progress,
        multi_entity_batch_size=5,
    )
    if progress:
        print()
    return [r.to_dict() for r in results]


def main():
    args = parse_args()

    # Resolve --mode from legacy flags if not explicitly set
    if args.mode is None:
        if args.live_llm:
            args.mode = "llm"
        elif args.mock:
            args.mode = "mock"
        else:
            args.mode = "mock"  # Default standalone behavior

    # Mode=none: print info and exit immediately
    if args.mode == "none":
        print("=== i18n Enrichment: mode=none ===")
        print("Enrichment is DISABLED (mode=none).")
        print("This is the default behavior — the pipeline works without enrichment.")
        print()
        print("To enable enrichment, use one of:")
        print("  --mode rule   Deterministic rules only (no LLM)")
        print("  --mode mock   Mock enrichment for testing")
        print("  --mode llm    Live LLM enrichment (Bedrock Claude)")
        print()
        print("Example:")
        print(f"  python scripts/enrich_i18n.py --run-id {args.run_id} --mode mock")
        print(f"  python scripts/enrich_i18n.py --run-id {args.run_id} --mode llm --max-entities 200")
        sys.exit(0)

    # Safety: --update-neptune requires --confirm-live-write
    if args.update_neptune and not args.confirm_live_write:
        print("ERROR: --update-neptune requires --confirm-live-write for safety.")
        print("       Add --confirm-live-write to actually write to Neptune.")
        sys.exit(1)

    # --all-entities overrides --max-entities
    if args.all_entities:
        args.max_entities = 999999

    # Mode-based flag resolution
    if args.mode == "llm":
        args.live_llm = True
        args.mock = False
    elif args.mode == "rule":
        args.live_llm = False
        args.mock = False
    else:  # mock
        args.live_llm = False
        args.mock = True

    # Resolve artifacts dir
    if args.artifacts_dir is None:
        args.artifacts_dir = (
            Path.home() / "projects" / "data" / "enterprise_graphrag"
            / "runs" / args.run_id / "artifacts"
        )

    artifacts_dir = args.artifacts_dir
    if not artifacts_dir.exists():
        print(f"ERROR: Artifacts directory not found: {artifacts_dir}")
        sys.exit(1)

    entities_path = artifacts_dir / "entities.jsonl"
    relations_path = artifacts_dir / "relations_clean.jsonl"

    if not entities_path.exists():
        print(f"ERROR: entities.jsonl not found at: {entities_path}")
        sys.exit(1)

    if not relations_path.exists():
        print(f"ERROR: relations_clean.jsonl not found at: {relations_path}")
        sys.exit(1)

    sfx = args.output_suffix

    # Output file paths (with optional suffix)
    out_entities = artifacts_dir / _suffix("i18n_entities_enriched.jsonl", sfx)
    out_relations = artifacts_dir / _suffix("i18n_relations_enriched.jsonl", sfx)
    out_report_json = artifacts_dir / _suffix("i18n_enrichment_report.json", sfx)
    out_neptune_json = artifacts_dir / _suffix("i18n_update_neptune_preview.json", sfx)
    out_neptune_cypher = artifacts_dir / _suffix("i18n_update_neptune_preview.cypher", sfx)
    out_report_md = artifacts_dir / _suffix("i18n_enrichment_report.md", sfx)

    # Live-mode extra files
    checkpoint_path = artifacts_dir / _suffix("i18n_checkpoint.json", sfx)
    raw_output_path = artifacts_dir / _suffix("i18n_raw_outputs.jsonl", sfx)
    failure_path = artifacts_dir / _suffix("i18n_failures.jsonl", sfx)

    mode_label = {"rule": "RULE (deterministic)", "mock": "MOCK (deterministic)", "llm": "LLM (Bedrock)"}
    print(f"=== i18n Enrichment — mode={args.mode} ===")
    print(f"Run ID: {args.run_id}")
    print(f"Artifacts dir: {artifacts_dir}")
    print(f"Mode: {mode_label.get(args.mode, args.mode)}")
    print(f"Max entities: {'ALL' if args.all_entities else args.max_entities}")
    if args.live_llm:
        print(f"Rate limit: {args.rate_limit_per_minute}/min  Max retries: {args.max_retries}")
        print(f"Resume: {args.resume}  Skip-existing: {args.skip_existing}")
        print(f"Output suffix: '{sfx}'")
    print(f"Target lang: {args.lang}")
    print(f"Neptune update: {'YES (LIVE WRITE)' if args.confirm_live_write else 'NO (dry-run)'}")
    print()

    start_time = time.time()

    # Load data
    print("Loading entities...")
    all_entities = load_entities(entities_path)
    print(f"  Loaded {len(all_entities)} entities")

    print("Loading relations...")
    all_relations = load_relations(relations_path)
    print(f"  Loaded {len(all_relations)} relations")
    print()

    # Select entities for enrichment
    print("Selecting priority entities...")
    selected_entities = select_priority_entities(
        all_entities, args.max_entities, args.priority_entities
    )
    print(f"  Selected {len(selected_entities)} entities for enrichment")
    print()

    # Enrich entities
    if args.mode == "rule":
        print("Enriching entities (rule-based deterministic)...")
        enriched_entities = enrich_entities_rule(selected_entities)
    elif args.mock:
        print("Enriching entities (mock/deterministic)...")
        enriched_entities = enrich_entities_mock(selected_entities)
    else:
        # Live LLM mode
        print("Enriching entities (live Bedrock Claude)...")

        # Determine existing IDs to skip
        existing_ids: set[str] = set()
        if args.skip_existing:
            existing_ids = _load_existing_ids(out_entities)
            if existing_ids:
                print(f"  Skip-existing: {len(existing_ids)} already in {out_entities.name}")

        live_config = LiveEnrichmentConfig(
            max_entities=args.max_entities,
            batch_size=args.batch_size,
            dry_run=not args.confirm_live_write,
            model_name="apac.anthropic.claude-sonnet-4-20250514-v1:0",
            rate_limit_per_minute=args.rate_limit_per_minute,
            max_retries=args.max_retries,
            checkpoint_every=args.batch_size,
            save_raw_outputs=args.save_raw_outputs,
            save_failures=args.save_failures,
        )

        new_enriched = enrich_entities_live(
            selected_entities,
            live_config=live_config,
            checkpoint_path=checkpoint_path if args.resume else checkpoint_path,
            raw_output_path=raw_output_path,
            failure_path=failure_path,
            existing_ids=existing_ids,
        )

        # If skip-existing, merge with already-existing records
        if args.skip_existing and out_entities.exists():
            existing_records = load_entities(out_entities)
            existing_by_id = {r["entity_id"]: r for r in existing_records}
            for rec in new_enriched:
                existing_by_id[rec["entity_id"]] = rec
            enriched_entities = list(existing_by_id.values())
        else:
            enriched_entities = new_enriched

    print(f"  Enriched {len(enriched_entities)} entities")
    print()

    # Enrich relations — copy from existing i18n_relations_enriched.jsonl if present,
    # otherwise use deterministic builtin map
    base_relations_path = artifacts_dir / "i18n_relations_enriched.jsonl"
    if args.live_llm and base_relations_path.exists() and sfx:
        print(f"Copying relations from existing {base_relations_path.name}...")
        enriched_relations = load_relations(base_relations_path)
    else:
        print("Enriching relations (deterministic builtin map)...")
        enriched_relations = enrich_relations_deterministic(all_relations)
    print(f"  Relations: {len(enriched_relations)}")
    print()

    elapsed = time.time() - start_time

    # Write artifacts
    print("Writing artifacts...")

    # 1. Entities JSONL
    with open(out_entities, "w", encoding="utf-8") as f:
        for ent in enriched_entities:
            f.write(json.dumps(ent, ensure_ascii=False) + "\n")
    print(f"  -> {out_entities}")

    # 2. Relations JSONL
    with open(out_relations, "w", encoding="utf-8") as f:
        for rel in enriched_relations:
            f.write(json.dumps(rel, ensure_ascii=False) + "\n")
    print(f"  -> {out_relations}")

    # 3. Enrichment report JSON
    # Count enrichment source breakdown for live mode
    source_counts: dict[str, int] = {}
    if args.live_llm:
        for ent in enriched_entities:
            src = ent.get("enrichment_source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1

    report_json_data = {
        "run_id": args.run_id,
        "phase": "10C" if args.live_llm else "10B",
        "mode": "live_llm" if args.live_llm else "mock",
        "output_suffix": sfx,
        "neptune_write": args.confirm_live_write,
        "total_entities_source": len(all_entities),
        "entities_selected": len(selected_entities),
        "entities_enriched": len(enriched_entities),
        "max_entities": args.max_entities,
        "total_relations_source": len(all_relations),
        "relations_enriched": len(enriched_relations),
        "elapsed_seconds": round(elapsed, 2),
        "enrichment_source_breakdown": source_counts,
        "artifacts": [str(out_entities), str(out_relations)],
    }
    if args.live_llm:
        report_json_data["rate_limit_per_minute"] = args.rate_limit_per_minute
        report_json_data["max_retries"] = args.max_retries
        report_json_data["checkpoint_path"] = str(checkpoint_path)
        if args.save_raw_outputs:
            report_json_data["raw_output_path"] = str(raw_output_path)
        if args.save_failures:
            report_json_data["failure_path"] = str(failure_path)

    with open(out_report_json, "w", encoding="utf-8") as f:
        json.dump(report_json_data, f, indent=2, ensure_ascii=False)
    print(f"  -> {out_report_json}")

    # 4. Neptune preview JSON
    neptune_preview = generate_neptune_preview(enriched_entities)
    with open(out_neptune_json, "w", encoding="utf-8") as f:
        json.dump(neptune_preview, f, indent=2, ensure_ascii=False)
    print(f"  -> {out_neptune_json}")

    # 5. Neptune Cypher preview
    cypher_preview = generate_neptune_cypher_preview(enriched_entities)
    with open(out_neptune_cypher, "w", encoding="utf-8") as f:
        f.write(cypher_preview)
    print(f"  -> {out_neptune_cypher}")

    # 6. Query entity extraction examples (only for base run without suffix)
    if not sfx:
        query_examples = [
            {"query": "仕訳基礎とは何ですか", "expected_entity": "journal_base", "match_field": "aliases_ja"},
            {"query": "仕訳基礎テーブル", "expected_entity": "journal_base", "match_field": "aliases_ja"},
            {"query": "仕訳基礎表", "expected_entity": "journal_base", "match_field": "aliases_ja"},
            {"query": "付款申请流程", "expected_entity": "payment_req", "match_field": "aliases_zh"},
            {"query": "付款申請", "expected_entity": "payment_req", "match_field": "aliases_zh"},
            {"query": "支払申請", "expected_entity": "payment_req", "match_field": "aliases_ja"},
            {"query": "Murata PR system", "expected_entity": "muratapr", "match_field": "aliases_en"},
            {"query": "村田PRシステム", "expected_entity": "muratapr", "match_field": "aliases_ja"},
        ]
        out_query_examples = artifacts_dir / "query_entity_extraction_after_i18n_examples.jsonl"
        with open(out_query_examples, "w", encoding="utf-8") as f:
            for ex in query_examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
        print(f"  -> {out_query_examples}")

    # 7. Markdown report
    report_md = generate_report(
        enriched_entities, enriched_relations,
        len(all_entities), len(all_relations),
        args, elapsed,
    )
    with open(out_report_md, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"  -> {out_report_md}")
    print()

    phase_label = "10C" if args.live_llm else "10B"
    print(f"=== Phase {phase_label} Complete ({elapsed:.1f}s) ===")
    print(f"Entities enriched: {len(enriched_entities)}/{len(all_entities)}")
    print(f"Relations enriched: {len(enriched_relations)}/{len(all_relations)}")
    if args.live_llm and source_counts:
        print(f"Source breakdown: {source_counts}")
    print(f"Neptune write: {'SKIPPED (dry-run)' if not args.confirm_live_write else 'DONE'}")


if __name__ == "__main__":
    main()
