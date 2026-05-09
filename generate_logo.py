from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import math

# 1. 创建画布
# 180x180 pixels
width, height = 180, 180
# 背景色：清新的天空蓝 (#81D4FA - Light Blue)
bg_color = (129, 212, 250)
# 文字颜色：粉嫩色系
color_k = (255, 238, 88)  # Yellow
color_d = (248, 187, 208) # Pink
color_x = (225, 190, 231) # Purple

img = Image.new('RGB', (width, height), bg_color)
draw = ImageDraw.Draw(img)

# 2. 绘制背景气泡 (Bubbles)
# 使用半透明白色圆圈模拟气泡
bubble_color = (255, 255, 255, 100) # White with transparency
# 需要创建一个 RGBA 图层来画透明气泡
overlay = Image.new('RGBA', (width, height), (0,0,0,0))
overlay_draw = ImageDraw.Draw(overlay)

bubbles = [
    (20, 20, 15),
    (160, 30, 10),
    (150, 150, 20),
    (30, 160, 12),
    (90, 10, 8),
    (100, 170, 6)
]
for x, y, r in bubbles:
    overlay_draw.ellipse([x-r, y-r, x+r, y+r], fill=bubble_color, outline=(255,255,255,180), width=2)
    # 高光
    overlay_draw.ellipse([x-r/2, y-r/2, x-r/4, y-r/4], fill=(255,255,255,200))

img.paste(overlay, (0,0), overlay)

# 3. 绘制文字 "KDX" - 胖乎乎的风格 (Bubbly Font Style)
# 由于没有字体文件，手动绘制圆润的形状
# 字体位置调整
start_x = 10
base_y = 50
char_width = 50
char_height = 70
stroke_width = 18 # 非常粗的线条来模拟胖乎乎的感觉

# 绘制辅助函数：带圆角的粗线
def draw_fat_line(draw_obj, xy, fill, width):
    draw_obj.line(xy, fill=fill, width=width, joint='curve')
    # 手动补圆头
    for point in [xy[0], xy[-1]]:
        r = width / 2
        draw_obj.ellipse([point[0]-r, point[1]-r, point[0]+r, point[1]+r], fill=fill)

# K - Yellow
# 竖线
draw_fat_line(draw, [(35, 60), (35, 120)], color_k, stroke_width)
# 上撇
draw_fat_line(draw, [(35, 90), (60, 60)], color_k, stroke_width)
# 下捺
draw_fat_line(draw, [(35, 90), (60, 120)], color_k, stroke_width)
# K的表情 (Eyes and Mouth)
draw.ellipse([28, 95, 32, 99], fill='black') # Left Eye
draw.ellipse([45, 95, 49, 99], fill='black') # Right Eye
draw.arc([35, 100, 42, 105], 0, 180, fill='black', width=2) # Smile

# D - Pink
# D的形状比较特殊，用填充多边形+轮廓
# 竖线部分
draw_fat_line(draw, [(85, 60), (85, 120)], color_d, stroke_width)
# 弧形部分 (模拟)
draw.arc([65, 60, 115, 120], 270, 90, fill=color_d, width=stroke_width)
# 填补中间空隙 (Dirty hack for fat font look)
draw.rectangle([85, 60, 95, 120], fill=color_d)
# D的内部镂空 (White center)
draw.ellipse([88, 75, 102, 105], fill='white')

# X - Purple
# 左上到右下
draw_fat_line(draw, [(135, 60), (165, 120)], color_x, stroke_width)
# 右上到左下
draw_fat_line(draw, [(165, 60), (135, 120)], color_x, stroke_width)
# X的表情
draw.ellipse([142, 90, 146, 94], fill='black') # Left Eye
draw.ellipse([158, 90, 162, 94], fill='black') # Right Eye
draw.arc([148, 95, 156, 100], 0, 180, fill='black', width=2) # Smile


# 4. 增加一点蝴蝶装饰 (Butterflies)
def draw_butterfly(x, y, color):
    # Wings
    draw.ellipse([x-8, y-8, x, y], fill=color) # Top Left
    draw.ellipse([x, y-8, x+8, y], fill=color) # Top Right
    draw.ellipse([x-6, y, x, y+6], fill=color) # Bottom Left
    draw.ellipse([x, y, x+6, y+6], fill=color) # Bottom Right
    # Body
    draw.line([(x, y-5), (x, y+5)], fill='brown', width=2)

draw_butterfly(160, 40, (255, 245, 157)) # Yellow butterfly
draw_butterfly(30, 140, (244, 143, 177)) # Pink butterfly

# 5. 保存
output_path = r'c:\Users\konglingwen\code\django-vue-docker\kdx-fe\public\logo.png'
# 也覆盖之前的 apple-touch-icon
output_path_icon = r'c:\Users\konglingwen\code\django-vue-docker\kdx-fe\public\apple-touch-icon.png'
img.save(output_path)
img.save(output_path_icon)
print(f"Logo generated at: {output_path}")
