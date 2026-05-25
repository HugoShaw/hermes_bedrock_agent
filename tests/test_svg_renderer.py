"""Tests for SVG renderer."""

import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from flowchart_to_mermaid.renderers.svg_renderer import SVGRenderer, SVGRenderResult


@pytest.fixture
def sample_mmd(tmp_path):
    """Create a sample .mmd file."""
    mmd_file = tmp_path / "test.mmd"
    mmd_file.write_text(
        'flowchart TD\n    N001(["開始"])\n    N002["処理"]\n    N001 --> N002\n',
        encoding="utf-8",
    )
    return mmd_file


def test_svg_renderer_finds_system_mmdc():
    """Test that renderer can find system mmdc."""
    renderer = SVGRenderer()
    with patch("shutil.which", return_value="/usr/bin/mmdc"):
        mmdc = renderer._find_mmdc()
        assert mmdc == "/usr/bin/mmdc"


def test_svg_renderer_finds_local_mmdc(tmp_path):
    """Test that renderer finds local node_modules mmdc."""
    local_mmdc = tmp_path / "node_modules" / ".bin" / "mmdc"
    local_mmdc.parent.mkdir(parents=True)
    local_mmdc.touch()

    renderer = SVGRenderer(project_root=tmp_path)
    with patch("shutil.which", return_value=None):
        mmdc = renderer._find_mmdc()
        assert mmdc == str(local_mmdc)


def test_svg_renderer_no_mmdc_found(tmp_path):
    """Test proper error when mmdc not found."""
    renderer = SVGRenderer(project_root=tmp_path)
    with patch("shutil.which", return_value=None):
        mmdc = renderer._find_mmdc()
        assert mmdc is None


def test_svg_renderer_render_success(sample_mmd, tmp_path):
    """Test successful SVG rendering."""
    svg_output = tmp_path / "output.svg"
    renderer = SVGRenderer(project_root=tmp_path)

    # Mock successful subprocess
    def mock_run(*args, **kwargs):
        # Create the SVG file as if mmdc did it
        svg_output.write_text("<svg>test</svg>")
        return MagicMock(returncode=0, stderr="")

    with patch("shutil.which", return_value="/usr/bin/mmdc"):
        with patch("subprocess.run", side_effect=mock_run):
            result = renderer.render(sample_mmd, svg_output)

    assert result.success is True
    assert result.svg_size > 0


def test_svg_renderer_render_failure(sample_mmd, tmp_path):
    """Test SVG rendering failure produces HTML fallback."""
    svg_output = tmp_path / "output.svg"
    renderer = SVGRenderer(project_root=tmp_path)

    with patch("shutil.which", return_value=None):
        with patch("subprocess.run", side_effect=Exception("no mmdc")):
            result = renderer.render(sample_mmd, svg_output)

    assert result.success is False
    assert result.html_fallback_path is not None
    assert result.html_fallback_path.exists()


def test_svg_renderer_sandbox_retry(sample_mmd, tmp_path):
    """Test that sandbox errors trigger retry with puppeteer config."""
    svg_output = tmp_path / "output.svg"
    renderer = SVGRenderer(project_root=tmp_path)

    call_count = [0]

    def mock_run(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return MagicMock(returncode=1, stderr="Running as root without --no-sandbox")
        else:
            svg_output.write_text("<svg>ok</svg>")
            return MagicMock(returncode=0, stderr="")

    with patch("shutil.which", return_value="/usr/bin/mmdc"):
        with patch("subprocess.run", side_effect=mock_run):
            result = renderer.render(sample_mmd, svg_output)

    assert result.success is True
    assert call_count[0] == 2  # First failed, second succeeded

    # Check puppeteer config was created
    config_path = tmp_path / "puppeteer-config.json"
    assert config_path.exists()
    config = json.loads(config_path.read_text())
    assert "--no-sandbox" in config["args"]


def test_svg_renderer_missing_mmd_file(tmp_path):
    """Test error when .mmd file doesn't exist."""
    renderer = SVGRenderer(project_root=tmp_path)
    result = renderer.render(tmp_path / "nonexistent.mmd", tmp_path / "out.svg")
    assert result.success is False
    assert "not found" in result.stderr


def test_svg_render_result_defaults():
    """Test SVGRenderResult default values."""
    result = SVGRenderResult()
    assert result.success is False
    assert result.svg_path is None
    assert result.svg_size == 0
    assert result.exit_code == -1
