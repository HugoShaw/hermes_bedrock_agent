Please execute Phase R2.5: VLM API Smoke Test + Narrow VLM Parsing.

Project root:

~/projects/hermes_bedrock_agent

Important context:

R2 report is accepted as PASS, but do not proceed to R3 yet.

The user has configured the following in:

~/projects/hermes_bedrock_agent/.env

bedrock_vlm_model_id=anthropic.claude-sonnet-4-6

The user is suspicious whether the Bedrock VLM API call to Claude Sonnet is actually working correctly. Before parsing the 3 HIGH-priority VLM files, first verify the VLM API call effectiveness.

You must first run a controlled VLM smoke test. Only if the VLM smoke test succeeds, process the 3 HIGH-priority VLM files identified in the R2 report.

============================================================
Phase R2.5 Goal
============================================================

1. Verify that the project can correctly read the VLM model ID from .env.
2. Verify that Bedrock Claude Sonnet VLM call works with a real small image/file input.
3. Verify that the VLM response is meaningful and parseable.
4. If smoke test succeeds, process only the 3 HIGH-priority VLM files identified in the R2 report.
5. Extract business-process evidence relevant to the five target QA questions.
6. Display / report the VLM parsing results clearly for human review.
7. Do not proceed to R3 automatically.

============================================================
Files and Control Documents to Read
============================================================

Please read:

1. .hermes.md
2. docs/task_state.md
3. docs/prompts/phase_r2_parse_quality_check.md
4. data/registry/murata_rebuild_v1_sample_files.jsonl
5. R2 artifacts under:

~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/

Especially check:

- parser_failed.jsonl
- visual_blocks.jsonl
- target_question_evidence_matrix.md
- parse_quality_report.md
- missing_evidence_report.md

Also read project config loading logic:

- src/hermes_bedrock_agent/configs/settings.py
- src/hermes_bedrock_agent/clients/bedrock_client.py
- src/hermes_bedrock_agent/parsers/vlm_parser.py
- src/hermes_bedrock_agent/parsers/image_parser.py

============================================================
Important .env / Config Validation
============================================================

Before calling Bedrock, verify how the project reads VLM model ID.

The .env currently contains:

bedrock_vlm_model_id=anthropic.claude-sonnet-4-6

Please check whether the project expects:

- bedrock_vlm_model_id
- BEDROCK_VLM_MODEL_ID
- VLM_MODEL_ID
- BEDROCK_MODEL_ID
- another settings field

If the current lowercase key is not loaded by pydantic-settings or project config, report it clearly and do not silently use a wrong model.

If necessary, support both lowercase and uppercase variants, but do not modify core code unless required. Prefer reporting the exact env var name expected by the project.

The smoke test report must include:

- loaded VLM model ID
- env var source
- AWS region
- whether Bedrock client initialized successfully
- whether an inference profile is required
- whether invoke_model / converse path is used
- whether image content is passed in the correct multimodal format

============================================================
Allowed Actions
============================================================

Allowed:

1. Read selected files.
2. Read .env and configuration.
3. Run a small Bedrock VLM smoke test.
4. Run VLM only for the 3 HIGH-priority VLM files if smoke test succeeds.
5. Create visual_blocks_r2_5.jsonl.
6. Create VLM quality reports.
7. Display parsed results in Markdown reports.
8. Update docs/task_state.md.

============================================================
Forbidden Actions
============================================================

Forbidden:

1. Do not generate embeddings.
2. Do not write LanceDB.
3. Do not query Neptune.
4. Do not write Neptune.
5. Do not run graph extraction.
6. Do not run QA terminal.
7. Do not proceed to R3 automatically.
8. Do not process all 6 VLM files unless one of the 3 HIGH-priority files is missing, corrupt, or unusable and a replacement is justified.
9. Do not modify core code unless the VLM config cannot be read at all; if code modification is required, explain before and keep the change minimal.
10. Do not continue to VLM parsing if the smoke test fails.

============================================================
Step 1: VLM Smoke Test
============================================================

Perform a minimal VLM smoke test before processing business files.

Smoke test input options, in priority order:

1. Use one small selected HIGH-priority visual file if it is safe and small enough.
2. Otherwise use a small image from the selected sample.
3. Otherwise create a tiny local test image with simple text such as:
   "VLM smoke test: Murata AP workflow"
   and ask the VLM to read the text.

The smoke test prompt should be simple:

"Please describe this image briefly. If there is visible text, extract it. Return JSON with fields: description, extracted_text, confidence."

Expected output must be valid or near-valid JSON.

Record:

- request model id
- input file name
- input mime type
- image size
- response status
- response latency
- response text
- JSON parse result
- whether the result is meaningful

If smoke test fails:

1. Stop.
2. Do not process the 3 HIGH-priority VLM files.
3. Create:
   - docs/murata_rebuild_vlm_smoke_test_report.md
4. Report the likely cause:
   - model ID not loaded
   - wrong env var
   - Bedrock permission issue
   - inference profile required
   - unsupported model ID
   - wrong multimodal request format
   - region mismatch
   - throttling
   - other error

============================================================
Step 2: Identify 3 HIGH-Priority VLM Files
============================================================

From the R2 report and sample registry, identify the 3 HIGH-priority VLM-required files.

For each file, record:

- source_uri
- file_name
- file_type
- why it requires VLM
- related target questions
- expected evidence
- priority

If R2 report does not explicitly list the 3 files, infer them from:

- sample registry
- parser_failed.jsonl
- visual_blocks.jsonl
- target_question_evidence_matrix.md
- parse_quality_report.md

But report the inference clearly.

============================================================
Step 3: VLM Parse Only the 3 HIGH-Priority Files
============================================================

If smoke test succeeds, process only the 3 HIGH-priority VLM files.

For each file, the VLM prompt should extract:

1. Document/page/image description
2. Visible text
3. Business process steps
4. Tables / fields / forms visible in the image
5. Systems involved, such as AP system, OA system, payment system
6. Workflow arrows or dependencies
7. Evidence related to the target QA questions
8. Whether the file supports Q1, Q4, or Q5

The prompt should be evidence-focused, not generic.

For each visual file, ask the VLM to return structured JSON:

{
  "source_uri": "...",
  "file_name": "...",
  "visual_type": "screenshot|diagram|slide|excel|word|unknown",
  "description": "...",
  "visible_text": ["..."],
  "business_process_steps": [
    {
      "step": "...",
      "system": "...",
      "input": "...",
      "output": "...",
      "related_tables": ["..."],
      "key_fields": ["..."]
    }
  ],
  "detected_entities": ["..."],
  "detected_tables": ["..."],
  "detected_fields": ["..."],
  "detected_code_modules": ["..."],
  "detected_relations": [
    {
      "from": "...",
      "to": "...",
      "relation": "generates|depends_on|relates_to|unknown",
      "evidence": "..."
    }
  ],
  "target_question_support": {
    "Q1": "none|weak|medium|strong",
    "Q2": "none|weak|medium|strong",
    "Q3": "none|weak|medium|strong",
    "Q4": "none|weak|medium|strong",
    "Q5": "none|weak|medium|strong"
  },
  "process_chain_coverage": {
    "订单": "covered|partial|missing",
    "对账单": "covered|partial|missing",
    "审批": "covered|partial|missing",
    "付款申请": "covered|partial|missing",
    "支付": "covered|partial|missing",
    "报表": "covered|partial|missing"
  },
  "recommended_r3_usage": "include_as_visual_evidence|summary_only|exclude",
  "confidence": 0.0
}

If the response is not valid JSON, save the raw output and create a normalized best-effort record.

============================================================
Step 4: Display Parsing Results
============================================================

The user wants to see whether the VLM parsing is effective.

Create a human-readable report that displays the parsing results.

The report must include for each processed file:

1. File name
2. Source URI
3. VLM model ID
4. Short description
5. Extracted visible text
6. Extracted process steps
7. Detected tables / fields / systems
8. Which target questions it supports
9. Whether it helps Q1 / Q4 / Q5
10. Recommended R3 usage
11. Raw VLM response excerpt
12. Parsing confidence

Do not only write JSONL. The Markdown report must be readable.

============================================================
Required Outputs
============================================================

Create:

1. docs/murata_rebuild_vlm_smoke_test_report.md

2. ~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/visual_blocks_r2_5.jsonl

3. docs/murata_rebuild_vlm_quality_report.md

4. docs/murata_rebuild_process_chain_evidence_report.md

5. docs/murata_rebuild_vlm_raw_outputs.md or:
   ~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/vlm_raw_outputs_r2_5.jsonl

6. Update docs/murata_rebuild_target_question_evidence_matrix.md if needed.

7. Update docs/task_state.md.

============================================================
R2.5 Quality Gate
============================================================

R2.5 passes only if:

1. VLM smoke test succeeds.
2. The loaded VLM model ID is explicitly reported.
3. The Bedrock VLM response is meaningful.
4. The 3 HIGH-priority VLM files are identified.
5. The 3 HIGH-priority files are processed or failures are clearly explained.
6. visual_blocks_r2_5.jsonl is created.
7. VLM quality report is created.
8. Process chain evidence report is created.
9. Each VLM file is classified as:
   - include_as_visual_evidence
   - summary_only
   - exclude
10. No embeddings, LanceDB writes, Neptune operations, graph extraction, or QA are executed.

If the smoke test fails, R2.5 fails safely and stops.

============================================================
State Update
============================================================

After completing R2.5, update docs/task_state.md:

If R2.5 passes:

- Current Phase: R2.5
- Current Phase Status: completed
- Completed Outputs:
  - docs/murata_rebuild_vlm_smoke_test_report.md
  - visual_blocks_r2_5.jsonl
  - docs/murata_rebuild_vlm_quality_report.md
  - docs/murata_rebuild_process_chain_evidence_report.md
- Latest Findings
- Risks / Issues
- Recommended Next Phase: R3
- Next Phase Prompt: docs/prompts/phase_r3_chunking_quality.md

If R2.5 fails:

- Current Phase: R2.5
- Current Phase Status: failed
- Failure reason
- Recommended action before retry

Then stop and wait for user review.

============================================================
Final Report
============================================================

At the end, output:

1. Whether the VLM smoke test succeeded.
2. Which model ID was actually used.
3. Whether bedrock_vlm_model_id from .env was correctly loaded.
4. Which 3 files were processed.
5. Summary of VLM parsing quality.
6. Whether Q1 / Q4 / Q5 evidence improved.
7. Whether R3 can proceed.
8. Files generated.
9. Any errors or warnings.

Now execute R2.5 only.
