# -*- coding: utf-8 -*-
"""生成 800x480 开机 Coca-Cola 图 与 冷酸灵静态图（以及 /dev/fb0 原始 BGRA 数据）"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

W, H = 800, 480
OUT = r"g:\lcd\bootimg"
FONT_BD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_RG = r"C:\Windows\Fonts\msyh.ttc"

def font(path, size):
    return ImageFont.truetype(path, size)

def text_spaced(draw, xy, text, fnt, fill, spacing=0, anchor_center_x=None):
    """带字间距的文本绘制；anchor_center_x 给定时整体水平居中"""
    widths = [draw.textlength(ch, font=fnt) for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = (anchor_center_x - total / 2) if anchor_center_x is not None else xy[0]
    y = xy[1]
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += w + spacing

# ---------- 1. 可口可乐开机图 ----------
def make_cola():
    # 背景：可口可乐红 + 轻微径向渐变
    base = Image.new("RGB", (W, H), (244, 0, 9))
    grad = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(grad)
    for y in range(H):
        v = int(18 * (1 - abs(y - H * 0.42) / (H * 0.58)))
        gd.line([(0, y), (W, y)], fill=max(0, v))
    dark = Image.new("RGB", (W, H), (196, 0, 6))
    base = Image.composite(dark, base, grad.point(lambda p: int(p * 0.55)))

    # 白色 Coca-Cola 手写 logo（来自 simple-icons，黑色渲染后取反做蒙版）
    src = Image.open(os.path.join(OUT, "cola_edge.png")).convert("L")
    bbox = src.point(lambda p: 255 if p < 245 else 0).getbbox()
    logo = src.crop(bbox)
    logo_w = 620
    logo_h = int(logo.height * logo_w / logo.width)
    logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
    mask = logo.point(lambda p: 255 - p)  # 黑色笔画 -> 不透明

    img = base.copy()
    lx = (W - logo_w) // 2
    ly = int(H * 0.30) - logo_h // 2 + 30
    white = Image.new("RGB", logo.size, (255, 255, 255))
    img.paste(white, (lx, ly), mask)

    d = ImageDraw.Draw(img)
    # 中线装饰
    cy = ly + logo_h + 30
    d.line([(W//2 - 200, cy), (W//2 + 200, cy)], fill=(255, 255, 255), width=2)
    # 中文名
    f_cn = font(FONT_BD, 44)
    text_spaced(d, (0, cy + 18), "可口可乐", f_cn, (255, 255, 255), spacing=14, anchor_center_x=W/2)
    f_en = font(FONT_RG, 18)
    text_spaced(d, (0, cy + 84), "C O C A - C O L A", f_en, (255, 235, 235), spacing=3, anchor_center_x=W/2)

    img.save(os.path.join(OUT, "boot_cola_800x480.png"))
    return img

# ---------- 2. 冷酸灵静态图 ----------
def make_lesening():
    split = 428  # 左侧渐变区宽度
    # 左侧渐变背景
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    top = (226, 243, 255)
    bottom = (247, 252, 255)
    for y in range(H):
        t = y / (H - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (split, y)], fill=c)

    # 左侧装饰圆
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    dd.ellipse([-170, -210, 250, 210], fill=(198, 232, 252, 150))
    dd.ellipse([-130, 330, 230, 690], fill=(206, 240, 240, 100))
    dd.ellipse([300, 300, 560, 560], fill=(186, 227, 250, 90))
    deco = deco.filter(ImageFilter.GaussianBlur(3))
    img = Image.alpha_composite(img.convert("RGBA"), deco).convert("RGB")

    # 左右分割的细微阴影
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for i in range(12):
        sd.line([(split + i, 0), (split + i, H)], fill=(120, 160, 200, max(0, 26 - i * 2)))
    img = Image.alpha_composite(img.convert("RGBA"), shade).convert("RGB")

    # 左侧文案
    d = ImageDraw.Draw(img)
    navy = (18, 60, 140)
    teal = (11, 150, 150)
    grey = (110, 122, 138)

    d.rectangle([52, 100, 62, 156], fill=(226, 32, 40))
    f1 = font(FONT_BD, 50)
    d.text((80, 96), "冷酸灵牙膏", font=f1, fill=navy)

    f2 = font(FONT_RG, 25)
    d.text((82, 170), "专研抗敏  ·  医研修护", font=f2, fill=teal)

    f3 = font(FONT_RG, 19)
    d.text((82, 216), "科学护龈  缓解牙齿敏感", font=f3, fill=grey)

    # 底部品牌行
    d.line([(52, 360), (300, 360)], fill=(198, 218, 234), width=2)
    f4 = font(FONT_BD, 24)
    d.text((52, 380), "冷酸灵", font=f4, fill=navy)
    f5 = font(FONT_RG, 16)
    d.text((148, 388), "LESENING", font=f5, fill=grey)

    # 右侧产品图（源图为白底，正好与右侧纯白区域融合）
    prod = Image.open(os.path.join(OUT, "src1.png")).convert("RGB")
    prod = prod.crop((80, 144, 338, 232))  # 只保留产品盒主体，排除倒影与接缝暗影
    target_w = 350
    prod = prod.resize((target_w, int(prod.height * target_w / prod.width)), Image.LANCZOS)

    px = split + (W - split - target_w) // 2
    py = (H - prod.height) // 2 + 6

    # 产品底部柔和投影
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shd = ImageDraw.Draw(sh)
    shd.ellipse([px + 20, py + prod.height - 14, px + target_w - 20, py + prod.height + 26],
                fill=(90, 120, 150, 70))
    sh = sh.filter(ImageFilter.GaussianBlur(8))
    img = Image.alpha_composite(img.convert("RGBA"), sh)
    img.paste(prod, (px, py))
    img = img.convert("RGB")

    img.save(os.path.join(OUT, "post_lesening_800x480.png"))
    return img

def save_fb(img, name):
    """转换为 /dev/fb0 需要的 32bpp BGRA 原始数据（屏幕实际按 B,G,R,A 取字节）"""
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    a = Image.new("L", rgba.size, 255)
    out = Image.merge("RGBA", (b, g, r, a)).tobytes()
    path = os.path.join(OUT, name)
    with open(path, "wb") as f:
        f.write(out)
    print(name, len(out))

if __name__ == "__main__":
    cola = make_cola()
    les = make_lesening()
    save_fb(cola, "cola.fb")
    save_fb(les, "lesening.fb")
    print("done")
