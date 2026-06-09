"""Generate the README header graphic in the Factor-AI design language."""
from PIL import Image, ImageDraw, ImageFont

W, H = 1086, 1338
WHITE = (255, 255, 255)
BLACK = (26, 26, 26)
ORANGE = (224, 116, 7)
TEAL = (14, 129, 116)
GREEN = (48, 147, 65)
AMBER = (237, 194, 99)
INDIGO = (64, 41, 155)
INDIGO2 = (59, 63, 158)
RED = (192, 57, 43)
GRAY = (158, 158, 158)
LGRAY = (218, 218, 218)

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans"
LIB = "/usr/share/fonts/truetype/liberation/LiberationSans"
def font(size, bold=False, italic=False):
    if italic:
        path = LIB + ("-BoldItalic" if bold else "-Italic") + ".ttf"
    else:
        path = DEJAVU + ("-Bold" if bold else "") + ".ttf"
    return ImageFont.truetype(path, size)

img = Image.new("RGB", (W, H), WHITE)
d = ImageDraw.Draw(img)

def ctext(cx, y, text, fnt, fill, anchor="mm"):
    d.text((cx, y), text, font=fnt, fill=fill, anchor=anchor)

def rbox(x0, y0, x1, y1, fill, radius=10, outline=None, width=2):
    d.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill,
                        outline=outline, width=width)

def dashed_rect(x0, y0, x1, y1, color, dash=10, gap=7, width=3):
    def dashed_line(p0, p1):
        import math
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        length = math.hypot(dx, dy)
        n = int(length // (dash + gap)) + 1
        ux, uy = dx / length, dy / length
        for i in range(n):
            s = i * (dash + gap)
            e = min(s + dash, length)
            d.line([(p0[0] + ux * s, p0[1] + uy * s),
                    (p0[0] + ux * e, p0[1] + uy * e)], fill=color, width=width)
    dashed_line((x0, y0), (x1, y0))
    dashed_line((x1, y0), (x1, y1))
    dashed_line((x1, y1), (x0, y1))
    dashed_line((x0, y1), (x0, y0))

def arrow(x, y0, y1, color=BLACK, width=3, head=9):
    d.line([(x, y0), (x, y1 - head)], fill=color, width=width)
    d.polygon([(x - head + 2, y1 - head), (x + head - 2, y1 - head), (x, y1)],
              fill=color)

CX = W // 2

# ---- Title ----
ctext(CX, 38, "DETERMINISTIC AGENT HARNESS", font(40, bold=True), BLACK)
ctext(CX, 80, "Deterministic AI Agent Runtime Platform", font(20), BLACK)

# ---- User / LLM pill ----
rbox(CX - 130, 108, CX + 130, 152, INDIGO, radius=22)
ctext(CX, 130, "User / LLM Client", font(19, bold=True), WHITE)
arrow(CX, 152, 192)

# ---- Container 1: validation & routing ----
C1_T, C1_B = 192, 652
dashed_rect(28, C1_T, W - 28, C1_B, INDIGO2)
rbox(CX - 280, C1_T - 16, CX + 280, C1_T + 16, INDIGO2, radius=8)
ctext(CX, C1_T, "INTENT VALIDATION & STATIC ROUTING", font(18, bold=True), WHITE)

# Governor box (orange)
rbox(95, 250, W - 95, 342, ORANGE, radius=12)
ctext(CX, 278, "~ Governor FSM (Static TRANSITIONS) ~", font(23, bold=True), WHITE)
ctext(CX, 312, "Resolves every state transition from a table frozen at import time,",
      font(15, italic=True), WHITE)
ctext(CX, 330, "the LLM never selects an edge", font(15, italic=True), WHITE)

# arrows to three green boxes
for gx in (208, CX, W - 208):
    d.line([(CX, 342), (CX, 375)], fill=BLACK, width=3)
    d.line([(208, 375), (W - 208, 375)], fill=BLACK, width=3)
    arrow(gx, 375, 408)

greens = [
    (62, 354, "~ Validation Gate ~",
     ["Pydantic v2 envelope,", 'extra="forbid", closed', "intent enum, bounded", "confidence"]),
    (412, 704, "~ Static Routing ~",
     ["Complete intent to", "workflow map, built", "once, no improvised", "routes"]),
    (762, 1054, "~ Typed Halts ~",
     ["schema_violation,", "unsupported_intent,", "illegal_transition,", "step_failure, dry_run_block"]),
]
for x0, x1, title, lines in greens:
    rbox(x0, 408, x1, 560, GREEN, radius=12)
    cx = (x0 + x1) // 2
    ctext(cx, 432, title, font(18, bold=True), WHITE)
    for i, line in enumerate(lines):
        ctext(cx, 468 + i * 22, line, font(14, italic=True), WHITE)

arrow(CX, 580, 652 + 38)
ctext(CX + 12, 600, "validated IntentEnvelope only", font(13, italic=True), BLACK,
      anchor="lm")

# ---- Container 2: dry-run & flight recorder harness ----
C2_T, C2_B = 690, 1058
dashed_rect(28, C2_T, W - 28, C2_B, RED)
rbox(CX - 300, C2_T - 16, CX + 300, C2_T + 16, INDIGO2, radius=8)
ctext(CX, C2_T, "DRY-RUN SAFETY & FLIGHT RECORDER HARNESS", font(18, bold=True), WHITE)

inner = [
    (62, 354, RED, WHITE, "~ DRY_RUN Gate ~",
     ["Armed by default,", "only the literal", '"false" disarms it']),
    (412, 704, AMBER, BLACK, "~ Side-Effect Block ~",
     ["side_effectful steps", "halt with dry_run_block", "before invocation"]),
    (762, 1054, AMBER, BLACK, "~ Flight Recorder ~",
     ["Append-only JSONL,", "SHA-256 hash chain,", "verify() tamper check"]),
]
for x0, x1, fill, tcol, title, lines in inner:
    rbox(x0, 728, x1, 856, fill, radius=12)
    cx = (x0 + x1) // 2
    ctext(cx, 752, title, font(18, bold=True), tcol)
    for i, line in enumerate(lines):
        ctext(cx, 788 + i * 22, line, font(14, italic=True), tcol)
    arrow(cx, 856, 894)

# teal wide bar
rbox(62, 894, W - 62, 944, TEAL, radius=10)
ctext(CX, 919, "Governor  ~  checks gate + legal transitions before every step",
      font(19, bold=True), WHITE)
arrow(CX, 944, 982)

# audit bar inside container 2
rbox(62, 982, W - 62, 1032, ORANGE, radius=10)
ctext(CX, 1007, "Immutable Audit Trail  ~  every input, transition, output, halt",
      font(19, bold=True), WHITE)

arrow(CX, 1058, 1108)

# ---- Workflow bar ----
rbox(95, 1108, W - 95, 1158, INDIGO, radius=10)
ctext(CX, 1133, "Example Compliance Workflow", font(21, bold=True), WHITE)

# arrows to three white boxes
d.line([(CX, 1158), (CX, 1186)], fill=BLACK, width=3)
d.line([(208, 1186), (W - 208, 1186)], fill=BLACK, width=3)
for gx in (208, CX, W - 208):
    arrow(gx, 1186, 1212)

bottoms = [
    (62, 354, "Validate", ["Pydantic gate,", "regex-pinned record"]),
    (412, 704, "Transform", ["Static 10,000.00", "review threshold"]),
    (762, 1054, "Persist", ["artifacts/ only,", "blocked under dry run"]),
]
for x0, x1, title, lines in bottoms:
    rbox(x0, 1212, x1, 1310, WHITE, radius=12, outline=GRAY, width=3)
    cx = (x0 + x1) // 2
    ctext(cx, 1238, title, font(18, bold=True), BLACK)
    for i, line in enumerate(lines):
        ctext(cx, 1268 + i * 20, line, font(14, italic=True), BLACK)

img.save("/home/user/Deterministic-Agent-Harness/docs/header.png")
print("saved")
