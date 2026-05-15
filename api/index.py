from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
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
import json
import base64
import io
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware

# 动态加载中文字体，确保在 Vercel 或 Serverless 环境中渲染不出错
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_PATH = os.path.join(BASE_DIR, "fonts", "NotoSansSC.ttf")
IMAGE_CACHE_DIR = Path(os.getenv("IMAGE_CACHE_DIR", "/tmp/dmind-api-images"))
MAX_BASE64_BYTES = int(os.getenv("MAX_IMAGE_BASE64_BYTES", str(2 * 1024 * 1024)))
DEFAULT_DPI = int(os.getenv("MINDMAP_DPI", "120"))
MAX_FIGURE_HEIGHT = float(os.getenv("MINDMAP_MAX_FIGURE_HEIGHT", "80"))
MAX_NODES = int(os.getenv("MINDMAP_MAX_NODES", "120"))
MAX_NODE_TEXT_CHARS = int(os.getenv("MINDMAP_MAX_NODE_TEXT_CHARS", "80"))

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
    include_image_base64: bool = Field(
        False,
        description="为 true 且图片未超过 MAX_IMAGE_BASE64_BYTES 时，在 image_base64 中返回 Data URI；默认 false 以避免长图 JSON 过大导致 504",
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
    # 兼容早期仅映射下列根字段的 Coze 工具配置（与 data_struct.pic / msg 同源）
    image: str = Field("", description="与 data_struct.pic 相同；给前端直接取 image 字段作为 JPEG/PNG 文件 URL")
    image_url: str = Field("", description="与 data_struct.pic 相同，便于旧输出映射")
    message: str = Field("", description="与 msg 相同，便于旧输出映射（旧版常用字段名 message）")
    image_base64: str = Field(
        "",
        description="请求 include_image_base64 为 true 时为完整 Data URI；否则为空字符串",
    )

def _public_base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://dmindmap.zeabur.app").rstrip("/")

def _make_log_id() -> str:
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:20].upper()
    return f"{ts}{suffix}"

def _env_jump_link() -> str:
    return (os.getenv("MINDMAP_JUMP_LINK") or "").strip()

def _unwrap_markdown_text(text: str) -> str:
    """若上游误把整段 JSON 放进 markdown_text（如 Coze/LLM 输出 {\"image\": \"# ...\"}），取出内层 Markdown。"""
    text = (text or "").strip()
    if not text:
        return text
    if text.startswith('"') and text.endswith('"'):
        try:
            decoded = json.loads(text)
            if isinstance(decoded, str):
                return decoded.strip()
        except (json.JSONDecodeError, TypeError, ValueError):
            return _unescape_json_string_fragment(text[1:-1]).strip()
    if not text.startswith("{"):
        return text
    try:
        obj = json.loads(text)
        if isinstance(obj, str):
            return obj.strip()
        if isinstance(obj, dict):
            for key in ("image", "markdown", "markdown_text", "content", "mindmap_md"):
                v = obj.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    # LLM 常产出「伪 JSON」：字符串里带真实换行，标准 json.loads 无法解析
    loose = _unwrap_loose_image_object(text)
    if loose is not None:
        return loose
    return text


def _unwrap_loose_image_object(text: str) -> Optional[str]:
    """解析形如 {\"image\": \"# 行1\\n真实换行## 行2\" } 的非严格 JSON（值内可有字面换行）。"""
    m = re.match(
        r'^\s*\{\s*"(image|markdown|markdown_text|content|mindmap_md)"\s*:\s*"',
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    value_start = m.end()
    end = re.search(r'"\s*\}\s*$', text[value_start:])
    if not end:
        return None
    inner = text[value_start : value_start + end.start()]
    return _unescape_json_string_fragment(inner).strip()


def _unescape_json_string_fragment(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "r":
                out.append("\r")
            elif nxt in '"\\':
                out.append(nxt)
            else:
                out.append(s[i : i + 2])
            i += 2
            continue
        out.append(s[i])
        i += 1
    return "".join(out)

def _normalize_image_format(image_format: Optional[str]) -> str:
    fmt = (image_format or "jpeg").lower().strip().lstrip(".")
    if fmt in {"jpg", "jpeg", "jepg"}:
        return "jpeg"
    if fmt == "png":
        return "png"
    raise ValueError("image_format 仅支持 jpeg、jpg、jepg、png")

def _image_media_type(image_format: str) -> str:
    return "image/jpeg" if image_format == "jpeg" else "image/png"


def _image_extension(image_format: str) -> str:
    return "jpeg" if image_format == "jpeg" else "png"


def _data_uri_for_bytes(image_format: str, raw: bytes) -> str:
    mime = "image/jpeg" if image_format == "jpeg" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _image_cache_path(image_id: str, image_format: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", image_id)
    if not safe_id:
        raise ValueError("无效的图片 ID")
    return IMAGE_CACHE_DIR / f"{safe_id}.{_image_extension(image_format)}"


def _save_image(raw: bytes, image_format: str, image_id: str) -> Path:
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _image_cache_path(image_id, image_format)
    path.write_bytes(raw)
    return path


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

def _clip_node_text(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= MAX_NODE_TEXT_CHARS:
        return text
    return text[:MAX_NODE_TEXT_CHARS].rstrip() + "..."

def wrap_text(text, limit=18):
    text = _clip_node_text(text)
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
    skipped = 0
    current_heading_level = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or set(stripped) <= {"-"}:
            continue
        heading_match = re.match(r'^(#+)\s+(.*)', stripped)
        bullet_match = re.match(r'^(\s*)([-*+]|\d+[.)])\s+(.*)', line)
        text = ""
        level = current_heading_level + 1
        if heading_match:
            level = len(heading_match.group(1)) - 1
            text = heading_match.group(2)
            current_heading_level = level
        elif bullet_match:
            indent = len(bullet_match.group(1).replace("\t", "    "))
            level = current_heading_level + 1 + min(indent // 2, 3)
            text = bullet_match.group(3)
        else:
            text = stripped

        if text:
            if len(nodes) < MAX_NODES:
                nodes.append({"level": level, "text": _clip_node_text(text)})
            else:
                skipped += 1
            
    root = {"text": "Root", "children": []}
    stack = [(-1, root)]
    for item in nodes:
        level, text = item["level"], item["text"]
        new_node = {"text": text, "wrapped_text": wrap_text(text), "children": [], "level": level}
        while stack and stack[-1][0] >= level: stack.pop()
        stack[-1][1]["children"].append(new_node)
        stack.append((level, new_node))
    if len(root["children"]) == 1:
        result = root["children"][0]
    elif len(root["children"]) > 1:
        result = {"text": "思维导图", "wrapped_text": wrap_text("思维导图"), "children": root["children"], "level": 0}
    else:
        result = root
    if skipped:
        result.setdefault("children", []).append({
            "text": f"其余 {skipped} 个节点已省略，请缩短内容或分批生成",
            "wrapped_text": wrap_text(f"其余 {skipped} 个节点已省略，请缩短内容或分批生成"),
            "children": [],
            "level": result.get("level", 0) + 1,
        })
    return result

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
    
    fig_height = min(max(10, total_height * 0.7), MAX_FIGURE_HEIGHT)
    fig, ax = plt.subplots(figsize=(18, fig_height))
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
    plt.savefig(buf, format=image_format, dpi=DEFAULT_DPI, bbox_inches='tight', facecolor=fig.get_facecolor())
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

@app.get("/image/{image_name}")
def get_cached_image(image_name: str):
    try:
        m = re.fullmatch(r"([A-Za-z0-9_-]+)\.(jpeg|jpg|jepg|png)", image_name)
        if not m:
            raise HTTPException(status_code=404, detail="图片不存在")
        image_id, image_format = m.group(1), _normalize_image_format(m.group(2))
        path = _image_cache_path(image_id, image_format)
        if not path.exists():
            raise HTTPException(status_code=404, detail="图片已过期或不存在")
        return FileResponse(path, media_type=_image_media_type(image_format))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/generate", response_model=MindmapPluginResponse)
def generate_mindmap(req: MindmapRequest):
    try:
        markdown_text = _unwrap_markdown_text(req.markdown_text)
        image_format = _normalize_image_format(req.image_format)
        buf = generate_image_buf(markdown_text, image_format)
        raw = buf.read()
        image_base64 = ""
        if req.include_image_base64 and len(raw) <= MAX_BASE64_BYTES:
            image_base64 = _data_uri_for_bytes(image_format, raw)
        base = _public_base_url()
        log_id = _make_log_id()
        image_id = uuid.uuid4().hex
        _save_image(raw, image_format, image_id)
        pic = f"{base}/image/{image_id}.{_image_extension(image_format)}"
        jump = (req.jump_link or _env_jump_link() or "").strip()
        data = _build_data_markdown(pic, jump)
        return MindmapPluginResponse(
            code=0,
            data=data,
            data_struct=DataStruct(jump_link=jump, pic=pic),
            log_id=log_id,
            msg="success",
            status_code=0,
            type_for_model=2,
            image=pic,
            image_url=pic,
            message="success",
            image_base64=image_base64,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
