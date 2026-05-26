#!/usr/bin/env python3
"""
Render each Excel sheet to a single-page PDF using LibreOffice UNO.
Strategy: Use a Python UNO script that sets each sheet's page style to
fit all columns/rows on one page, then exports to PDF one sheet at a time.
"""
import subprocess
import os
import sys
import json
import shutil
import time
from pathlib import Path

XLSX_PATH = "/tmp/s3_downloads/サンプル20260519/02_詳細設計/MW_IFマッピング定義書_205_発注情報(登録・変更・取消).xlsx"
OUTPUT_BASE = os.path.expanduser("~/projects/hermes_bedrock_agent/outputs/reparse_wb2")
PDF_DIR = f"{OUTPUT_BASE}/pdf"
IMG_DIR = f"{OUTPUT_BASE}/images"
TMP_DIR = "/tmp/lo_reparse"

# Load manifest
with open(f"{OUTPUT_BASE}/manifest.json") as f:
    manifest = json.load(f)

sheets = manifest['sheets']

os.makedirs(TMP_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)

def create_uno_export_script(xlsx_path, sheet_index, output_pdf_path):
    """Create a LibreOffice macro script that exports one sheet as single-page PDF."""
    # Use the approach: set page scaling to fit all cols/rows on one page
    script = f"""
import uno
from com.sun.star.beans import PropertyValue

def export_sheet():
    localContext = uno.getComponentContext()
    resolver = localContext.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", localContext)
    
    ctx = resolver.resolve(
        "uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
    smgr = ctx.ServiceManager
    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    
    # Open the file
    url = uno.systemPathToFileUrl("{xlsx_path}")
    props = []
    p = PropertyValue()
    p.Name = "Hidden"
    p.Value = True
    props.append(p)
    
    doc = desktop.loadComponentFromURL(url, "_blank", 0, tuple(props))
    sheets = doc.getSheets()
    
    # Activate target sheet
    sheet = sheets.getByIndex({sheet_index})
    doc.getCurrentController().setActiveSheet(sheet)
    
    # Set page style to fit on one page
    page_styles = doc.getStyleFamilies().getByName("PageStyles")
    style_name = sheet.PageStyle
    page_style = page_styles.getByName(style_name)
    page_style.ScaleToPages = 1  # Fit all on one page
    page_style.IsLandscape = True  # Landscape for wide sheets
    
    # Export to PDF
    pdf_props = []
    p1 = PropertyValue()
    p1.Name = "FilterName"
    p1.Value = "calc_pdf_Export"
    pdf_props.append(p1)
    
    # Export only active sheet
    p2 = PropertyValue()
    p2.Name = "FilterData"
    p2.Value = uno.Any("[]com.sun.star.beans.PropertyValue", (
        PropertyValue("Selection", 0, sheet, 0),
    ))
    pdf_props.append(p2)
    
    output_url = uno.systemPathToFileUrl("{output_pdf_path}")
    doc.storeToURL(output_url, tuple(pdf_props))
    doc.close(True)

export_sheet()
"""
    return script


def export_sheet_simple(xlsx_path, sheet_index, sheet_name, output_pdf, output_png):
    """Export single sheet using LibreOffice command-line with page fitting.
    
    Strategy: Create a temporary copy with modified page setup, then export.
    """
    import openpyxl
    from openpyxl.worksheet.page import PageMargins
    
    # Create temp copy with page setup for fitting on one page
    tmp_xlsx = os.path.join(TMP_DIR, f"tmp_sheet_{sheet_index}.xlsx")
    shutil.copy2(xlsx_path, tmp_xlsx)
    
    # Modify page setup to fit on 1 page
    wb = openpyxl.load_workbook(tmp_xlsx)
    
    # Hide all other sheets
    for i, name in enumerate(wb.sheetnames):
        if i == sheet_index:
            wb[name].sheet_state = 'visible'
            ws = wb[name]
            # Set page setup: fit to 1 page wide x 1 page tall
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.page_setup.fitToWidth = 1
            ws.page_setup.fitToHeight = 1
            ws.page_setup.orientation = 'landscape'
            # Reduce margins
            ws.page_margins = PageMargins(
                left=0.2, right=0.2, top=0.2, bottom=0.2,
                header=0.1, footer=0.1
            )
        else:
            wb[name].sheet_state = 'hidden'
    
    wb.save(tmp_xlsx)
    wb.close()
    
    # Export to PDF with LibreOffice
    result = subprocess.run(
        ['libreoffice', '--headless', '--calc', '--convert-to', 'pdf',
         '--outdir', TMP_DIR, tmp_xlsx],
        capture_output=True, text=True, timeout=60
    )
    
    tmp_pdf = os.path.join(TMP_DIR, f"tmp_sheet_{sheet_index}.pdf")
    
    if not os.path.exists(tmp_pdf):
        print(f"  ERROR: PDF not generated for sheet {sheet_index} ({sheet_name})")
        os.remove(tmp_xlsx)
        return False
    
    # Move PDF to output
    shutil.move(tmp_pdf, output_pdf)
    
    # Convert PDF to PNG at high DPI
    png_prefix = os.path.join(TMP_DIR, f"img_{sheet_index}")
    subprocess.run(
        ['pdftoppm', '-png', '-r', '200', '-singlefile', output_pdf, png_prefix],
        capture_output=True, timeout=60
    )
    
    tmp_png = f"{png_prefix}.png"
    if os.path.exists(tmp_png):
        shutil.move(tmp_png, output_png)
    else:
        # If singlefile fails (multi-page), stitch pages
        pages = sorted([
            os.path.join(TMP_DIR, f) 
            for f in os.listdir(TMP_DIR)
            if f.startswith(f"img_{sheet_index}") and f.endswith('.png')
        ])
        if pages:
            from PIL import Image
            imgs = [Image.open(p) for p in pages]
            total_h = sum(im.height for im in imgs)
            max_w = max(im.width for im in imgs)
            stitched = Image.new('RGB', (max_w, total_h), 'white')
            y = 0
            for im in imgs:
                stitched.paste(im, (0, y))
                y += im.height
                im.close()
            stitched.save(output_png, 'PNG')
            stitched.close()
            for p in pages:
                os.remove(p)
        else:
            print(f"  WARNING: No PNG generated for sheet {sheet_index}")
    
    # Clean temp xlsx
    os.remove(tmp_xlsx)
    return True


def main():
    print(f"Rendering {len(sheets)} sheets to single-page PDF + PNG")
    print(f"Output: {OUTPUT_BASE}")
    print()
    
    success = 0
    failed = []
    
    for sheet in sheets:
        idx = sheet['index']
        name = sheet['name']
        safe = sheet['safe']
        stype = sheet['type']
        
        output_pdf = os.path.join(PDF_DIR, f"{safe}.pdf")
        output_png = os.path.join(IMG_DIR, f"{safe}.png")
        
        print(f"  [{idx+1:02d}/27] {name} ({stype}, {sheet['rows']}x{sheet['cols']})")
        
        if stype == 'empty' and not sheet['has_data']:
            # For empty sheets, create a placeholder
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new('RGB', (400, 100), 'white')
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 14)
            except:
                font = ImageFont.load_default()
            draw.text((10, 10), f"Sheet: {name}", fill='black', font=font)
            draw.text((10, 40), "(Empty sheet - no data)", fill='gray', font=font)
            img.save(output_png, 'PNG')
            img.close()
            
            # Create minimal PDF
            subprocess.run(
                ['convert', output_png, output_pdf],
                capture_output=True, timeout=30
            )
            success += 1
            print(f"    → empty sheet placeholder created")
            continue
        
        ok = export_sheet_simple(XLSX_PATH, idx, name, output_pdf, output_png)
        if ok:
            success += 1
            print(f"    → OK")
        else:
            failed.append(sheet)
            print(f"    → FAILED")
        
        # Small delay to avoid LibreOffice conflicts
        time.sleep(1)
    
    print(f"\nResults: {success} success, {len(failed)} failed")
    if failed:
        print(f"Failed sheets: {[s['name'] for s in failed]}")
    
    # Clean tmp
    shutil.rmtree(TMP_DIR, ignore_errors=True)


if __name__ == '__main__':
    main()
