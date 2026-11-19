"""Render a .war matrix glyph grid to a standalone SVG.

Lit pixels are drawn as horizontal runs of one colour; a pattern overlay draws the
dark pixel gaps so the result reads as an LED matrix while staying small.
"""
PAL = {"W": "#F4F4F0", "A": "#FFB000", "R": "#E8202A", "G": "#2BD34F"}

def war_to_svg(rows, cell=10):
    h = len(rows)
    w = max((len(r) for r in rows), default=0)
    disp = min(320, max(w * cell, 96))
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img">'
           % (w * cell, h * cell, disp, round(disp * h / max(w, 1))),
           '<defs><pattern id="px" width="%d" height="%d" patternUnits="userSpaceOnUse">'
           '<path d="M0 0H%d V%d" fill="none" stroke="#000" stroke-width="%g"/></pattern></defs>'
           % (cell, cell, cell, cell, cell * 0.3),
           '<rect width="%d" height="%d" fill="#202024"/>' % (w * cell, h * cell)]
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            c = row[x]
            x2 = x
            while x2 < len(row) and row[x2] == c:
                x2 += 1
            if c in PAL:
                out.append('<rect x="%d" y="%d" width="%d" height="%d" fill="%s"/>' % (x * cell, y * cell, (x2 - x) * cell, cell, PAL[c]))
            x = x2
    out.append('<rect width="%d" height="%d" fill="url(#px)"/></svg>' % (w * cell, h * cell))
    return "".join(out) + "\n"
