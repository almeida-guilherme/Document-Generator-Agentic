import os
from PIL import Image
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from schemas import ProcessModel, ExceptionItem, RequirementItem, format_timestamp
from flowchart import build_flowchart, columns_for


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


def add_bookmark(paragraph, bookmark_name: str, bookmark_id: int):
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark_id))
    start.set(qn("w:name"), bookmark_name)
    # w:pPr must stay the paragraph's first child, otherwise Word refuses to open the file.
    p_pr = paragraph._p.pPr
    if p_pr is not None:
        p_pr.addnext(start)
    else:
        paragraph._p.insert(0, start)

    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))
    paragraph._p.append(end)


def add_internal_hyperlink(paragraph, bookmark_name: str, text: str):
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("w:anchor"), bookmark_name)

    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")

    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    rPr.append(color)

    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    rPr.append(underline)

    run.append(rPr)

    text_elem = OxmlElement("w:t")
    text_elem.text = text
    run.append(text_elem)

    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def add_manual_toc(doc, entries: list[tuple[str, str, int]]):
    """entries: list of (bookmark_name, display_text, indent_level)"""
    for bookmark_name, text, indent in entries:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.25 * indent)
        add_internal_hyperlink(p, bookmark_name, text)


def add_exception_table(doc, title: str, items: list[ExceptionItem]):
    doc.add_heading(title, level=2)

    if not items:
        doc.add_paragraph(f"No {title.lower()} identified in this process.")
        return

    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    add_header_row(table, ["Exception Name", "Action", "Parameters", "Action to be Taken"])

    for item in items:
        row = table.add_row()
        row.cells[0].text = item.name
        row.cells[1].text = item.action
        row.cells[2].text = item.parameters
        row.cells[3].text = item.action_to_be_taken


REQUIREMENT_LABELS = {
    "frequency": "Frequency",
    "volume": "Volume",
    "business_rule": "Business rule",
    "reference_data": "Reference data",
    "access": "Access",
    "other": "Other",
}


def add_requirements_table(doc, items: list[RequirementItem]):
    if not items:
        doc.add_paragraph("No business rules or requirements identified in this process.")
        return

    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    add_header_row(table, ["Type", "Description"])

    order = list(REQUIREMENT_LABELS)
    for item in sorted(items, key=lambda r: order.index(r.category)):
        row = table.add_row()
        row.cells[0].text = REQUIREMENT_LABELS[item.category]
        row.cells[1].text = item.description
    set_column_widths(table, [1.4, 5.1])


INPUT_KIND_LABELS = {"structured": "structured", "semi_structured": "semi-structured", "unstructured": "unstructured"}


def set_column_widths(table, widths: list[float]):
    """Word reads the cell widths, LibreOffice the column widths; autofit would override both."""
    table.autofit = False
    for column, width in zip(table.columns, widths):
        column.width = Inches(width)
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = Inches(width)


def add_header_row(table, headers: list[str]):
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        cell.paragraphs[0].runs[0].bold = True
        set_cell_shading(cell, "2F5496")


def add_overview_table(doc, model: ProcessModel):
    """The facts an automation assessment starts from, measured from the recording where possible."""
    recorded = model.recorded_seconds
    rows = [
        ("Applications", ", ".join(model.applications) or "Not identified"),
        ("Inputs", "\n".join(f"{i.name} ({INPUT_KIND_LABELS[i.kind]}{', from ' + i.source if i.source else ''})"
                             for i in model.inputs) or "Not identified"),
        ("Steps", str(len(model.as_is))),
        ("Decision points", ", ".join(f"step {s.number}" for s in model.decision_points) or "None identified"),
    ]
    if recorded is not None:
        rows.append(("Recorded duration", f"{format_timestamp(recorded)} (includes the narrator's explanations, "
                                          "so the task itself is usually faster)"))
    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    add_header_row(table, ["Item", "Value"])
    for label, value in rows:
        row = table.add_row()
        row.cells[0].text, row.cells[1].text = label, value
    set_column_widths(table, [1.6, 4.9])


def render_docx(pdd: ProcessModel, output_path: str = "output/PDD_final.docx") -> tuple[str, dict]:
    """Writes the .docx; returns its path and what was actually inserted (for the run report)."""
    doc = Document()
    stats = {"images_inserted": 0, "images_missing": [], "flowchart": False}
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # --- Page 1: Cover ---
    title = doc.add_heading("Process Design Document (PDD)", level=0)
    remove_heading_border(title)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    subtitle = doc.add_heading(pdd.process_name, level=1)
    remove_heading_border(subtitle)
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_page_break()

    # --- Page 2: Table of Contents (manual, hyperlinked) ---
    toc_heading = doc.add_heading("Table of Contents", level=1)
    remove_heading_border(toc_heading)
    toc_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    toc_entries = [
        ("intro", "1. Introduction", 0),
        ("proposal", "1.1 Project Proposal", 1),
        ("overview", "1.2 Process Overview", 1),
        ("asis", "2. As Is", 0),
        ("flowchart_sec", "2.1 Flowchart", 1),
        ("steps_sec", "2.2 Process Steps", 1),
        ("exceptions", "3. Exceptions", 0),
        ("requirements", "4. Business Rules & Requirements", 0),
    ]
    add_manual_toc(doc, toc_entries)

    doc.add_page_break()

    # --- Page 3+: Content ---

    # 1. Introduction
    h = doc.add_heading("1. Introduction", level=1)
    add_bookmark(h, "intro", 1)

    h = doc.add_heading("1.1 Project Proposal", level=2)
    add_bookmark(h, "proposal", 2)
    doc.add_paragraph(pdd.project_proposal)

    h = doc.add_heading("1.2 Process Overview", level=2)
    add_bookmark(h, "overview", 8)
    add_overview_table(doc, pdd)

    # 2. As Is
    h = doc.add_heading("2. As Is", level=1)
    add_bookmark(h, "asis", 3)

    h = doc.add_heading("2.1 Flowchart", level=2)
    add_bookmark(h, "flowchart_sec", 4)
    try:
        flowchart_path = build_flowchart(pdd, output_path=os.path.join(os.path.dirname(output_path), "flowchart"))
        # Fit inside the box so a long chart shrinks instead of being cut off at the page bottom; a chart
        # laid out in several columns gets the full page width.
        max_w = 3.5 if columns_for(len(pdd.as_is)) == 1 else 6.5
        max_h = 7.5
        with Image.open(flowchart_path) as img:
            width, height = img.size
        if height / width > max_h / max_w:
            doc.add_picture(flowchart_path, height=Inches(max_h))
        else:
            doc.add_picture(flowchart_path, width=Inches(max_w))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        stats["flowchart"] = True
    except Exception as e:
        print(f"Failed to generate/insert flowchart: {e}")
        doc.add_paragraph("[Flowchart could not be generated]")

    h = doc.add_heading("2.2 Process Steps", level=2)
    add_bookmark(h, "steps_sec", 5)
    for step in pdd.as_is:
        # keep_with_next keeps each step's heading, text, screenshot and caption on the same page.
        title = f"Step {step.number}" + (f" — {step.application}" if step.application else "")
        title += f" ({step.time})" if step.time else ""
        doc.add_heading(title, level=3).paragraph_format.keep_with_next = True

        doc.add_paragraph(step.instruction).paragraph_format.keep_with_next = True
        if step.decision:
            p = doc.add_paragraph()
            p.add_run("Decision: ").bold = True
            p.add_run(step.decision)
            p.paragraph_format.keep_with_next = True

        image = step.main_frame_path
        if image and os.path.exists(image):
            doc.add_picture(image, width=Inches(5.5))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            doc.paragraphs[-1].paragraph_format.keep_with_next = True
            caption = doc.add_paragraph(f"Screenshot — Step {step.number}")
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption.runs[0].italic = True
            caption.runs[0].font.size = Pt(9)
            stats["images_inserted"] += 1
        else:
            doc.add_paragraph("[No screenshot for this step]")
            stats["images_missing"].append(step.number)

        doc.add_paragraph()

    # 3. Exceptions
    h = doc.add_heading("3. Exceptions", level=1)
    add_bookmark(h, "exceptions", 6)
    add_exception_table(doc, "Business Exceptions", pdd.business_exceptions)
    add_exception_table(doc, "System Exceptions", pdd.system_exceptions)

    # 4. Business rules & requirements
    h = doc.add_heading("4. Business Rules & Requirements", level=1)
    add_bookmark(h, "requirements", 7)
    add_requirements_table(doc, pdd.requirements)

    doc.save(output_path)

    return output_path, stats