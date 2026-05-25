# VLM Smoke Test Report — Phase R2.5

**Date:** 2026-05-15
**Run ID:** murata_rebuild_v1
**Phase:** R2.5 — VLM API Smoke Test + Narrow VLM Parsing

---

## 1. Config Validation

### .env Configuration

| Key | Value | Status |
|-----|-------|--------|
| `BEDROCK_VLM_MODEL_ID` | `anthropic.claude-sonnet-4-6` | Present in .env |
| `AWS_REGION` | `ap-northeast-1` | OK |
| `BEDROCK_MODEL_ID` | `apac.anthropic.claude-sonnet-4-20250514-v1:0` | OK (general model) |

### Config Loading Issue Identified

**CRITICAL FINDING:** The .env variable `BEDROCK_VLM_MODEL_ID` is **NOT loaded** by the project's pydantic-settings configuration.

- `settings.py` `LLMSettings` uses `env_mapping` with keys:
  - `vision_model_id` ← `VISION_LLM_MODEL_ID` (NOT `BEDROCK_VLM_MODEL_ID`)
  - `text_model_id` ← `TEXT_LLM_MODEL_ID` (NOT `BEDROCK_TEXT_MODEL_ID`)
- Neither `VISION_LLM_MODEL_ID` nor `TEXT_LLM_MODEL_ID` is set in `.env`
- `vlm_parser.py` has hardcoded `DEFAULT_VLM_MODEL = "anthropic.claude-sonnet-4-20250514-v1:0"`
- The bare model ID `anthropic.claude-sonnet-4-6` requires an inference profile prefix in `ap-northeast-1`

### Inference Profile Resolution

| Bare Model ID | Available Profiles | Selected |
|---|---|---|
| `anthropic.claude-sonnet-4-6` | `jp.anthropic.claude-sonnet-4-6` (ACTIVE) | ✅ Used |
| | `global.anthropic.claude-sonnet-4-6` (ACTIVE) | Available |
| | `apac.anthropic.claude-sonnet-4-6` | NOT available |

**Resolution:** Used `jp.anthropic.claude-sonnet-4-6` for all VLM calls in R2.5.

---

## 2. Smoke Test Results

| Parameter | Value |
|-----------|-------|
| **Model ID (raw)** | `anthropic.claude-sonnet-4-6` |
| **Model ID (resolved)** | `jp.anthropic.claude-sonnet-4-6` |
| **Env var source** | `BEDROCK_VLM_MODEL_ID` from .env (manually loaded) |
| **AWS Region** | `ap-northeast-1` |
| **API** | `converse` (Bedrock Converse API, multimodal) |
| **Inference profile required** | Yes — bare ID fails with ValidationException |
| **Image format** | PNG, 400×200, 6,881 bytes |
| **Request format** | Converse API with `image.source.bytes` |

### Smoke Test Input

Generated a test image containing:
```
VLM Smoke Test
Murata AP Workflow
JOURNAL_BASE -> RECEIVING_JOURNAL
-> PAYMENT_REQ (STATUS: 1-5)
2026-05-15 R2.5 Test
```

### Smoke Test Output

| Metric | Value |
|--------|-------|
| **Status** | ✅ SUCCESS |
| **Latency** | 5.62s |
| **Stop reason** | end_turn |
| **Input tokens** | 159 |
| **Output tokens** | 162 |
| **JSON parseable** | ✅ Yes |
| **Response meaningful** | ✅ Yes |
| **Confidence** | 0.98 |

### Extracted Response

```json
{
  "description": "A simple text-based interface or document showing a VLM Smoke Test result for a Murata AP Workflow, displaying journal and payment request status information with a version/date stamp.",
  "extracted_text": {
    "title": "VLM Smoke Test",
    "link": "Murata AP Workflow",
    "line1": "JOURNAL_BASE -> RECEIVING_JOURNAL",
    "line2": "-> PAYMENT_REQ (STATUS: 1-5)",
    "footer": "2026-05-15 R2.5 Test"
  },
  "confidence": 0.98
}
```

**VERDICT: SMOKE TEST PASS**

The VLM correctly read all 5 text lines, returned valid JSON, and identified the domain-specific content (journal/payment entities).

---

## 3. Recommendations for Core Code

Before R3, consider updating the project config to properly load VLM model settings:

1. **Option A (minimal):** Add `BEDROCK_VLM_MODEL_ID` to `LLMSettings.env_mapping`
2. **Option B (better):** Align `.env` variable names with what pydantic-settings expects:
   - `VISION_LLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6`
3. **Always** store inference-profile-prefixed model IDs in `.env` for `ap-northeast-1`

These changes are **deferred to a later phase** — R2.5 works with direct env var loading.
