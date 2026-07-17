"""Generate PDF files from the OmniVLA documentation markdown files.

This script converts all .md files in the documentation/ directory to PDF format.
It uses markdown2 for HTML conversion and weasyprint for PDF rendering.

If weasyprint is not available (common on Windows without GTK), it falls back
to creating styled HTML files that can be printed to PDF from any browser.

Usage:
    pip install markdown2
    python generate_documentation_pdfs.py
"""

import os
import glob
import re
import sys


def markdown_to_styled_html(md_content: str, title: str) -> str:
    """Convert markdown content to a beautifully styled HTML document."""
    
    try:
        import markdown2
        html_body = markdown2.markdown(
            md_content,
            extras=[
                "fenced-code-blocks",
                "tables",
                "code-friendly",
                "header-ids",
                "break-on-newline",
                "cuddled-lists",
            ]
        )
    except ImportError:
        # Basic fallback: manual conversion of key elements
        html_body = basic_md_to_html(md_content)
    
    css = """
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    
    * { margin: 0; padding: 0; box-sizing: border-box; }
    
    body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        line-height: 1.7;
        color: #1a1a2e;
        background: #ffffff;
        max-width: 900px;
        margin: 0 auto;
        padding: 60px 40px;
        font-size: 14px;
    }
    
    h1 {
        font-size: 2.2em;
        font-weight: 700;
        color: #0f0f23;
        margin-top: 0;
        margin-bottom: 8px;
        padding-bottom: 16px;
        border-bottom: 3px solid #667eea;
        letter-spacing: -0.5px;
    }
    
    h2 {
        font-size: 1.6em;
        font-weight: 600;
        color: #1a1a2e;
        margin-top: 48px;
        margin-bottom: 16px;
        padding-bottom: 8px;
        border-bottom: 1px solid #e2e8f0;
    }
    
    h3 {
        font-size: 1.25em;
        font-weight: 600;
        color: #2d3748;
        margin-top: 32px;
        margin-bottom: 12px;
    }
    
    h4 {
        font-size: 1.05em;
        font-weight: 600;
        color: #4a5568;
        margin-top: 24px;
        margin-bottom: 8px;
    }
    
    p {
        margin-bottom: 16px;
        color: #2d3748;
    }
    
    strong { font-weight: 600; color: #1a1a2e; }
    
    em { font-style: italic; color: #4a5568; }
    
    a { color: #667eea; text-decoration: none; }
    a:hover { text-decoration: underline; }
    
    code {
        font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
        background: #f1f5f9;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.88em;
        color: #e53e3e;
    }
    
    pre {
        background: #1a1a2e;
        color: #e2e8f0;
        padding: 20px 24px;
        border-radius: 8px;
        overflow-x: auto;
        margin: 16px 0 24px 0;
        font-size: 0.85em;
        line-height: 1.6;
        border: 1px solid #2d3748;
    }
    
    pre code {
        background: transparent;
        color: #e2e8f0;
        padding: 0;
        font-size: 1em;
    }
    
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 16px 0 24px 0;
        font-size: 0.92em;
    }
    
    thead th {
        background: #667eea;
        color: white;
        padding: 12px 16px;
        text-align: left;
        font-weight: 600;
        font-size: 0.9em;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    tbody td {
        padding: 10px 16px;
        border-bottom: 1px solid #e2e8f0;
        vertical-align: top;
    }
    
    tbody tr:nth-child(even) { background: #f8fafc; }
    tbody tr:hover { background: #edf2f7; }
    
    ul, ol {
        margin: 8px 0 16px 24px;
    }
    
    li {
        margin-bottom: 6px;
        color: #2d3748;
    }
    
    li code { font-size: 0.85em; }
    
    blockquote {
        border-left: 4px solid #667eea;
        background: #f0f4ff;
        padding: 16px 20px;
        margin: 16px 0;
        border-radius: 0 8px 8px 0;
        font-style: italic;
        color: #4a5568;
    }
    
    blockquote strong { color: #2d3748; }
    
    hr {
        border: none;
        border-top: 2px solid #e2e8f0;
        margin: 40px 0;
    }
    
    /* Print styles */
    @media print {
        body { padding: 20px; max-width: 100%; }
        pre { background: #f5f5f5 !important; color: #333 !important; 
              border: 1px solid #ddd; }
        pre code { color: #333 !important; }
        thead th { background: #333 !important; }
        h1, h2, h3 { page-break-after: avoid; }
        pre, table { page-break-inside: avoid; }
    }
    
    .title-block {
        text-align: center;
        margin-bottom: 48px;
        padding: 40px 0;
        border-bottom: 3px solid #667eea;
    }
    
    .title-block h1 {
        border: none;
        padding: 0;
        margin: 0;
        font-size: 2.5em;
    }
    
    .subtitle {
        color: #667eea;
        font-size: 1.2em;
        font-weight: 400;
        margin-top: 8px;
    }
    
    .footer {
        margin-top: 60px;
        padding-top: 20px;
        border-top: 1px solid #e2e8f0;
        text-align: center;
        color: #a0aec0;
        font-size: 0.85em;
    }
    """
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>{css}</style>
</head>
<body>
    {html_body}
    <div class="footer">
        <p>OmniVLA Project Documentation &mdash; Generated April 2026</p>
        <p>Confidential &mdash; Final Year Project</p>
    </div>
</body>
</html>"""
    
    return html


def basic_md_to_html(md: str) -> str:
    """Very basic markdown to HTML (fallback if markdown2 not installed)."""
    lines = md.split('\n')
    html_lines = []
    in_code_block = False
    in_table = False
    
    for line in lines:
        if line.startswith('```'):
            if in_code_block:
                html_lines.append('</code></pre>')
                in_code_block = False
            else:
                lang = line[3:].strip()
                html_lines.append(f'<pre><code class="language-{lang}">')
                in_code_block = True
            continue
        
        if in_code_block:
            html_lines.append(line.replace('<', '&lt;').replace('>', '&gt;'))
            continue
        
        # Headers
        if line.startswith('# '):
            html_lines.append(f'<h1>{line[2:]}</h1>')
        elif line.startswith('## '):
            html_lines.append(f'<h2>{line[3:]}</h2>')
        elif line.startswith('### '):
            html_lines.append(f'<h3>{line[4:]}</h3>')
        elif line.startswith('#### '):
            html_lines.append(f'<h4>{line[5:]}</h4>')
        elif line.startswith('---'):
            html_lines.append('<hr>')
        elif line.startswith('| '):
            if not in_table:
                html_lines.append('<table><thead><tr>')
                in_table = True
                cells = [c.strip() for c in line.split('|')[1:-1]]
                for cell in cells:
                    html_lines.append(f'<th>{cell}</th>')
                html_lines.append('</tr></thead><tbody>')
            elif '---' in line:
                continue  # Skip separator row
            else:
                html_lines.append('<tr>')
                cells = [c.strip() for c in line.split('|')[1:-1]]
                for cell in cells:
                    html_lines.append(f'<td>{cell}</td>')
                html_lines.append('</tr>')
        else:
            if in_table and not line.startswith('|'):
                html_lines.append('</tbody></table>')
                in_table = False
            if line.strip():
                # Bold
                line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
                # Italic
                line = re.sub(r'\*(.+?)\*', r'<em>\1</em>', line)
                # Inline code
                line = re.sub(r'`(.+?)`', r'<code>\1</code>', line)
                html_lines.append(f'<p>{line}</p>')
    
    if in_table:
        html_lines.append('</tbody></table>')
    
    return '\n'.join(html_lines)


def main():
    docs_dir = "documentation"
    output_dir = os.path.join(docs_dir, "html_output")
    os.makedirs(output_dir, exist_ok=True)
    
    md_files = sorted(glob.glob(os.path.join(docs_dir, "*.md")))
    
    if not md_files:
        print(f"No markdown files found in {docs_dir}/")
        return
    
    print(f"Found {len(md_files)} documentation files")
    print("=" * 60)
    
    # Try PDF generation first
    try_pdf = False
    try:
        import importlib
        weasyprint_module = importlib.import_module("weasyprint")
        HTML = weasyprint_module.HTML
        try_pdf = True
        print("weasyprint available -- will generate PDFs")
    except Exception:
        print("weasyprint not available -- generating styled HTML files")
        print("To get PDFs: open HTML files in Chrome and use Ctrl+P -> Save as PDF")
    
    for md_file in md_files:
        basename = os.path.splitext(os.path.basename(md_file))[0]
        
        with open(md_file, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        # Extract title from first heading
        title_match = re.search(r'^#\s+(.+)$', md_content, re.MULTILINE)
        title = title_match.group(1) if title_match else basename
        
        # Convert to styled HTML
        html_content = markdown_to_styled_html(md_content, title)
        
        # Save HTML
        html_path = os.path.join(output_dir, f"{basename}.html")
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Try PDF
        if try_pdf:
            try:
                pdf_path = os.path.join(output_dir, f"{basename}.pdf")
                HTML(string=html_content).write_pdf(pdf_path)
                print(f"  [OK] PDF: {pdf_path}")
            except Exception as e:
                print(f"  [FAIL] PDF failed for {basename}: {e}")
                print(f"  -> HTML saved: {html_path}")
        else:
            file_size_kb = os.path.getsize(html_path) / 1024
            print(f"  [OK] HTML ({file_size_kb:.0f}KB): {html_path}")
    
    print("=" * 60)
    print(f"Output directory: {os.path.abspath(output_dir)}")
    
    if not try_pdf:
        print()
        print("To convert HTML to PDF:")
        print("  1. Open any HTML file in Chrome/Edge")
        print("  2. Press Ctrl+P")
        print("  3. Change destination to 'Save as PDF'")
        print("  4. Click Save")
        print()
        print("Or install weasyprint: pip install weasyprint")
        print("  (requires GTK3 on Windows -- see https://doc.courtbouillon.org/weasyprint/)")


if __name__ == "__main__":
    main()
