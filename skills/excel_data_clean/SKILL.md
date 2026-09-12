---
name: excel_data_clean
title: Excel Spreadsheet Cleaning & Formatting
description: Formats unformatted spreadsheet tables, auto-fits columns, bolds headers, and highlights key data rows.
domain: excel
triggers:
  - "clean excel data"
  - "format spreadsheet"
  - "format excel sheet"
  - "clean table in excel"
parameters:
  - name: file_path
    description: Path to target spreadsheet file
    type: string
    required: false
  - name: apply_table_style
    description: Whether to apply standard Excel table formatting
    type: boolean
    default_value: true
    required: false
author: system
version: 1.0.0
tags: [excel, spreadsheet, office, data]
---

# Excel Spreadsheet Cleaning & Formatting

Formats unformatted spreadsheet tables, auto-fits columns, bolds headers, and highlights key data rows.

## Cognitive Strategy & Workflow
1. **Focus Excel Window**: Bring Microsoft Excel to the foreground. If `{{file_path}}` is provided, open the file.
2. **Select Entire Table**: Click on cell A1, then press `Ctrl+A` to select the entire contiguous table range.
3. **Format Table Header**: Press `Ctrl+B` to bold the header row, and apply center alignment.
4. **Auto-Fit Columns**: Double-click the boundary line between column headers A and B (or press `Alt+H+O+I`) to auto-fit all columns to content width.
5. **Freeze Header Row**: Navigate to the 'View' tab on the ribbon, locate 'Freeze Panes', and select 'Freeze Top Row'.
6. **Save Changes**: Press `Ctrl+S` to save the formatted workbook.

## Visual Landmarks & Grounding Cues
- Formula Bar: Long white input strip below the main ribbon.
- Column Headers: Letters A, B, C... along the top of the grid.
- Green Ribbon: Top application bar with 'Home', 'Insert', 'Page Layout', 'Data', 'View'.
- Cell Selection Boundary: Thin green rectangle surrounding the selected cells.

## Failure Modes & Recovery
- **Read-Only / Protected View Warning**: If a yellow notification banner appears stating 'PROTECTED VIEW', click the 'Enable Editing' button on the banner.
- **Formula Error (#VALUE!, #REF!)**: If error flags appear in cells, highlight the affected rows in light red.
