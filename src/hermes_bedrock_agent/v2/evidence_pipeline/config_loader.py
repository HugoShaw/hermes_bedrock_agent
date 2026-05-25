"""
Config loader — YAML設定ファイルと.envファイルをマージして返す。

Priority order (highest wins):
  1. OS environment variables
  2. .env file
  3. YAML config file defaults
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# .envから読み込む対象のキー一覧
_ENV_KEYS = [
    "S3_BUCKET",
    "S3_RAW_PREFIX",
    "AWS_REGION",
    "BEDROCK_VLM_MODEL_ID",
    "VISION_LLM_MODEL_ID",
    "VISION_LLM_PROVIDER",
    "BEDROCK_TEXT_MODEL_ID",
    "TEXT_LLM_MODEL_ID",
    "TEXT_LLM_PROVIDER",
    "BEDROCK_EMBEDDING_MODEL_ID",
    "EMBEDDING_MODEL_ID",
    "EMBEDDING_PROVIDER",
    "LOG_LEVEL",
    "DRY_RUN",
]


def _load_dotenv_file(env_path: str | Path) -> dict[str, str]:
    """Parse a .env file manually (python-dotenv が無い場合のフォールバック)。"""
    result: dict[str, str] = {}
    path = Path(env_path)
    if not path.exists():
        return result
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            result[key] = value
    return result


def _try_python_dotenv(env_path: str | Path) -> dict[str, str]:
    """python-dotenv が利用可能ならそちらを使う。"""
    try:
        from dotenv import dotenv_values  # type: ignore
        raw = dotenv_values(str(env_path))
        return {k: v for k, v in raw.items() if v is not None}
    except ImportError:
        logger.debug("python-dotenv not installed, falling back to manual parser")
        return _load_dotenv_file(env_path)


def _load_yaml(yaml_path: str | Path) -> dict[str, Any]:
    """Load a YAML config file. Returns empty dict on failure."""
    try:
        import yaml  # type: ignore
        with open(yaml_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data or {}
    except ImportError:
        logger.warning("PyYAML not installed — YAML config will be skipped")
        return {}
    except FileNotFoundError:
        logger.warning("Config file not found: %s", yaml_path)
        return {}
    except Exception as exc:
        logger.error("Failed to load YAML config %s: %s", yaml_path, exc)
        return {}


def _resolve_env(env_file: str | Path | None) -> dict[str, str]:
    """Collect env vars: OS environment overrides .env file."""
    merged: dict[str, str] = {}

    # Step 1: load from .env file
    if env_file is None:
        # Try common default locations
        for candidate in [".env", Path.home() / ".env"]:
            p = Path(candidate)
            if p.exists():
                env_file = p
                break

    if env_file is not None:
        file_values = _try_python_dotenv(env_file)
        merged.update(file_values)
        logger.debug("Loaded %d keys from %s", len(file_values), env_file)

    # Step 2: OS environment overrides .env
    for key in _ENV_KEYS:
        if key in os.environ:
            merged[key] = os.environ[key]

    return merged


def load_config(
    yaml_path: str | Path | None = None,
    env_file: str | Path | None = None,
) -> dict[str, Any]:
    """Load and merge YAML config with environment variables.

    Parameters
    ----------
    yaml_path:
        Path to a YAML configuration file. Optional.
    env_file:
        Path to a .env file. If None, will try `.env` in cwd.

    Returns
    -------
    Merged config dict with a top-level ``env`` sub-dict holding all
    resolved environment variable values.
    """
    config: dict[str, Any] = {}

    # Load YAML base
    if yaml_path is not None:
        config = _load_yaml(yaml_path)
        logger.info("Loaded YAML config from %s", yaml_path)

    # Resolve environment variables
    env_vars = _resolve_env(env_file)

    # Inject env into config["env"] for easy access
    config.setdefault("env", {})
    config["env"].update(env_vars)

    # Convenience shortcuts at the top level (YAML value wins if already set)
    _set_if_absent(config, "dataset", config.get("dataset", "sample_20260519"))
    _set_if_absent(config, "run_id", config.get("run_id", "sample_20260519_evidence_v1"))
    _set_if_absent(config, "output_dir", config.get("output_dir", "data/outputs/sample_20260519_evidence_v1"))

    # Model IDs — env vars override YAML values
    config["bedrock_vlm_model_id"] = (
        env_vars.get("BEDROCK_VLM_MODEL_ID")
        or env_vars.get("VISION_LLM_MODEL_ID")
        or config.get("bedrock_vlm_model_id", "")
    )
    config["bedrock_text_model_id"] = (
        env_vars.get("BEDROCK_TEXT_MODEL_ID")
        or env_vars.get("TEXT_LLM_MODEL_ID")
        or config.get("bedrock_text_model_id", "")
    )
    config["bedrock_embedding_model_id"] = (
        env_vars.get("BEDROCK_EMBEDDING_MODEL_ID")
        or env_vars.get("EMBEDDING_MODEL_ID")
        or config.get("bedrock_embedding_model_id", "")
    )
    config["aws_region"] = (
        env_vars.get("AWS_REGION")
        or config.get("aws_region", "ap-northeast-1")
    )
    config["s3_bucket"] = (
        env_vars.get("S3_BUCKET")
        or _nested_get(config, "source", "s3_bucket", default="")
    )
    config["s3_raw_prefix"] = (
        env_vars.get("S3_RAW_PREFIX")
        or _nested_get(config, "source", "s3_prefix", default="")
    )

    return config


def _set_if_absent(d: dict[str, Any], key: str, value: Any) -> None:
    if key not in d:
        d[key] = value


def _nested_get(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur
