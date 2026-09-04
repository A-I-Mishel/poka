import uuid
from langchain.tools import tool
from pptx import Presentation
from pptx.util import Inches


@tool
def create_pptx(topic: str, content: str) -> str:
    """Create a PowerPoint presentation.

    Args:
        topic: Presentation title shown on the title slide.
        content: Slide text separated by double newlines. Each block's first
            line is the slide title, remaining lines are bullet points.

    Returns:
        Filename of the saved presentation.
    """
    try:
        prs: Presentation = Presentation()

        title_slide = prs.slides.add_slide(prs.slide_layouts[0])
        title_slide.shapes.title.text = topic

        slides_content: list[str] = content.strip().split("\n\n")
        for slide_text in slides_content:
            if not slide_text.strip():
                continue
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            lines: list[str] = slide_text.strip().split("\n")
            slide.shapes.title.text = lines[0].lstrip("- ").strip() if lines else "Slide"
            bullets: list[str] = [ln.lstrip("- ").strip() for ln in lines[1:] if ln.strip()]
            if not bullets:
                continue
            try:
                body = slide.placeholders[1].text_frame
                body.clear()
                body.paragraphs[0].text = bullets[0]
                for line in bullets[1:]:
                    p = body.add_paragraph()
                    p.text = line
                    p.level = 0
            except (IndexError, KeyError, AttributeError):
                # Fallback: add a textbox if the layout has no body placeholder.
                left = top = Inches(1)
                width = Inches(8)
                height = Inches(4)
                textbox = slide.shapes.add_textbox(left, top, width, height)
                tf = textbox.text_frame
                tf.text = bullets[0]
                for line in bullets[1:]:
                    p = tf.add_paragraph()
                    p.text = f"\u2022 {line}"
                    p.level = 0

        filename: str = f"pptx_{uuid.uuid4().hex[:8]}.pptx"
        prs.save(filename)
        return f"Presentation saved as {filename}"
    except Exception as e:
        return f"Error creating presentation: {str(e)}"
