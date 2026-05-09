from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import math

# 1. 创建画布
# 180x180 pixels, RGBA mode (transparent background support, though we will fill it)
width, height = 180, 180
# 背景色：温暖的阳光黄 (#FFF9C4 - Light Yellow / Cream)
bg_color = (255, 249, 196)
# 辅助色：柔和的天空蓝 (#B3E5FC - Light Blue) for accents
accent_color = (179, 229, 252)
# 主题色：活泼的橙红色 (#FF7043 - Deep Orange) for text
text_color = (255, 112, 67)
# 线条粗细
stroke_width = 12

img = Image.new('RGB', (width, height), bg_color)
draw = ImageDraw.Draw(img)

# 2. 绘制背景元素：阳光与云朵
# 右上角的大太阳 (Sun) - 温暖
sun_center = (150, 40)
sun_radius = 40
sun_color = (255, 213, 79) # Amber
draw.ellipse(
    [sun_center[0]-sun_radius, sun_center[1]-sun_radius, sun_center[0]+sun_radius, sun_center[1]+sun_radius], 
    fill=sun_color, outline=None
)

# 左下角的云朵 (Cloud) - 无忧无虑
# 使用几个圆叠加
cloud_color = (255, 255, 255) # White
cloud_circles = [
    (30, 140, 25),
    (60, 130, 35),
    (90, 140, 25),
]
for cx, cy, r in cloud_circles:
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=cloud_color, outline=None)


# 3. 绘制文字 "kdx"
# 由于没有现成的可爱字体，手动绘制圆润的几何线条
# 坐标系统：中心 y=90
# 字体高度：约 50px

# K
# 竖线 (x=30, y=60 to 120)
draw.line([(30, 60), (30, 120)], fill=text_color, width=stroke_width, joint='curve')
# 上斜线 (x=30, y=90 to 60, 60)
draw.line([(30, 95), (60, 65)], fill=text_color, width=stroke_width, joint='curve')
# 下斜线 (x=30, y=90 to 60, 120)
draw.line([(30, 95), (60, 120)], fill=text_color, width=stroke_width, joint='curve')

# D
# 竖线 (x=100, y=50 to 120) (ascender goes higher)
draw.line([(100, 50), (100, 120)], fill=text_color, width=stroke_width, joint='curve')
# 圆肚 (center x=80, y=100, radius=20)
# draw.ellipse outline is tricky with heavy stroke, using arc
# 绘制 d 的左半圆弧
# Bounding box: [60, 80, 100, 120]
draw.arc([60, 80, 100, 120], 90, 270, fill=text_color, width=stroke_width)
# 补全 d 的连接线
# draw.line([(100, 80), (100, 120)], fill=text_color, width=stroke_width) # Covered by vertical line

# X
# 左上到右下 (x=120, y=70 to 160, 110)
draw.line([(120, 70), (160, 110)], fill=text_color, width=stroke_width, joint='curve')
# 右上到左下 (x=160, y=70 to 120, 110)
draw.line([(160, 70), (120, 110)], fill=text_color, width=stroke_width, joint='curve')

# 4. 绘制微笑 (Smile) - 温馨
# 在底部中央画一个弧线
smile_box = [60, 130, 120, 150]
draw.arc(smile_box, 0, 180, fill=text_color, width=6)

# 5. 保存
output_path = r'c:\Users\konglingwen\code\django-vue-docker\kdx-fe\public\apple-touch-icon.png'
img.save(output_path)
print(f"Icon generated at: {output_path}")
