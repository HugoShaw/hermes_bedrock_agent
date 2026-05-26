"""
File classifier for the semantic map workflow.

Assigns a ``source_type`` label and a numeric ``usefulness_score`` (0–1) to
each file based on its extension, path components, and filename patterns.
Rules are applied in priority order; the first matching rule wins.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source-type constants
# ---------------------------------------------------------------------------
ST_DDL = "ddl"
ST_SOURCE_CODE = "source_code"
ST_SQL_MAPPER = "sql_mapper"
ST_ENUM_OR_CONSTANT = "enum_or_constant"
ST_USER_MANUAL = "user_manual"
ST_REQUIREMENT_DOC = "requirement_doc"
ST_DESIGN_DOC = "design_doc"
ST_API_DOC = "api_doc"
ST_TEST_CASE = "test_case"
ST_UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# Usefulness score table
# ---------------------------------------------------------------------------
_USEFULNESS: dict[str, float] = {
    ST_DDL: 1.0,
    ST_SOURCE_CODE: 0.9,
    ST_SQL_MAPPER: 0.85,
    ST_USER_MANUAL: 0.8,
    ST_API_DOC: 0.8,
    ST_DESIGN_DOC: 0.75,
    ST_REQUIREMENT_DOC: 0.75,
    ST_ENUM_OR_CONSTANT: 0.7,
    ST_TEST_CASE: 0.65,
    ST_UNKNOWN: 0.3,
}

# ---------------------------------------------------------------------------
# Extension sets
# ---------------------------------------------------------------------------
_SOURCE_CODE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".java", ".py", ".js", ".ts", ".tsx", ".jsx",
        ".cs", ".cpp", ".c", ".h", ".hpp",
        ".go", ".rb", ".php", ".swift", ".kt", ".scala",
        ".rs",
    }
)

_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".md", ".txt", ".html", ".htm"}
)

# ---------------------------------------------------------------------------
# Compiled regex patterns for filename matching (case-insensitive)
# ---------------------------------------------------------------------------
_RE_MAPPER_FILE = re.compile(r"(?i)(Mapper|DAO|sql[\w]*)\.xml$")
_RE_ENUM_CONST = re.compile(r"(?i)(Const(ants?)?|Enum|KBN)")
_RE_USER_MANUAL = re.compile(r"(?i)(manual|マニュアル|guide|howto|how[-_]?to)")
_RE_REQUIREMENT = re.compile(r"(?i)(要件|requirements?|req[-_])")
_RE_DESIGN = re.compile(r"(?i)(設計|design|spec(ification)?)")
_RE_API_DOC = re.compile(r"(?i)(api|swagger|openapi)")
# "spec" alone is excluded here because it also describes design specifications.
# It is captured by _RE_DESIGN instead.
_RE_TEST = re.compile(r"(?i)(test|テスト)")

# Path component patterns (matched against individual directory components)
_RE_PATH_MANUAL = re.compile(r"(?i)(操作手册|manual|マニュアル|guide)")
_RE_PATH_DESIGN = re.compile(r"(?i)(文書|設計|design|spec|architecture)")
_RE_PATH_REQ = re.compile(r"(?i)(要件|requirements?|req)")
_RE_PATH_API = re.compile(r"(?i)(api|swagger|openapi)")
_RE_PATH_TEST = re.compile(r"(?i)(test|tests|テスト)")

# SQL DDL detection (matches first 4 kB of content when present)
_RE_DDL = re.compile(r"(?im)^\s*CREATE\s+TABLE\b")


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _path_components(file_info: dict) -> list[str]:
    """Return lower-cased path components (directories + stem) for *file_info*."""
    rel = file_info.get("rel_path") or file_info.get("path") or file_info.get("s3_key", "")
    return [part.lower() for part in Path(rel).parts]


def _name(file_info: dict) -> str:
    return file_info.get("name") or Path(
        file_info.get("path") or file_info.get("s3_key", "unknown")
    ).name


def _ext(file_info: dict) -> str:
    return file_info.get("ext") or Path(_name(file_info)).suffix.lower()


def _first_bytes(file_info: dict, nbytes: int = 4096) -> str:
    """Read the first *nbytes* of the local file if available."""
    local_path = file_info.get("path")
    if not local_path:
        return ""
    try:
        with open(local_path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read(nbytes)
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_file(file_info: dict) -> dict:
    """Classify a file and return *file_info* augmented with classification keys.

    The returned dict extends *file_info* with:
      - ``source_type``         – one of the ``ST_*`` constants
      - ``usefulness_score``    – float in [0.0, 1.0]
      - ``classification_reason`` – human-readable explanation

    Classification is purely based on filename/path patterns and (when a local
    ``path`` is present) a small prefix read from the file content.  No full
    file parse is performed.

    Parameters
    ----------
    file_info:
        Dict as returned by ``list_local_files`` or ``list_s3_files``.

    Returns
    -------
    dict
        Shallow copy of *file_info* with classification fields added.
    """
    result: dict[str, Any] = dict(file_info)
    name = _name(file_info)
    ext = _ext(file_info)
    components = _path_components(file_info)
    stem = Path(name).stem

    # ------------------------------------------------------------------
    # Rule 1: DDL  (.sql file that starts with CREATE TABLE)
    # ------------------------------------------------------------------
    if ext == ".sql":
        snippet = _first_bytes(file_info, 4096)
        if _RE_DDL.search(snippet) or _RE_DDL.search(name):
            return _tag(result, ST_DDL, "SQL file contains CREATE TABLE statement")
        # Plain SQL that doesn't have CREATE TABLE – still treat as source_code
        return _tag(result, ST_SOURCE_CODE, "SQL script (no DDL detected)")

    # ------------------------------------------------------------------
    # Rule 2: MyBatis / SQL mapper XML
    # ------------------------------------------------------------------
    if ext == ".xml" and _RE_MAPPER_FILE.search(name):
        return _tag(result, ST_SQL_MAPPER, "XML mapper file (MyBatis/DAO pattern)")

    # ------------------------------------------------------------------
    # Rule 3: Enum / Constant file
    # ------------------------------------------------------------------
    if _RE_ENUM_CONST.search(stem):
        return _tag(result, ST_ENUM_OR_CONSTANT, "Enum or constant definition file")

    # ------------------------------------------------------------------
    # Rule 4: Test file (path component or filename)
    # ------------------------------------------------------------------
    path_is_test = any(_RE_PATH_TEST.search(c) for c in components[:-1])
    name_is_test = _RE_TEST.search(stem) is not None
    if path_is_test or name_is_test:
        return _tag(
            result,
            ST_TEST_CASE,
            "Test file (path contains test/ or name matches test pattern)",
        )

    # ------------------------------------------------------------------
    # Rule 5: Source code
    # ------------------------------------------------------------------
    if ext in _SOURCE_CODE_EXTENSIONS:
        return _tag(result, ST_SOURCE_CODE, f"Source code file ({ext})")

    # ------------------------------------------------------------------
    # Rule 6: API documentation
    # ------------------------------------------------------------------
    path_is_api = any(_RE_PATH_API.search(c) for c in components[:-1])
    name_is_api = _RE_API_DOC.search(stem) is not None
    if path_is_api or name_is_api:
        return _tag(result, ST_API_DOC, "API documentation (swagger/openapi pattern)")

    # ------------------------------------------------------------------
    # Rule 7: User manual
    # ------------------------------------------------------------------
    path_is_manual = any(_RE_PATH_MANUAL.search(c) for c in components[:-1])
    name_is_manual = _RE_USER_MANUAL.search(stem) is not None
    if path_is_manual or name_is_manual:
        return _tag(result, ST_USER_MANUAL, "User manual / guide document")

    # ------------------------------------------------------------------
    # Rule 8: Requirement document
    # ------------------------------------------------------------------
    path_is_req = any(_RE_PATH_REQ.search(c) for c in components[:-1])
    name_is_req = _RE_REQUIREMENT.search(stem) is not None
    if path_is_req or name_is_req:
        return _tag(result, ST_REQUIREMENT_DOC, "Requirements document")

    # ------------------------------------------------------------------
    # Rule 9: Design document
    # ------------------------------------------------------------------
    path_is_design = any(_RE_PATH_DESIGN.search(c) for c in components[:-1])
    name_is_design = _RE_DESIGN.search(stem) is not None
    if path_is_design or name_is_design:
        return _tag(result, ST_DESIGN_DOC, "Design / specification document")

    # ------------------------------------------------------------------
    # Rule 10: Document type with no further pattern match
    # ------------------------------------------------------------------
    if ext in _DOCUMENT_EXTENSIONS:
        return _tag(result, ST_UNKNOWN, f"Document with no matching pattern ({ext})")

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------
    return _tag(result, ST_UNKNOWN, f"No classification rule matched (ext={ext!r})")


def _tag(file_info: dict, source_type: str, reason: str) -> dict:
    """Attach classification keys to *file_info* and return it."""
    file_info["source_type"] = source_type
    file_info["usefulness_score"] = _USEFULNESS.get(source_type, 0.3)
    file_info["classification_reason"] = reason
    logger.debug(
        "classify_file: %s -> %s (%.2f) – %s",
        file_info.get("name", "?"),
        source_type,
        file_info["usefulness_score"],
        reason,
    )
    return file_info
