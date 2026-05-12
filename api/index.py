from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
import os
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.path as mpath
import matplotlib.patches as mpatches
from matplotlib import font_manager
import networkx as nx
import re
import io
import uuid
import urllib.parse
from datetime import datetime
from typing import Optional
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
    jump_link: Optional[str] = Field(
        None,
        description="可选。在线编辑页完整 URL；未传则读环境变量 MINDMAP_JUMP_LINK（均可为空）",
    )
    image_format: Optional[str] = Field(
        "jpeg",
        description="输出图片格式，支持 jpeg、jpg、jepg、png；默认 jpeg",
    )

class DataStruct(BaseModel):
    jump_link: str = Field(description="在线编辑或跳转链接；未配置时为空字符串")
    pic: str = Field(description="思维导图图片可直接访问的 URL")

class MindmapPluginResponse(BaseModel):
    """与生产环境（如树图类插件）一致的插件返回结构，便于 Coze 等渠道直接消费。"""
    code: int = 0
    data: str = Field(description="含 Markdown 图片与说明文案，可直接展示给用户")
    data_struct: DataStruct
    log_id: str
    msg: str = "success"
    status_code: int = 0
    type_for_model: int = 2

def _public_base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://dmindmap.zeabur.app").rstrip("/")

def _make_log_id() -> str:
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:20].upper()
    return f"{ts}{suffix}"

def _env_jump_link() -> str:
    return (os.getenv("MINDMAP_JUMP_LINK") or "").strip()

def _normalize_image_format(image_format: Optional[str]) -> str:
    fmt = (image_format or "jpeg").lower().strip().lstrip(".")
    if fmt in {"jpg", "jpeg", "jepg"}:
        return "jpeg"
    if fmt == "png":
        return "png"
    raise ValueError("image_format 仅支持 jpeg、jpg、jepg、png")

def _image_media_type(image_format: str) -> str:
    return "image/jpeg" if image_format == "jpeg" else "image/png"

def _build_data_markdown(pic: str, jump_link: str) -> str:
    lines = [f"![返回图片]({pic})"]
    if jump_link:
        lines.extend([
            "",
            f"[编辑]({jump_link})",
            "",
            "如果觉得这个思维导图还不够完美，或者你的想法需要更自由地表达，点击编辑按钮，将你的思维导图变形、变色、变内容、甚至可以添加新的元素，快来试试吧！。",
        ])
    else:
        lines.extend(["", "以下为根据你的内容自动生成的思维导图图片。"])
    return "\n".join(lines) + "\n"

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

def generate_image_buf(md_text, image_format="jpeg"):
    image_format = _normalize_image_format(image_format)
    root_node = parse_markdown(md_text)
    if not isinstance(root_node, dict): raise ValueError("无效的 Markdown 格式")
        
    root_node["level"] = 0
    root_node["wrapped_text"] = wrap_text(root_node["text"], 22)
    root_node, total_height = layout_tree(root_node, parent_x=0)
    set_colors(root_node)
    
    fig, ax = plt.subplots(figsize=(18, max(10, total_height * 0.7)))
    fig.patch.set_facecolor('#F2F2F2')
    ax.set_facecolor('#F2F2F2')
    draw_tree(ax, root_node)
    
    all_x, all_y = [] , []
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
    plt.savefig(buf, format=image_format, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf

def _render_image_response(markdown: str, image_format: str):
    try:
        fmt = _normalize_image_format(image_format)
        buf = generate_image_buf(markdown, fmt)
        return Response(content=buf.read(), media_type=_image_media_type(fmt))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/render")
def render_mindmap(markdown: str, image_format: str = "jpeg"):
    return _render_image_response(markdown, image_format)

@app.get("/render.{image_format}")
def render_mindmap_with_format(image_format: str, markdown: str):
    return _render_image_response(markdown, image_format)

@app.post("/generate", response_model=MindmapPluginResponse)
def generate_mindmap(req: MindmapRequest):
    try:
        image_format = _normalize_image_format(req.image_format)
        buf = generate_image_buf(req.markdown_text, image_format)
        buf.read()  # 渲染校验通过；图片以 URL 形式提供，与生产插件一致
        encoded_markdown = urllib.parse.quote(req.markdown_text)
        base = _public_base_url()
        pic = f"{base}/render.{image_format}?markdown={encoded_markdown}"
        jump = (req.jump_link or _env_jump_link() or "").strip()
        data = _build_data_markdown(pic, jump)
        return MindmapPluginResponse(
            code=0,
            data=data,
            data_struct=DataStruct(jump_link=jump, pic=pic),
            log_id=_make_log_id(),
            msg="success",
            status_code=0,
            type_for_model=2,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
