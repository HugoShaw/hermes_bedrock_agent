"""Visual renderer - exports Excel sheets as images for review.

Tries multiple strategies:
1. LibreOffice headless → PDF → images
2. openpyxl-chart + Pillow fallback
3. Raw placeholder if nothing works
"""
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def render_excel_to_images(excel_path: str, output_dir: str, sheet_names: list = None) -> dict:
    """Render Excel file to review images.
    
    Args:
        excel_path: Path to the Excel file
        output_dir: Directory where rendered PNGs will be saved
        sheet_names: Optional list of sheet names (in order) to label the output images
    
    Returns dict with:
        method: str - which method succeeded
        sheet_images: list[dict] - {sheet_name, path}
        success: bool
        error: str
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    result = {
        "method": "none",
        "sheet_images": [],
        "success": False,
        "error": ""
    }
    
    # Strategy 1: LibreOffice headless
    if _try_libreoffice(excel_path, output_path, result, sheet_names):
        return result
    
    # Strategy 2: xlsx2csv + simple placeholder
    result["method"] = "placeholder"
    result["success"] = False
    result["error"] = (
        "LibreOffice not available for rendering. "
        "Visual semantic review requires manual screenshot or LibreOffice installation. "
        "Install with: sudo apt-get install libreoffice"
    )
    
    logger.warning(result["error"])
    return result


def _try_libreoffice(excel_path: str, output_path: Path, result: dict, sheet_names: list = None) -> bool:
    """Try rendering via LibreOffice headless."""
    try:
        # Check if libreoffice is available
        check = subprocess.run(
            ["which", "libreoffice"],
            capture_output=True, text=True, timeout=5
        )
        if check.returncode != 0:
            return False
        
        # Convert to PDF first (put pdf in parent to avoid mixing with images)
        pdf_dir = output_path.parent / "pdf"
        pdf_dir.mkdir(exist_ok=True)
        
        cmd = [
            "libreoffice", "--headless", "--convert-to", "pdf",
            "--outdir", str(pdf_dir), excel_path
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if proc.returncode != 0:
            logger.warning(f"LibreOffice PDF conversion failed: {proc.stderr}")
            return False
        
        # Find the generated PDF
        pdf_files = list(pdf_dir.glob("*.pdf"))
        if not pdf_files:
            return False
        
        pdf_path = pdf_files[0]
        
        # Convert PDF to images using pdftoppm or Pillow
        # output_path is already the target directory (e.g., rendered/sheets/)
        images_dir = output_path
        images_dir.mkdir(exist_ok=True)
        
        if _pdf_to_images(str(pdf_path), str(images_dir), result, sheet_names):
            result["method"] = "libreoffice+pdftoppm"
            result["success"] = True
            return True
        
        return False
        
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"LibreOffice not available: {e}")
        return False


def _pdf_to_images(pdf_path: str, output_dir: str, result: dict, sheet_names: list = None) -> bool:
    """Convert PDF pages to PNG images."""
    try:
        # Try pdftoppm
        check = subprocess.run(
            ["which", "pdftoppm"],
            capture_output=True, text=True, timeout=5
        )
        if check.returncode == 0:
            cmd = [
                "pdftoppm", "-png", "-r", "200",
                pdf_path, f"{output_dir}/sheet"
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if proc.returncode == 0:
                # Find generated images
                images = sorted(Path(output_dir).glob("sheet-*.png"))
                for i, img in enumerate(images):
                    if sheet_names and i < len(sheet_names):
                        name = sheet_names[i]
                    else:
                        name = f"sheet_{i+1}"
                    result["sheet_images"].append({
                        "sheet_name": name,
                        "path": str(img),
                        "page_index": i
                    })
                return len(images) > 0
        
        # Try with pdf2image (Python library)
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(pdf_path, dpi=200)
            for i, img in enumerate(images):
                if sheet_names and i < len(sheet_names):
                    name = sheet_names[i]
                else:
                    name = f"sheet_{i+1}"
                img_path = f"{output_dir}/sheet_{i+1:03d}_{name}.png"
                img.save(img_path, "PNG")
                result["sheet_images"].append({
                    "sheet_name": name,
                    "path": img_path,
                    "page_index": i
                })
            return True
        except ImportError:
            pass
        
        return False
        
    except Exception as e:
        logger.warning(f"PDF to image conversion failed: {e}")
        return False


def render_region_crops(sheet_image_path: str, regions: list, output_dir: str) -> list:
    """Crop region images from the full sheet image.
    
    This is a best-effort operation - if we can't crop, we note it in the audit.
    """
    # For now, we skip actual cropping since we need sheet-level coordinates
    # mapping to pixel coordinates which requires knowing the DPI and cell sizes
    return []
