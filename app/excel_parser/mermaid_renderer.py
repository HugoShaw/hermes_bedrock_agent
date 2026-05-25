"""Mermaid renderer - converts .mmd files to SVG using mermaid-cli."""
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def render_mermaid_to_svg(mmd_path: str, svg_path: str) -> bool:
    """Render a .mmd file to .svg using mmdc.
    
    Returns True if rendering succeeded.
    """
    svg_dir = Path(svg_path).parent
    svg_dir.mkdir(parents=True, exist_ok=True)
    
    # Try mmdc first
    mmdc_path = _find_mmdc()
    if mmdc_path:
        return _render_with_mmdc(mmdc_path, mmd_path, svg_path)
    
    # Try npx fallback
    return _render_with_npx(mmd_path, svg_path)


def _find_mmdc() -> str | None:
    """Find mmdc in PATH."""
    result = subprocess.run(
        ["which", "mmdc"], capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _render_with_mmdc(mmdc_path: str, mmd_path: str, svg_path: str) -> bool:
    """Render using local mmdc installation."""
    # Check for puppeteer config - look in project root
    project_root = Path(__file__).parent.parent.parent
    puppeteer_config = project_root / "puppeteer-config.json"
    
    cmd = [mmdc_path, "-i", mmd_path, "-o", svg_path, "-w", "4000", "-H", "3000"]
    
    if puppeteer_config.exists():
        cmd.extend(["-p", str(puppeteer_config)])
    
    logger.info(f"Rendering SVG: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    
    if result.returncode == 0 and Path(svg_path).exists():
        size = Path(svg_path).stat().st_size
        logger.info(f"  SVG rendered: {svg_path} ({size} bytes)")
        return True
    else:
        logger.warning(f"  mmdc failed: {result.stderr}")
        return False


def _render_with_npx(mmd_path: str, svg_path: str) -> bool:
    """Fallback: render using npx @mermaid-js/mermaid-cli."""
    cmd = [
        "npx", "-y", "@mermaid-js/mermaid-cli",
        "-i", mmd_path, "-o", svg_path
    ]
    
    logger.info(f"Trying npx fallback: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and Path(svg_path).exists():
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    logger.warning("Mermaid SVG rendering unavailable (no mmdc or npx)")
    return False
