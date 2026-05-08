# doc-analyze: Replace Bedrock invoke_model with Hermes Agent as Analyst

**Goal:** Instead of calling Bedrock invoke_model directly, the app should download S3 files to a temp dir, then spawn a `hermes chat -q` subprocess. Hermes uses its own file/terminal tools to read each document iteratively, reason about hierarchical and cross-system relationships, and output a final structured JSON block. The app parses that JSON and passes it to the unchanged `mermaid_renderer.py`.

**Architecture:**
- `analyze_directory()` in `analyzer.py` downloads files to a temp dir (existing logic, keep as-is).
- A new function `_call_hermes_agent(tmpdir, file_paths)` replaces `_call_bedrock()`.
- It builds a self-contained prompt instructing Hermes to read each file via its file tools, reason, cross-reference, and emit a final JSON block wrapped in `<RESULT>...</RESULT>` sentinel tags.
- It runs `hermes chat -q "<prompt>" -t file` as a subprocess (with `--quiet` / `-Q` to suppress banner/spinner noise), captures stdout, and extracts the JSON from between the sentinel tags.
- `_parse_json_robust()` is reused on the extracted content.
- `analyze_directory()` signature gets a new optional `use_hermes: bool = True` flag. When True it uses `_call_hermes_agent`. When False it falls back to the old `_call_bedrock` path (kept for backward compat). Default is True.
- `cmd.py` gets a `--use-bedrock` flag (default: off) that passes `use_hermes=not use_bedrock` to `analyze_directory()`.

**Why sentinel tags?**
Hermes produces conversational output mixed with tool-call traces. We need a reliable way to extract ONLY the final JSON from the full stdout. Using `<RESULT>...</RESULT>` tags is the most reliable approach — the prompt instructs Hermes to wrap its final JSON in them, and the parser strips everything outside.

**Tech Stack:** Python stdlib `subprocess`, existing `extract_text`, existing `_parse_json_robust`, `hermes` CLI.

---

## Task 1: Add `_call_hermes_agent()` to `analyzer.py`

**Objective:** Add a function that writes files to a temp dir (they are already there from the download step), builds a Hermes prompt, spawns `hermes chat -q`, and returns the raw text output.

**Files:**
- Modify: `src/hermes_bedrock_agent/doc_analyze/analyzer.py`

**Step 1: Add the import** — add `import subprocess` and `import shutil` at the top imports block.

**Step 2: Add the Hermes prompt builder**

Add this function after `_build_prompt()`:

```python
def _build_hermes_prompt(file_paths: list[str]) -> str:
    """Build a self-contained prompt for `hermes chat -q` to read & analyze files."""
    file_list = "\n".join(f"  - {p}" for p in file_paths)
    return f"""You are an expert enterprise architect. Your task is to analyze the following company document files and identify organizational and technical relationships.

FILES TO ANALYZE:
{file_list}

INSTRUCTIONS:
1. Use your file reading tools to read EACH file listed above, one by one.
2. After reading all files, reason about:
   a. HIERARCHICAL relationships: company → subsidiary → department → team, or parent system → subsystem → module
   b. CROSS-SYSTEM / CROSS-SUBSIDIARY relationships: data flows, API integrations, business processes that span entities, shared services
3. Identify ALL entities (companies, subsidiaries, departments, teams, systems, modules) mentioned across ALL files.
4. Identify ALL relationships between those entities.

OUTPUT FORMAT — you MUST end your response with this exact structure (replace the example with your actual findings):

<RESULT>
{{
  "summary": "one or two sentence summary of what you found",
  "entities": [
    {{"id": "unique_snake_case_id", "name": "Display Name", "type": "company|subsidiary|department|system|module|team|other", "description": "brief description"}}
  ],
  "relationships": [
    {{"from_id": "entity_id", "to_id": "entity_id", "type": "hierarchy|integration|data_flow|business_process|other", "label": "relationship label", "direction": "uni|bi"}}
  ]
}}
</RESULT>

Start by reading the files now, then produce your analysis."""
```

**Step 3: Add `_call_hermes_agent()`**

Add this function after `_call_bedrock()`:

```python
def _call_hermes_agent(file_paths: list[str], timeout: int = 300) -> str:
    """Spawn `hermes chat -q` with file-reading tools to analyze documents.

    Returns the raw stdout from Hermes. The caller extracts the <RESULT>…</RESULT> block.
    """
    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        raise RuntimeError(
            "hermes CLI not found on PATH. Install Hermes Agent or use --use-bedrock flag."
        )

    prompt = _build_hermes_prompt(file_paths)

    try:
        proc = subprocess.run(
            [hermes_bin, "chat", "-q", prompt, "-Q", "-t", "file"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=None,  # inherit full environment including AWS_ vars and HERMES config
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Hermes agent timed out after {timeout}s. Try increasing --hermes-timeout or use --use-bedrock."
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to spawn hermes: {exc}") from exc

    # Hermes may write errors to stderr; surface them if stdout is empty
    if not proc.stdout.strip() and proc.returncode != 0:
        raise RuntimeError(
            f"Hermes exited with code {proc.returncode}. stderr: {proc.stderr[:500]}"
        )

    return proc.stdout
```

**Step 4: Add `_extract_result_block()` helper**

Add after `_parse_json_robust()`:

```python
def _extract_result_block(text: str) -> str:
    """Extract content between <RESULT> and </RESULT> tags from Hermes output.

    Falls back to the full text if tags are not found (so _parse_json_robust still runs).
    """
    import re as _re
    m = _re.search(r"<RESULT>\s*([\s\S]*?)\s*</RESULT>", text)
    if m:
        return m.group(1).strip()
    # Fallback: try the whole output
    return text
```

**Step 5: Update `analyze_directory()` signature and body**

Change the signature to add `use_hermes: bool = True` and `hermes_timeout: int = 300`:

```python
def analyze_directory(
    bucket: str,
    prefix: str,
    region: str,
    model_id: str,
    max_chars_per_file: int = 8000,
    use_hermes: bool = True,
    hermes_timeout: int = 300,
) -> AnalysisResult:
```

Change step 3 from:
```python
    # 3. Build prompt and call Bedrock
    prompt = _build_prompt(file_contents)
    raw_response = _call_bedrock(prompt, model_id, region)
```

to:
```python
    # 3. Call analyst (Hermes agent or Bedrock)
    if use_hermes:
        # Write extracted texts to temp files for Hermes to read
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_paths: list[str] = []
            for filename, text in file_contents.items():
                tmp_path = str(Path(tmpdir) / filename) + ".txt"
                Path(tmp_path).write_text(text, encoding="utf-8")
                tmp_paths.append(tmp_path)
            raw_response = _call_hermes_agent(tmp_paths, timeout=hermes_timeout)
        raw_response = _extract_result_block(raw_response)
    else:
        prompt = _build_prompt(file_contents)
        raw_response = _call_bedrock(prompt, model_id, region)
```

**Verify:** Run the module's import:
```bash
cd ~/projects/hermes_bedrock_agent
PYTHONPATH=src .venv/bin/python -c "from hermes_bedrock_agent.doc_analyze.analyzer import analyze_directory; print('OK')"
```
Expected: `OK`

---

## Task 2: Add `--use-bedrock` flag to `cmd.py`

**Objective:** Let the user opt out of Hermes and fall back to the old Bedrock path from the CLI.

**Files:**
- Modify: `src/hermes_bedrock_agent/doc_analyze/cmd.py`

**Step 1:** In the `run_cmd()` function, add a new option parameter after `max_chars`:

```python
    use_bedrock: bool = typer.Option(False, "--use-bedrock", help="Use direct Bedrock invoke_model instead of Hermes agent."),
    hermes_timeout: int = typer.Option(300, "--hermes-timeout", help="Seconds to wait for Hermes agent to complete analysis."),
```

**Step 2:** Update the `analyze_directory()` call to pass the new flags:

```python
            result = analyze_directory(
                bucket=resolved_bucket,
                prefix=prefix,
                region=region,
                model_id=resolved_model,
                max_chars_per_file=max_chars,
                use_hermes=not use_bedrock,
                hermes_timeout=hermes_timeout,
            )
```

**Step 3:** Update the info header printed before analysis to show the analyst mode:

```python
    analyst = f"Bedrock ({resolved_model})" if use_bedrock else "Hermes Agent"
    rprint(f"  Analyst: {analyst}")
```
Add this line after the `rprint(f"  Model  : {resolved_model}")` line.

**Verify:** Check CLI help shows new flags:
```bash
cd ~/projects/hermes_bedrock_agent
PYTHONPATH=src .venv/bin/python -m hermes_bedrock_agent.main doc-analyze run --help
```
Expected: see `--use-bedrock` and `--hermes-timeout` in the output.

---

## Task 3: Fix temp file naming collision

**Objective:** The temp file names in task 1 step 5 may collide if two files from different S3 paths have the same basename. Use the index as prefix.

**Files:**
- Modify: `src/hermes_bedrock_agent/doc_analyze/analyzer.py`

In the Hermes branch of `analyze_directory()`, change:

```python
            for filename, text in file_contents.items():
                tmp_path = str(Path(tmpdir) / filename) + ".txt"
```

to:

```python
            for i, (filename, text) in enumerate(file_contents.items()):
                safe_name = f"{i:03d}_{filename}"
                tmp_path = str(Path(tmpdir) / safe_name)
                if not tmp_path.endswith(".txt"):
                    tmp_path += ".txt"
```

And update `tmp_paths.append(tmp_path)` accordingly.

---

## Task 4: Update upload_cmd to pass through new flags

**Objective:** The `upload` command auto-invokes `run_cmd` — it needs to pass `use_bedrock=False` and `hermes_timeout=300` so the defaults work without breaking.

**Files:**
- Modify: `src/hermes_bedrock_agent/doc_analyze/cmd.py`

In `upload_cmd()`, update the `typer.get_current_context().invoke(run_cmd, ...)` call to add:

```python
            use_bedrock=False,
            hermes_timeout=300,
```

---

## Final Verification

```bash
cd ~/projects/hermes_bedrock_agent
# Import test
PYTHONPATH=src .venv/bin/python -c "
from hermes_bedrock_agent.doc_analyze.analyzer import analyze_directory, _call_hermes_agent, _extract_result_block, _build_hermes_prompt
print('All imports OK')
print('_build_hermes_prompt sample:', _build_hermes_prompt(['/tmp/test.txt'])[:80])
"

# CLI help test
PYTHONPATH=src .venv/bin/python -m hermes_bedrock_agent.main doc-analyze run --help
```
