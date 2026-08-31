from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from schemas import PDD, ExceptionItem
import os


def set_cell_shading(cell, color_hex: str):
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), color_hex)
    cell._tc.get_or_add_tcPr().append(shading)


def remove_heading_border(paragraph):
    """Remove the bottom border that comes by default with Title/Heading styles."""
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "none")
    pBdr.append(bottom)
    pPr.append(pBdr)


def add_table_of_contents(doc):
    """Inserts a real Word TOC field. Word will calculate/display it when opened
    (may show 'Right-click > Update Field' the first time, depending on the Word version)."""
    paragraph = doc.add_paragraph()
    run = paragraph.add_run()

    fldChar_begin = OxmlElement("w:fldChar")
    fldChar_begin.set(qn("w:fldCharType"), "begin")

    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = 'TOC \\o "1-3" \\h \\z \\u'

    fldChar_separate = OxmlElement("w:fldChar")
    fldChar_separate.set(qn("w:fldCharType"), "separate")

    fldChar_end = OxmlElement("w:fldChar")
    fldChar_end.set(qn("w:fldCharType"), "end")

    run._r.append(fldChar_begin)
    run._r.append(instrText)
    run._r.append(fldChar_separate)
    run._r.append(fldChar_end)


def add_exception_table(doc, title: str, items: list[ExceptionItem]):
    doc.add_heading(title, level=2)

    if not items:
        doc.add_paragraph(f"No {title.lower()} identified in this process.")
        return

    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    headers = ["Exception Name", "Action", "Parameters", "Action to be Taken"]
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        cell.paragraphs[0].runs[0].bold = True
        set_cell_shading(cell, "2F5496")

    for item in items:
        row = table.add_row()
        row.cells[0].text = item.name
        row.cells[1].text = item.action
        row.cells[2].text = item.parameters
        row.cells[3].text = item.action_to_be_taken


def render_docx(pdd: PDD, output_path: str = "output/PDD_final.docx") -> str:
    doc = Document()

    # --- Page 1: Cover ---
    title = doc.add_heading("Process Design Document (PDD)", level=0)
    remove_heading_border(title)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    subtitle = doc.add_heading(pdd.process_name, level=1)
    remove_heading_border(subtitle)
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_page_break()

    # --- Page 2: Table of Contents ---
    toc_heading = doc.add_heading("Table of Contents", level=1)
    remove_heading_border(toc_heading)
    toc_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_table_of_contents(doc)

    doc.add_page_break()

    # --- Page 3+: Content ---
    doc.add_heading("1. Introduction", level=1)
    doc.add_heading("1.1 Project Proposal", level=2)
    doc.add_paragraph(pdd.project_proposal)

    doc.add_heading("2. As Is", level=1)

    doc.add_heading("2.1 Flowchart", level=2)
    doc.add_paragraph("[Flowchart to be added]")

    doc.add_heading("2.2 Process Steps", level=2)
    for step in pdd.as_is:
        doc.add_heading(f"Step {step.number} — {step.time}", level=3)

        p = doc.add_paragraph()
        p.add_run("System: ").bold = True
        p.add_run(step.system)

        p = doc.add_paragraph()
        p.add_run("Action: ").bold = True
        p.add_run(step.action)

        p = doc.add_paragraph()
        p.add_run("Result: ").bold = True
        p.add_run(step.result)

        try:
            doc.add_picture(step.frame_ref, width=Inches(5.5))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption = doc.add_paragraph(f"Screenshot — Step {step.number}")
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption.runs[0].italic = True
            caption.runs[0].font.size = Pt(9)
        except FileNotFoundError:
            doc.add_paragraph(f"[Image not found: {step.frame_ref}]")

        doc.add_paragraph()

    doc.add_heading("3. Exceptions", level=1)
    add_exception_table(doc, "Business Exceptions", pdd.business_exceptions)
    add_exception_table(doc, "System Exceptions", pdd.system_exceptions)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)

    return output_path