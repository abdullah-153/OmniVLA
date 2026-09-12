---
name: file_management
title: File Explorer Organizing & Archiving
description: Organizes downloaded or scattered files into structured directories and archives outdated documents.
domain: desktop
triggers:
  - "organize files"
  - "clean downloads folder"
  - "move files to *"
  - "archive documents"
parameters:
  - name: source_folder
    description: Folder to organize (e.g. Downloads, Desktop)
    type: string
    default_value: "Downloads"
    required: false
  - name: target_folder
    description: Destination archive folder
    type: string
    default_value: "Archive"
    required: false
author: system
version: 1.0.0
tags: [files, explorer, desktop, organization]
---

# File Explorer Organizing & Archiving

Organizes downloaded or scattered files into structured directories and archives outdated documents.

## Cognitive Strategy & Workflow
1. **Open File Explorer**: Press `Win+E` to launch File Explorer, then navigate to `{{source_folder}}`.
2. **Sort by Date / Type**: Click the 'Date modified' or 'Type' column header in the file list to group items.
3. **Select Target Items**: Click the first file, hold `Shift`, and select the range of matching files to move.
4. **Transfer Files**: Press `Ctrl+X` to cut items, navigate to `{{target_folder}}` in the left sidebar or address bar, and press `Ctrl+V` to paste.
5. **Verify Completion**: Verify visually that the source directory is clean and the destination contains the expected files.

## Visual Landmarks & Grounding Cues
- File Explorer Address Bar: Top breadcrumb navigation bar showing current path.
- Left Navigation Tree: Vertical list showing Quick Access, This PC, and drives.
- Column Headers: 'Name', 'Date modified', 'Type', 'Size'.

## Failure Modes & Recovery
- **File in Use Dialog**: If 'File in Use' modal appears, click 'Skip' or 'Try Again' after waiting 1 second.
- **Destination Folder Missing**: If `{{target_folder}}` does not exist, press `Ctrl+Shift+N` to create a new folder and name it.
