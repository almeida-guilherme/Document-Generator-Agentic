from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from schemas import PDD


def set_cell_shading(cell, color_hex: str):
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), color_hex)
    cell._tc.get_or_add_tcPr().append(shading)


def add_info_row(table, label: str, value: str):
    row = table.add_row()
    label_cell, value_cell = row.cells

    label_cell.text = label
    label_cell.paragraphs[0].runs[0].bold = True
    set_cell_shading(label_cell, "D9E2F3")

    value_cell.text = value


def render_docx(pdd: PDD, output_path: str = "output/PDD_final.docx") -> str:
    doc = Document()

    # Title
    title = doc.add_heading("Process Design Document (PDD)", level=0)
    doc.add_heading(pdd.process_name, level=2)

    # Info table
    info_table = doc.add_table(rows=0, cols=2)
    info_table.style = "Table Grid"
    add_info_row(info_table, "Process Name", pdd.process_name)
    add_info_row(info_table, "Objective", pdd.objective)
    add_info_row(info_table, "Scope Start", pdd.scope_start)
    add_info_row(info_table, "Scope End", pdd.scope_end)
    add_info_row(info_table, "Tools", ", ".join(pdd.tools))

    doc.add_paragraph()

    # Steps section
    doc.add_heading("Process Steps (As-Is)", level=1)

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
            last_paragraph = doc.paragraphs[-1]
            last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

            caption = doc.add_paragraph(f"Screenshot — Step {step.number}")
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption.runs[0].italic = True
            caption.runs[0].font.size = Pt(9)
        except FileNotFoundError:
            doc.add_paragraph(f"[Image not found: {step.frame_ref}]")

        doc.add_paragraph()

    # Business rules
    doc.add_heading("Business Rules", level=1)
    if pdd.business_rules:
        for rule in pdd.business_rules:
            doc.add_paragraph(rule, style="List Bullet")
    else:
        doc.add_paragraph("No business rules identified in this process.")

    # Exceptions
    doc.add_heading("Exceptions", level=1)
    if pdd.exceptions:
        for exc in pdd.exceptions:
            doc.add_paragraph(exc, style="List Bullet")
    else:
        doc.add_paragraph("No exceptions observed in this process.")

    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)

    return output_path