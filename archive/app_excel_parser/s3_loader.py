"""S3 file loader for Excel files."""
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def download_from_s3(s3_uri: str, local_dir: str) -> Path:
    """Download a file from S3 to local directory.
    
    Returns the local path of the downloaded file.
    Raises RuntimeError if download fails.
    """
    local_path = Path(local_dir) / Path(s3_uri).name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    
    if local_path.exists():
        logger.info(f"File already exists locally: {local_path}")
        return local_path
    
    logger.info(f"Downloading from S3: {s3_uri}")
    result = subprocess.run(
        ["aws", "s3", "cp", s3_uri, str(local_path)],
        capture_output=True, text=True, timeout=60
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"S3 download failed: {result.stderr}")
    
    logger.info(f"Downloaded to: {local_path}")
    return local_path
