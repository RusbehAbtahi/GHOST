from math import radians, sin, cos
from pathlib import Path
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt
from pptx.oxml.xmlchemy import OxmlElement

OUT = Path(__file__).with_name('GHOST_Architecture_Ring.pptx')

# ---------- palette ----------
BG = RGBColor(248, 252, 253)
RING_FILL = RGBColor(232, 246, 247)
RING_LINE = RGBColor(42, 112, 118)
SEGMENT_FILL = RGBColor(225, 243, 248)
SEGMENT_FILL_ALT = RGBColor(233, 237, 252)
SEGMENT_LINE = RGBColor(62, 124, 145)
CENTER_FILL = RGBColor(18, 104, 111)
CENTER_TEXT = RGBColor(255, 255, 255)
TEXT = RGBColor(21, 60, 73)
SUBTLE = RGBColor(88, 121, 132)

prs = Presentation()
prs.slide_width = Inches(13.333333)
prs.slide_height = Inches(7.5)
slide = prs.slides.add_slide(prs.slide_layouts[6])

# Background
bg = slide.background.fill
bg.solid()
bg.fore_color.rgb = BG

# Geometry in inches. All circular objects use exactly the same center.
cx = 6.6666665
cy = 3.75
outer_r = 3.18
ring_inner_r = 2.48
segment_outer_r = 2.70
segment_inner_r = 2.23
text_r = (segment_outer_r + segment_inner_r) / 2.0


def set_line(shape, color, width_pt=1.0):
    shape.line.color.rgb = color
    shape.line.width = Pt(width_pt)


def add_circle(radius, fill_color=None, line_color=RING_LINE, line_width=1.0):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.OVAL,
        Inches(cx - radius), Inches(cy - radius),
        Inches(2 * radius), Inches(2 * radius),
    )
    if fill_color is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill_color
    set_line(shp, line_color, line_width)
    return shp


def add_block_arc(start_deg, end_deg, outer_radius, inner_radius, fill_color, line_color=SEGMENT_LINE):
    """Create a native PowerPoint BLOCK_ARC with flat radial ends."""
    shp = slide.shapes.add_shape(
        MSO_SHAPE.BLOCK_ARC,
        Inches(cx - outer_radius), Inches(cy - outer_radius),
        Inches(2 * outer_radius), Inches(2 * outer_radius),
    )
    # python-pptx exposes the three native block-arc adjustment handles.
    # adj[0], adj[1] are angles in degrees; adj[2] is radial thickness ratio.
    shp.adjustments[0] = float(start_deg % 360)
    shp.adjustments[1] = float(end_deg % 360)
    shp.adjustments[2] = float((outer_radius - inner_radius) / outer_radius)
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill_color
    set_line(shp, line_color, 1.15)
    return shp


def add_text_warp(textbox, preset):
    """Apply native DrawingML WordArt warp; text remains editable in PowerPoint."""
    bodyPr = textbox.text_frame._txBody.bodyPr
    # Remove an existing warp if present.
    for child in list(bodyPr):
        if child.tag.endswith('prstTxWarp'):
            bodyPr.remove(child)
    warp = OxmlElement('a:prstTxWarp')
    warp.set('prst', preset)
    av = OxmlElement('a:avLst')
    warp.append(av)
    bodyPr.insert(0, warp)
    bodyPr.set('wrap', 'none')
    bodyPr.set('anchor', 'ctr')


def add_curved_text(text, start_deg, end_deg, radius, font_size=14, color=TEXT, bold=True):
    """
    Put editable WordArt on a circular arc using the SAME center/radius geometry
    as the block-arc segment. The text-box chord and sagitta are calculated from
    radius and sweep, not positioned by eye.
    """
    # Work with a positive clockwise sweep no larger than 180 degrees.
    start = start_deg % 360
    end = end_deg % 360
    sweep = (end - start) % 360
    if sweep == 0:
        sweep = 360
    if sweep > 180:
        # Use the complementary short arc for labels.
        start, end = end, start
        sweep = 360 - sweep

    mid = (start + sweep / 2.0) % 360
    half = radians(sweep / 2.0)

    chord = 2.0 * radius * sin(half)
    sagitta = radius * (1.0 - cos(half))

    # WordArt needs enough vertical room for the glyphs as well as the sagitta.
    glyph_h = max(0.26, font_size / 72.0 * 1.55)
    box_h = max(glyph_h + sagitta, glyph_h * 1.6)

    # Base text box is horizontal and centered on the chord of the desired arc.
    mid_rad = radians(mid)
    chord_center_r = radius * cos(half)
    chord_cx = cx + chord_center_r * cos(mid_rad)
    chord_cy = cy + chord_center_r * sin(mid_rad)

    x = chord_cx - chord / 2.0
    y = chord_cy - box_h / 2.0

    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(chord), Inches(box_h))
    tf = tb.text_frame
    tf.clear()
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = text
    run.font.name = 'Arial'
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = color

    # Keep text readable: upper hemisphere uses arch-up; lower hemisphere arch-down.
    if 0 <= mid < 180:
        preset = 'textArchDown'
        rotation = mid - 90.0
    else:
        preset = 'textArchUp'
        rotation = mid + 90.0

    add_text_warp(tb, preset)
    tb.rotation = rotation % 360
    return tb


def add_label_box(x, y, w, h, title, subtitle=None, fill=RGBColor(245, 251, 252)):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    set_line(shp, SEGMENT_LINE, 1.0)
    tf = shp.text_frame
    tf.clear(); tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = title; r.font.name = 'Arial'; r.font.size = Pt(13); r.font.bold = True; r.font.color.rgb = TEXT
    if subtitle:
        p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
        r2 = p2.add_run(); r2.text = subtitle; r2.font.name = 'Arial'; r2.font.size = Pt(8); r2.font.color.rgb = SUBTLE
    return shp


# ---------- concentric ring system ----------
add_circle(outer_r, RING_FILL, RING_LINE, 1.2)
add_circle(ring_inner_r, BG, RING_LINE, 1.0)

# Outer title along the ring
add_curved_text('HUMAN-CONTROLLED GHOST ORCHESTRATION', 205, 335, 3.00, font_size=15, color=RING_LINE, bold=True)

# Six native curved boxes inside one ring. Ends are FLAT because these are BLOCK_ARC shapes.
segments = [
    (205, 250, 'AI Client ChatGPT', SEGMENT_FILL_ALT),
    (255, 300, 'MCP Interface / Server', SEGMENT_FILL),
    (305, 350, 'AI Client Claude', SEGMENT_FILL_ALT),
    (10, 55, 'Skills / Tools', SEGMENT_FILL),
    (60, 105, 'Memory / Knowledge', SEGMENT_FILL),
    (110, 155, 'GHOST GUI', SEGMENT_FILL),
    (160, 200, 'Blackboard', SEGMENT_FILL),
]

for start, end, label, fill in segments:
    add_block_arc(start, end, segment_outer_r, segment_inner_r, fill)
    add_curved_text(label, start + 3, end - 3, text_r, font_size=12.5, color=TEXT, bold=True)

# Center backend
center = slide.shapes.add_shape(
    MSO_SHAPE.OVAL,
    Inches(cx - 1.02), Inches(cy - 1.02), Inches(2.04), Inches(2.04)
)
center.fill.solid(); center.fill.fore_color.rgb = CENTER_FILL
set_line(center, RGBColor(255, 255, 255), 1.5)
tf = center.text_frame; tf.clear(); tf.vertical_anchor = MSO_ANCHOR.MIDDLE
p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
r = p.add_run(); r.text = 'GHOST Backend'; r.font.name = 'Arial'; r.font.size = Pt(18); r.font.bold = True; r.font.color.rgb = CENTER_TEXT
p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
r2 = p2.add_run(); r2.text = 'Deterministic Orchestrator'; r2.font.name = 'Arial'; r2.font.size = Pt(9); r2.font.color.rgb = CENTER_TEXT
p3 = tf.add_paragraph(); p3.alignment = PP_ALIGN.CENTER
r3 = p3.add_run(); r3.text = 'secure • extensible • traceable'; r3.font.name = 'Arial'; r3.font.size = Pt(7.5); r3.font.color.rgb = CENTER_TEXT

# Small internal support boxes, kept native and editable.
add_label_box(5.18, 2.52, 1.22, 0.52, 'AI Agents')
add_label_box(6.93, 2.52, 1.22, 0.52, 'MCP Tools')
add_label_box(4.98, 3.49, 1.40, 0.54, 'Knowledge Graph')
add_label_box(6.95, 3.49, 1.40, 0.54, 'Skills')
add_label_box(5.18, 4.44, 1.22, 0.52, 'Documents')
add_label_box(6.93, 4.44, 1.22, 0.52, 'Audit')

# Title / note outside the diagram.
title = slide.shapes.add_textbox(Inches(0.45), Inches(0.18), Inches(4.5), Inches(0.55))
tf = title.text_frame; tf.clear()
p = tf.paragraphs[0]
r = p.add_run(); r.text = 'GHOST Architecture — Native PowerPoint Ring'; r.font.name = 'Arial'; r.font.size = Pt(20); r.font.bold = True; r.font.color.rgb = TEXT

note = slide.shapes.add_textbox(Inches(0.47), Inches(6.93), Inches(5.8), Inches(0.30))
tf = note.text_frame; tf.clear()
p = tf.paragraphs[0]
r = p.add_run(); r.text = 'Curved boxes: native BLOCK_ARC • Curved labels: editable DrawingML WordArt'; r.font.name = 'Arial'; r.font.size = Pt(8.5); r.font.color.rgb = SUBTLE

prs.save(OUT)
print(OUT)
