#!/usr/bin/env python3
"""BMP -> PNG converter (stdlib only). Supports crop + upscale to zoom in on a UI
region when locating click targets, plus an absolute-coordinate ruler grid and a
crosshair so that click coordinates can be read straight off the image instead of
being estimated from a scaled-down thumbnail.

Usage:
  python bmp2png.py in.bmp out.png
  python bmp2png.py in.bmp out.png X Y W H [SCALE]
  python bmp2png.py in.bmp out.png X Y W H [SCALE] --grid [STEP] [--cross CX CY]

X Y W H are in image pixel coords (origin top-left). SCALE is an integer
nearest-neighbour zoom (default 1).

--grid STEP   overlay ruler lines aligned to ABSOLUTE multiples of STEP
              (default 50). Every 100th line is red + labelled with its absolute
              coordinate, so a target's screen position can be read directly.
--cross CX CY draw a cyan crosshair at absolute point (CX, CY) to verify a target.
"""
import sys, struct, zlib

# --- minimal 3x5 bitmap font (digits + '-') for grid labels -------------------
_GLYPH = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "-": ("000", "000", "111", "000", "000"),
}


def _put(rows, W, H, x, y, rgb, thickness=1):
    """Set pixel (x, y) in-place, bounds-checked."""
    for dy in range(thickness):
        for dx in range(thickness):
            xx, yy = x + dx, y + dy
            if 0 <= xx < W and 0 <= yy < H:
                o = xx * 3
                rows[yy][o:o + 3] = bytes(rgb)


def draw_text(rows, W, H, text, x, y, rgb, size=2):
    """Draw a string using the 3x5 font, each font pixel blown up to `size`."""
    cx = x
    for ch in text:
        g = _GLYPH.get(ch)
        if g is None:
            cx += 4 * size
            continue
        for gy, line in enumerate(g):
            for gx, bit in enumerate(line):
                if bit == "1":
                    for sy in range(size):
                        for sx in range(size):
                            _put(rows, W, H, cx + gx * size + sx, y + gy * size + sy, rgb)
        cx += 4 * size
    return cx


def draw_grid(rows, W, H, ox, oy, scale, step):
    """Ruler lines at ABSOLUTE multiples of `step`.

    (ox, oy) = absolute coord of the crop's top-left corner. Every line whose
    absolute coordinate is a multiple of 2*step is drawn red and labelled.
    """
    minor, major = (170, 190, 210), (230, 60, 60)
    xs = [ax for ax in range(-(-ox // step) * step, ox + W // scale + 1, step)]
    ys = [ay for ay in range(-(-oy // step) * step, oy + H // scale + 1, step)]
    for ax in xs:
        px = (ax - ox) * scale
        is_major = ax % (step * 2) == 0
        for t in range(2 if is_major else 1):
            for yy in range(H):
                _put(rows, W, H, px + t, yy, major if is_major else minor)
        if is_major:
            draw_text(rows, W, H, str(ax), px + 3, 3, major, size=2)
    for ay in ys:
        py = (ay - oy) * scale
        is_major = ay % (step * 2) == 0
        for t in range(2 if is_major else 1):
            for xx in range(W):
                _put(rows, W, H, xx, py + t, major if is_major else minor)
        if is_major:
            draw_text(rows, W, H, str(ay), 3, py + 3, major, size=2)


def draw_cross(rows, W, H, ox, oy, scale, ax, ay, arm=14, gap=4):
    """Cyan crosshair at ABSOLUTE (ax, ay) with a gap at the centre."""
    rgb = (0, 165, 220)
    px, py = (ax - ox) * scale, (ay - oy) * scale
    for d in range(gap, arm + 1):
        for t in range(2):
            _put(rows, W, H, px + d, py + t, rgb)
            _put(rows, W, H, px - d, py + t, rgb)
            _put(rows, W, H, px + t, py + d, rgb)
            _put(rows, W, H, px + t, py - d, rgb)


def read_bmp(path):
    with open(path, "rb") as f:
        data = f.read()
    assert data[0:2] == b"BM", "not a BMP file"
    off = struct.unpack("<I", data[10:14])[0]
    w = struct.unpack("<i", data[18:22])[0]
    h = struct.unpack("<i", data[22:26])[0]
    bits = struct.unpack("<H", data[28:30])[0]
    comp = struct.unpack("<I", data[30:34])[0]
    assert comp == 0, "only BI_RGB (uncompressed) BMP supported"
    assert bits in (24, 32), "only 24/32-bit BMP supported"
    H = abs(h)
    bottom_up = h > 0
    rowb = w * (bits // 8)
    rowp = (rowb + 3) & ~3
    px = data[off:]
    rows = []
    for y in range(H):
        sy = (H - 1 - y) if bottom_up else y
        src = px[sy * rowp: sy * rowp + rowb]
        row = bytearray(w * 3)
        if bits == 24:
            for x in range(w):
                row[x * 3] = src[x * 3 + 2]
                row[x * 3 + 1] = src[x * 3 + 1]
                row[x * 3 + 2] = src[x * 3]
        else:  # 32-bit BGRA
            for x in range(w):
                row[x * 3] = src[x * 4 + 2]
                row[x * 3 + 1] = src[x * 4 + 1]
                row[x * 3 + 2] = src[x * 4]
        rows.append(row)
    return w, H, rows


def write_png(path, w, h, rows):
    def chunk(t, b):
        c = t + b
        return struct.pack(">I", len(b)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = bytearray()
    for r in rows:
        raw.append(0)
        raw.extend(r)
    idat = zlib.compress(bytes(raw), 9)
    with open(path, "wb") as f:
        f.write(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def crop_scale(rows, W, H, x, y, w, h, scale):
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = min(w, W - x)
    h = min(h, H - y)
    out = []
    for yy in range(h):
        src = rows[y + yy]
        line = bytearray()
        for xx in range(w):
            p = src[(x + xx) * 3:(x + xx) * 3 + 3]
            line.extend(p * scale)
        for _ in range(scale):
            out.append(line)
    return w * scale, h * scale, out


if __name__ == "__main__":
    argv = sys.argv[1:]
    grid_step = None
    cross = None
    if "--grid" in argv:
        i = argv.index("--grid")
        argv.pop(i)
        if i < len(argv) and argv[i].isdigit():
            grid_step = int(argv.pop(i))
        else:
            grid_step = 50
    if "--cross" in argv:
        i = argv.index("--cross")
        argv.pop(i)
        cross = (int(argv.pop(i)), int(argv.pop(i)))

    src, dst = argv[0], argv[1]
    W, H, rows = read_bmp(src)
    if len(argv) >= 6:
        x, y, w, h = (int(v) for v in argv[2:6])
        scale = int(argv[6]) if len(argv) >= 7 else 1
        ow, oh, orows = crop_scale(rows, W, H, x, y, w, h, scale)
        ox, oy = x, y
    else:
        ow, oh, orows = W, H, rows
        scale, ox, oy = 1, 0, 0
    if grid_step:
        draw_grid(orows, ow, oh, ox, oy, scale, grid_step)
    if cross:
        draw_cross(orows, ow, oh, ox, oy, scale, cross[0], cross[1])
    write_png(dst, ow, oh, orows)
    print("wrote", dst, ow, "x", oh, ("grid=%d" % grid_step) if grid_step else "", ("cross=%s" % (cross,)) if cross else "")
