"""Unifica el correo público de la plataforma en scripts y presentaciones."""
from pathlib import Path

from pptx import Presentation

OLD = "old.lodoman@gmail.com"
NEW = "tupedidojr@gmail.com"
BASE = Path(__file__).parent


def replace_in_paragraph(paragraph):
    if OLD not in paragraph.text:
        return 0
    full = paragraph.text.replace(OLD, NEW)
    runs = paragraph.runs
    if runs:
        for run in runs[1:]:
            run.text = ""
        runs[0].text = full
    else:
        paragraph.text = full
    return 1


def replace_in_shape(shape):
    count = 0
    if getattr(shape, "has_text_frame", False):
        for paragraph in shape.text_frame.paragraphs:
            count += replace_in_paragraph(paragraph)
    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            for cell in row.cells:
                for paragraph in cell.text_frame.paragraphs:
                    count += replace_in_paragraph(paragraph)
    if getattr(shape, "shapes", None):
        for child in shape.shapes:
            count += replace_in_shape(child)
    return count


def main():
    for path in BASE.glob("build_*.py"):
        text = path.read_text(encoding="utf-8")
        if OLD in text:
            path.write_text(text.replace(OLD, NEW), encoding="utf-8")
            print("SCRIPT", path.name)

    for path in BASE.glob("*.pptx"):
        prs = Presentation(path)
        count = 0
        for slide in prs.slides:
            for shape in slide.shapes:
                count += replace_in_shape(shape)
        if count:
            prs.save(path)
            print("PPTX", path.name, count)


if __name__ == "__main__":
    main()
