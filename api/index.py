from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
import matplotlib.pyplot as plt
import matplotlib.path as mpath
import matplotlib.patches as mpatches
from matplotlib import font_manager
import networkx as nx
import re
import io
import base64
import os
from fastapi.middleware.cors import CORSMiddleware

# 动态加载中文字体，确保在 Vercel 或 Serverless 环境中渲染不出错
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_PATH = os.path.join(BASE_DIR, "fonts", "NotoSansSC.ttf")

if os.path.exists(FONT_PATH):
    font_manager.fontManager.addfont(FONT_PATH)
    prop = font_manager.FontProperties(fname=FONT_PATH)
    plt.rcParams['font.family'] = prop.get_name()
else:
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'PingFang SC', 'Heiti TC', 'sans-serif']

plt.rcParams['axes.unicode_minus'] = False

app = FastAPI(title="zMind Generator API", description="生成美化思维导图的 API 插件")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class MindmapRequest(BaseModel):
    markdown_text: str

class MindmapResponse(BaseModel):
    image_base64: str
    message: str

def wrap_text(text, limit=18):
    if len(text) <= limit: return text
    parts = []
    while len(text) > limit:
        parts.append(text[:limit])
        text = text[limit:]
    if text: parts.append(text)
    wrapped = '\n'.join(parts)
    lines = wrapped.split('\n')
    if len(lines) > 3:
        return '\n'.join(lines[:2]) + '\n' + lines[2][:limit-2] + '...'
    return wrapped

def parse_markdown(md_text):
    lines = md_text.strip().split('\n')
    nodes = []
    for line in lines:
        if not line.strip(): continue
        heading_match = re.match(r'^(#+)\s+(.*)', line)
        if heading_match:
            nodes.append({"level": len(heading_match.group(1)) - 1, "text": heading_match.group(2).strip()})
            
    root = {"text": "Root", "children": []}
    stack = [(-1, root)]
    for item in nodes:
        level, text = item["level"], item["text"]
        new_node = {"text": text, "wrapped_text": wrap_text(text), "children": [], "level": level}
        while stack and stack[-1][0] >= level: stack.pop()
        stack[-1][1]["children"].append(new_node)
        stack.append((level, new_node))
    return root["children"][0] if len(root["children"]) >= 1 else root

def layout_tree(node, parent_x=0, current_y=0):
    lines = node.get("wrapped_text", node["text"]).split('\n')
    max_len = max(len(line) for line in lines)
    node_width = max_len * 0.28 + 0.5 
    if node.get("level") == 0: node_width += 1.0 
    node["x"] = parent_x
    node["width"] = node_width
    height_factor = max(1.0, len(lines) * 0.6)
    
    if not node.get("children"):
        node["y"] = current_y
        return node, current_y + height_factor + 0.4
        
    child_x = parent_x + node_width + 1.2 
    for child in node["children"]:
        child, current_y = layout_tree(child, child_x, current_y)
        
    node["y"] = (node["children"][0]["y"] + node["children"][-1]["y"]) / 2
    return node, current_y

def set_colors(node, color=None):
    colors = ["#F4928E", "#A49C93", "#82A4C8", "#F19999", "#7FB3A7", "#D4B376", "#AC8EC8"]
    text_colors = ["#B03A36", "#615A52", "#3E648C", "#B03A36", "#397164", "#917032", "#664882"]
    if node.get("level") == 0 or node.get("level") is None: 
        for i, child in enumerate(node.get("children", [])):
            set_colors(child, (colors[i % len(colors)], text_colors[i % len(text_colors)]))
    else:
        node["color"], node["text_color"] = color[0], color[1]
        for child in node.get("children", []): set_colors(child, color)

def draw_edge(ax, p0, p1, color, linewidth=2.5):
    ctrl_x = p0[0] + (p1[0] - p0[0]) * 0.5
    path = mpath.Path([p0, (ctrl_x, p0[1]), (ctrl_x, p1[1]), p1],
                      [mpath.Path.MOVETO, mpath.Path.CURVE4, mpath.Path.CURVE4, mpath.Path.CURVE4])
    patch = mpatches.PathPatch(path, facecolor='none', edgecolor=color, lw=linewidth)
    ax.add_patch(patch)

def draw_tree(ax, node, parent_pos=None):
    x, y, text, level = node["x"], node["y"], node.get("wrapped_text", node["text"]), node.get("level", 0)
    if parent_pos:
        start_x, end_x = parent_pos[0] + parent_pos[2], x - 0.2
        draw_edge(ax, (start_x, parent_pos[1]), (end_x, y), node.get("color", "#CCCCCC"))
        font_color = "#222222" if level == 1 else node.get("text_color", "#333333")
        ax.text(x, y, text, ha='left', va='center', fontsize=13 if level == 1 else 11, color=font_color)
    else:
        ax.text(x, y, text, ha='left', va='center', fontsize=16, color='white', weight='bold',
                bbox=dict(boxstyle="round,pad=0.7", ec="none", fc="#FFA3C5"))
    for child in node.get("children", []): draw_tree(ax, child, (x, y, node["width"]))

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "zMind Generator API is running perfectly on Vercel!",
        "endpoints": {
            "/generate": "POST - 传入 markdown_text 生成思维导图图片"
        }
    }

@app.post("/generate")
def generate_mindmap(req: MindmapRequest):
    try:
        root_node = parse_markdown(req.markdown_text)
        if not isinstance(root_node, dict): raise ValueError("无效的 Markdown 格式")
            
        root_node["level"] = 0
        root_node["wrapped_text"] = wrap_text(root_node["text"], 22)
        root_node, total_height = layout_tree(root_node, parent_x=0)
        set_colors(root_node)
        
        fig, ax = plt.subplots(figsize=(18, max(10, total_height * 0.7)))
        fig.patch.set_facecolor('#F2F2F2')
        ax.set_facecolor('#F2F2F2')
        draw_tree(ax, root_node)
        
        all_x, all_y = [], []
        def collect_coords(n):
            all_x.extend([n["x"], n["x"] + n["width"]])
            all_y.append(n["y"])
            for c in n.get("children", []): collect_coords(c)
        collect_coords(root_node)
        
        ax.set_xlim(min(all_x) - 1.5, max(all_x) + 3.0)
        ax.set_ylim(max(all_y) + 1.5, min(all_y) - 1.5)
        ax.axis("off")
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        
        return Response(content=buf.read(), media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
