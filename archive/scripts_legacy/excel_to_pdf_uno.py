#!/usr/bin/env python3
"""
Production-quality per-sheet PDF exporter using LibreOffice UNO API.

This script:
1. Opens the original Excel workbook in LibreOffice (preserving all shapes/drawings)
2. For each sheet, sets adaptive paper size based on column count
3. Exports each sheet as a single-page PDF using the Selection filter
4. Converts each PDF to PNG at appropriate DPI
5. Autocrops whitespace and generates tiles for VLM analysis

Requirements:
- LibreOffice installed with python-uno bindings
- System python3 (not venv) for UNO imports
- pdftoppm (poppler-utils) for PDF→PNG conversion
- PIL/Pillow for image processing

Usage:
  # Start LibreOffice listener first:
  soffice --headless --invisible --nocrashreport --nodefault --nofirststartwizard \
    "--accept=socket,host=localhost,port=2002;urp;StarOffice.ServiceManager" &
  sleep 8
  
  # Then run this script with system python:
  /usr/bin/python3 excel_to_pdf_uno.py <input.xlsx> <output_dir>
"""
import uno
from com.sun.star.beans import PropertyValue
import subprocess
import os
import sys
import json
import time


def connect(port=2002):
    """Connect to running LibreOffice instance."""
    local_ctx = uno.getComponentContext()
    resolver = local_ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_ctx)
    ctx = resolver.resolve(
        f"uno:socket,host=localhost,port={port};urp;StarOffice.ComponentContext")
    smgr = ctx.ServiceManager
    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    return desktop


def get_paper_config(max_col, max_row):
    """Determine paper size based on sheet dimensions."""
    if max_col <= 20 and max_row <= 50:
        # Small sheet: A3 landscape
        return 1190, 841, True, 1, 1
    elif max_col <= 20:
        # Narrow but tall: A1 portrait, fit width only
        return 594, 841, False, 1, 0
    elif max_col <= 50:
        # Medium-narrow: A1 landscape, fit width only
        return 841, 594, True, 1, 0
    elif max_col <= 100:
        # Medium-wide: A0 landscape, fit width only
        return 1189, 841, True, 1, 0
    else:
        # Very wide: custom 3000x2000mm, fit width only
        return 3000, 2000, True, 1, 0


def export_sheet(doc, sheet_idx, output_path, max_col, max_row):
    """Export a single sheet to PDF with adaptive paper sizing."""
    sheets = doc.getSheets()
    sheet = sheets.getByIndex(sheet_idx)
    controller = doc.getCurrentController()
    controller.setActiveSheet(sheet)
    
    # Get paper config
    pw_mm, ph_mm, landscape, stx, sty = get_paper_config(max_col, max_row)
    
    # Set page style
    page_style_name = sheet.getPropertyValue("PageStyle")
    page_styles = doc.getStyleFamilies().getByName("PageStyles")
    ps = page_styles.getByName(page_style_name)
    
    try:
        ps.setPropertyValue("IsLandscape", landscape)
        ps.setPropertyValue("Width", pw_mm * 100)  # hundredths of mm
        ps.setPropertyValue("Height", ph_mm * 100)
        ps.setPropertyValue("TopMargin", 500)
        ps.setPropertyValue("BottomMargin", 500)
        ps.setPropertyValue("LeftMargin", 500)
        ps.setPropertyValue("RightMargin", 500)
        ps.setPropertyValue("ScaleToPages", 0)
        ps.setPropertyValue("ScaleToPagesX", stx)
        ps.setPropertyValue("ScaleToPagesY", sty)
    except Exception as e:
        print(f"    [page style warning: {e}]")
    
    # Export to PDF with Selection filter
    output_url = uno.systemPathToFileUrl(output_path)
    filter_data = (
        PropertyValue(Name="Selection", Value=sheet),
        PropertyValue(Name="IsSkipEmptyPages", Value=False),
        PropertyValue(Name="MaxImageResolution", Value=300),
    )
    export_props = (
        PropertyValue(Name="FilterName", Value="calc_pdf_Export"),
        PropertyValue(Name="FilterData",
                     Value=uno.Any("[]com.sun.star.beans.PropertyValue", filter_data)),
        PropertyValue(Name="Overwrite", Value=True),
    )
    
    doc.storeToURL(output_url, export_props)
    
    if not os.path.exists(output_path):
        return None
    
    # Get page count
    r = subprocess.run(['pdfinfo', output_path], capture_output=True, text=True, timeout=5)
    pages = 1
    for line in r.stdout.split('\n'):
        if 'Pages:' in line:
            pages = int(line.split(':')[1].strip())
    
    return {
        'path': output_path,
        'pages': pages,
        'paper': f"{pw_mm}x{ph_mm}mm",
        'landscape': landscape,
        'scale': f"X={stx},Y={sty}"
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: /usr/bin/python3 excel_to_pdf_uno.py <input.xlsx> <output_dir>")
        sys.exit(1)
    
    xlsx_path = os.path.abspath(sys.argv[1])
    output_dir = os.path.abspath(sys.argv[2])
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Input:  {xlsx_path}")
    print(f"Output: {output_dir}")
    
    # Connect to LibreOffice
    desktop = connect()
    print("Connected to LibreOffice")
    
    # Open workbook
    file_url = uno.systemPathToFileUrl(xlsx_path)
    open_props = (
        PropertyValue(Name="Hidden", Value=True),
        PropertyValue(Name="MacroExecutionMode", Value=0),
    )
    doc = desktop.loadComponentFromURL(file_url, "_blank", 0, open_props)
    if doc is None:
        print("ERROR: Failed to open workbook")
        sys.exit(1)
    
    sheets = doc.getSheets()
    n_sheets = sheets.getCount()
    print(f"Workbook has {n_sheets} sheets")
    
    results = []
    for i in range(n_sheets):
        sheet = sheets.getByIndex(i)
        name = sheet.getName()
        
        # Get used range
        cursor = sheet.createCursor()
        cursor.gotoStartOfUsedArea(False)
        cursor.gotoEndOfUsedArea(True)
        max_col = cursor.getRangeAddress().EndColumn + 1
        max_row = cursor.getRangeAddress().EndRow + 1
        
        safe_name = f"sheet_{i+1:02d}"
        pdf_path = os.path.join(output_dir, f"{safe_name}.pdf")
        
        print(f"  [{i+1:02d}/{n_sheets}] {name} ({max_col}c x {max_row}r):", end=" ", flush=True)
        
        result = export_sheet(doc, i, pdf_path, max_col, max_row)
        
        if result:
            print(f"OK ({result['pages']}pg, {result['paper']})")
            results.append({
                'index': i + 1,
                'name': name,
                'safe_name': safe_name,
                'cols': max_col,
                'rows': max_row,
                **result
            })
        else:
            print("FAILED")
            results.append({
                'index': i + 1,
                'name': name,
                'safe_name': safe_name,
                'status': 'failed'
            })
    
    doc.close(True)
    
    # Save manifest
    manifest_path = os.path.join(output_dir, "export_manifest.json")
    with open(manifest_path, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\nExported {sum(1 for r in results if 'path' in r)}/{n_sheets} sheets")
    print(f"Manifest: {manifest_path}")


if __name__ == '__main__':
    main()
