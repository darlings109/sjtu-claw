"""生成 SJTUClaw 启动器图标

纯 stdlib 手写 ICO：不引入 Pillow 依赖（项目只有 requests / python-dotenv）。
造型为三道爪痕 + 环形轮廓，深底蓝紫渐变，呼应 Web UI 的 accent 色。
"""

import math
import os
import struct

SIZES = [16, 24, 32, 48, 64, 128, 256]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sjtuclaw.ico")

BG_TOP = (32, 30, 58)
BG_BOTTOM = (18, 18, 32)
ACCENT = (124, 127, 240)
CYAN = (79, 195, 247)


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def blend(dst, src, alpha):
    return tuple(round(d + (s - d) * alpha) for d, s in zip(dst, src))


def smoothstep(edge0, edge1, x):
    if edge1 == edge0:
        return 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)


def bezier(p0, p1, p2, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def sample_stroke(p0, p1, p2, steps=140):
    """把二次贝塞尔离散成点列，同时给出每点的锥度系数"""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x, y = bezier(p0, p1, p2, t)
        # 起笔略钝、收笔成尖，避免两端对称显得像叶片
        taper = (1 - t) ** 0.85 * (1 - (1 - t) ** 6)
        pts.append((x, y, t, taper))
    return pts


def dist_to_stroke(px, py, pts, base_w, ss):
    """返回该点落在爪痕上的覆盖度与沿线位置"""
    best_d = float("inf")
    best_t = 0.0
    best_w = 0.0
    for x, y, t, taper in pts:
        d = math.hypot(px - x, py - y)
        w = base_w * taper
        if w <= 0.01:
            continue
        # 用 d - w/2 归一化，取最贴合的一段
        edge = d - w * 0.5
        if edge < best_d:
            best_d = edge
            best_t = t
            best_w = w
    if best_w <= 0.01:
        return 0.0, 0.0
    return 1.0 - smoothstep(0.0, ss * 0.9, best_d), best_t


def render(size):
    """返回 BGRA 像素，4x 超采样抗锯齿"""
    ss = 4
    n = size * ss
    acc = [[[0.0] * 4 for _ in range(n)] for _ in range(n)]

    cx = cy = n / 2
    outer = n * 0.46
    ring_r = n * 0.40
    ring_w = max(n * 0.035, 1.0)

    # 三道平行斜爪痕：左下 → 右上，逐条外扩
    strokes = []
    for i in range(3):
        k = i - 1  # -1 / 0 / 1
        dx = k * n * 0.185
        dy = k * n * 0.150
        p0 = (cx - n * 0.24 + dx, cy + n * 0.20 + dy)
        p1 = (cx - n * 0.02 + dx, cy - n * 0.02 + dy)
        p2 = (cx + n * 0.22 + dx, cy - n * 0.24 + dy)
        strokes.append(sample_stroke(p0, p1, p2))
    claw_w = max(n * 0.075, 1.2)

    for y in range(n):
        for x in range(n):
            px, py = x + 0.5, y + 0.5
            r = math.hypot(px - cx, py - cy)

            # 圆形底盘 + 垂直渐变
            inside = 1.0 - smoothstep(outer - ss, outer, r)
            if inside <= 0.0:
                continue
            base = lerp(BG_TOP, BG_BOTTOM, y / n)
            color = list(base)
            alpha = inside

            # 外环
            d_ring = abs(r - ring_r)
            ring_a = (1.0 - smoothstep(ring_w * 0.5, ring_w * 0.5 + ss, d_ring)) * 0.55
            if ring_a > 0:
                color = list(blend(color, ACCENT, ring_a))

            # 爪痕：起笔偏青、收笔偏紫
            for pts in strokes:
                ca, t = dist_to_stroke(px, py, pts, claw_w, ss)
                if ca > 0:
                    color = list(blend(color, lerp(CYAN, ACCENT, t), ca))

            acc[y][x] = [color[0], color[1], color[2], alpha * 255]

    # 降采样
    out = bytearray()
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            rs = gs = bs = as_ = 0.0
            for dy in range(ss):
                for dx in range(ss):
                    p = acc[y * ss + dy][x * ss + dx]
                    a = p[3] / 255.0
                    rs += p[0] * a
                    gs += p[1] * a
                    bs += p[2] * a
                    as_ += a
            k = ss * ss
            if as_ > 0:
                r = round(rs / as_)
                g = round(gs / as_)
                b = round(bs / as_)
            else:
                r = g = b = 0
            a = round(as_ / k * 255)
            row += bytes((b, g, r, a))  # BGRA
        rows.append(row)
    for row in reversed(rows):  # DIB 自底向上
        out += row
    return bytes(out)


def build():
    images = []
    for s in SIZES:
        pixels = render(s)
        header = struct.pack(
            "<IiiHHIIiiII",
            40, s, s * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0,
        )
        mask_row = ((s + 31) // 32) * 4
        mask = bytes(mask_row * s)
        images.append(header + pixels + mask)

    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    offset = 6 + 16 * len(images)
    for s, data in zip(SIZES, images):
        dim = 0 if s >= 256 else s
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for data in images:
        out += data

    with open(OUT, "wb") as f:
        f.write(bytes(out))
    print(f"已生成 {OUT} ({len(out)} bytes, {len(SIZES)} 种尺寸)")


if __name__ == "__main__":
    build()
