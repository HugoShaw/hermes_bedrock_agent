"""SVG renderer: uses mmdc (Mermaid CLI) to render .mmd to .svg."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SVGRenderResult:
    """Result of an SVG render attempt."""

    def __init__(self):
        self.success: bool = False
        self.svg_path: Optional[Path] = None
        self.svg_size: int = 0
        self.command_used: str = ""
        self.exit_code: int = -1
        self.stderr: str = ""
        self.html_fallback_path: Optional[Path] = None


class SVGRenderer:
    """Render Mermaid .mmd files to SVG using mmdc."""

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path.cwd()

    def render(self, mmd_path: Path, output_path: Path) -> SVGRenderResult:
        """Render a .mmd file to SVG.

        Tries multiple approaches to find and use mmdc:
        1. System mmdc
        2. Local node_modules mmdc
        3. Install via npm if needed
        4. Retry with puppeteer-config if sandbox error

        Returns SVGRenderResult with status information.
        """
        result = SVGRenderResult()

        if not mmd_path.exists():
            result.stderr = f"Mermaid source file not found: {mmd_path}"
            logger.error(result.stderr)
            return result

        # Find mmdc
        mmdc_path = self._find_mmdc()
        if not mmdc_path:
            mmdc_path = self._try_install_mmdc()

        if not mmdc_path:
            result.stderr = "mmdc not found and could not be installed. Need node/npm."
            logger.error(result.stderr)
            self._generate_html_fallback(mmd_path, output_path, result)
            return result

        # Check if puppeteer config already exists in project root
        existing_config = self.project_root / "puppeteer-config.json"
        initial_extra_args = None
        if existing_config.exists():
            initial_extra_args = ["-p", str(existing_config)]

        # Try rendering (with existing puppeteer config if present)
        success = self._try_render(mmdc_path, mmd_path, output_path, result, extra_args=initial_extra_args)

        if not success and ("sandbox" in result.stderr.lower() or "could not find chrome" in result.stderr.lower()):
            # Retry with puppeteer config (creates/updates it with correct Chrome path)
            logger.info("Chrome/sandbox error detected, retrying with puppeteer config")
            puppeteer_config = self._create_puppeteer_config()
            success = self._try_render(
                mmdc_path, mmd_path, output_path, result,
                extra_args=["-p", str(puppeteer_config)]
            )

        if success and output_path.exists():
            result.success = True
            result.svg_path = output_path
            result.svg_size = output_path.stat().st_size
            logger.info(f"SVG rendered successfully: {output_path} ({result.svg_size} bytes)")
        else:
            # Generate HTML fallback
            self._generate_html_fallback(mmd_path, output_path, result)

        return result

    def _find_mmdc(self) -> Optional[str]:
        """Find mmdc executable."""
        # 1. System mmdc
        mmdc = shutil.which("mmdc")
        if mmdc:
            logger.info(f"Found system mmdc: {mmdc}")
            return mmdc

        # 2. Local node_modules
        local_mmdc = self.project_root / "node_modules" / ".bin" / "mmdc"
        if local_mmdc.exists():
            logger.info(f"Found local mmdc: {local_mmdc}")
            return str(local_mmdc)

        return None

    def _try_install_mmdc(self) -> Optional[str]:
        """Try to install mmdc via npm."""
        # Check if node/npm available
        if not shutil.which("node") or not shutil.which("npm"):
            logger.warning("node/npm not available, cannot install mmdc")
            return None

        try:
            logger.info("Installing @mermaid-js/mermaid-cli locally...")
            result = subprocess.run(
                ["npm", "install", "-D", "@mermaid-js/mermaid-cli"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                local_mmdc = self.project_root / "node_modules" / ".bin" / "mmdc"
                if local_mmdc.exists():
                    logger.info(f"Installed mmdc: {local_mmdc}")
                    return str(local_mmdc)
            else:
                logger.warning(f"npm install failed: {result.stderr}")
        except Exception as e:
            logger.warning(f"Failed to install mmdc: {e}")

        return None

    def _try_render(
        self, mmdc_path: str, mmd_path: Path, output_path: Path,
        result: SVGRenderResult, extra_args: Optional[list] = None
    ) -> bool:
        """Attempt to render with mmdc."""
        cmd = [mmdc_path, "-i", str(mmd_path), "-o", str(output_path), "-w", "4000"]
        if extra_args:
            cmd.extend(extra_args)

        result.command_used = " ".join(cmd)
        logger.info(f"Running: {result.command_used}")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.project_root),
            )
            result.exit_code = proc.returncode
            result.stderr = proc.stderr

            if proc.returncode == 0 and output_path.exists():
                return True
            else:
                logger.warning(f"mmdc failed (exit={proc.returncode}): {proc.stderr[:500]}")
                return False
        except subprocess.TimeoutExpired:
            result.stderr = "mmdc timed out (60s)"
            result.exit_code = -1
            logger.error(result.stderr)
            return False
        except Exception as e:
            result.stderr = str(e)
            result.exit_code = -1
            logger.error(f"mmdc execution error: {e}")
            return False

    def _create_puppeteer_config(self) -> Path:
        """Create puppeteer config for no-sandbox mode with correct chrome path."""
        config = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}

        # Find the actual Chrome/headless-shell in puppeteer cache
        chrome_exec = self._find_chrome_executable()
        if chrome_exec:
            config["executablePath"] = chrome_exec

        config_path = self.project_root / "puppeteer-config.json"
        config_path.write_text(json.dumps(config, indent=2))
        return config_path

    def _find_chrome_executable(self) -> Optional[str]:
        """Find Chrome or chrome-headless-shell in puppeteer cache."""
        cache_dir = Path.home() / ".cache" / "puppeteer"
        if not cache_dir.exists():
            return None

        # Check chrome-headless-shell first (lighter)
        for subdir in ("chrome-headless-shell", "chrome"):
            base = cache_dir / subdir
            if not base.exists():
                continue
            # Find latest version directory
            versions = sorted(base.iterdir(), reverse=True)
            for version_dir in versions:
                # Look for the executable
                for candidate in version_dir.rglob("chrome-headless-shell"):
                    if candidate.is_file():
                        return str(candidate)
                for candidate in version_dir.rglob("chrome"):
                    if candidate.is_file() and "driver" not in candidate.name:
                        return str(candidate)
        return None

    def _generate_html_fallback(
        self, mmd_path: Path, svg_output_path: Path, result: SVGRenderResult
    ) -> None:
        """Generate HTML fallback when SVG rendering fails."""
        mmd_content = mmd_path.read_text(encoding="utf-8")
        html_path = svg_output_path.with_suffix(".html")

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Flowchart Preview (SVG render failed)</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
</head>
<body>
    <h1>Flowchart Preview</h1>
    <p style="color:red;">Note: SVG rendering failed. This is a browser-based preview.</p>
    <p>Error: {result.stderr[:200]}</p>
    <div class="mermaid">
{mmd_content}
    </div>
    <script>mermaid.initialize({{startOnLoad: true}});</script>
</body>
</html>"""

        html_path.write_text(html, encoding="utf-8")
        result.html_fallback_path = html_path
        logger.info(f"HTML fallback saved: {html_path}")
