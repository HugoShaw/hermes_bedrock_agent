#!/usr/bin/env python3
"""Run the Excel Parse Pipeline.

Usage:
    python scripts/run_excel_parse_pipeline.py
    python scripts/run_excel_parse_pipeline.py --input-prefix "サンプル20260519/"
    python scripts/run_excel_parse_pipeline.py --output-dir data/outputs/excel_parse_pipeline/sample_20260519/
"""
import sys
import os
import argparse
from pathlib import Path


# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Load .env
env_path = project_root / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value


def main():
    parser = argparse.ArgumentParser(description="Excel Parse Pipeline")
    parser.add_argument("--s3-bucket", default=os.getenv("S3_BUCKET", "s3-hulftchina-rd"),
                        help="S3 bucket name")
    parser.add_argument("--input-prefix", default="サンプル20260519/",
                        help="S3 input prefix")
    parser.add_argument("--output-dir",
                        default="data/outputs/excel_parse_pipeline/sample_20260519/",
                        help="Local output directory")
    parser.add_argument("--output-prefix", default="output/sample_20260519/excel_parse_pipeline/",
                        help="S3 output prefix")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "ap-northeast-1"),
                        help="AWS region")
    parser.add_argument("--model-id", default=os.getenv("BEDROCK_MODEL_ID", ""),
                        help="Bedrock model ID for parse plan generation")
    parser.add_argument("--vlm-model-id", default=os.getenv("BEDROCK_VLM_MODEL_ID", ""),
                        help="Bedrock VLM model ID")
    parser.add_argument("--no-s3-sync", action="store_true",
                        help="Skip S3 output sync")

    args = parser.parse_args()

    from app.excel_parse_pipeline.config import PipelineConfig
    from app.excel_parse_pipeline.pipeline import run_pipeline

    config = PipelineConfig(
        s3_bucket=args.s3_bucket,
        s3_input_prefix=args.input_prefix,
        s3_output_prefix="" if args.no_s3_sync else args.output_prefix,
        aws_region=args.region,
    )
    # Override output dir if specified
    if args.output_dir:
        config.output_dir = Path(args.output_dir)
        config.downloads_dir = config.output_dir / "downloads"
    # Override models if specified
    if args.model_id:
        config.bedrock_text_model = args.model_id
    if args.vlm_model_id:
        config.bedrock_vlm_model = args.vlm_model_id

    result = run_pipeline(config)

    print("\n" + "=" * 60)
    print("PIPELINE RESULT")
    print("=" * 60)
    print(f"  Status: {result['status']}")
    print(f"  Duration: {result['duration_seconds']:.1f}s")
    print(f"  Output: {result['output_dir']}")
    print(f"  S3 synced: {result['s3_synced']}")
    print(f"  Issues: {result['issue_count']}")
    print(f"  Human review: {result['human_review_count']}")
    
    stats = result.get("statistics", {})
    if stats:
        print("\n  Statistics:")
        for key, value in stats.items():
            print(f"    {key}: {value}")

    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
