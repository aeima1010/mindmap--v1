# zMind Generator API 插件文档

此目录包含了可以作为一个 Coze 插件接入的思维导图生成器 API。它利用了火山引擎的大语言模型能力来输出规则和节点的 Markdown 文本，并将该文本传给本 API 渲染出精美思维导图。

## 目录结构
- `main.py`: 基于 FastAPI 的接口，提供图片渲染服务。
- `requirements.txt`: Python 依赖。
- `openapi.yaml`: 导入到 Coze 平台时的标准 OpenAPI 规范文件。
- `netlify.toml` / `vercel.json`: 部署配置文件。

## 部署说明 (Deployment)

由于此项目使用了 `matplotlib` 和 `networkx` 等依赖包（在云函数中涉及到 C++ 底层库和体积限制），我们提供了以下两种推荐部署方式：

### 方案 1：Vercel / Render 部署（推荐，原生支持 Python）
Vercel 对 Python FastAPI 的 Serverless 部署支持最好。
1. 在目录下创建 `vercel.json` (本文档已附带生成)
2. 将该目录推送到 GitHub。
3. 在 Vercel 控制台中导入该项目，它会自动安装 `requirements.txt` 并发布服务。

### 方案 2：Netlify 部署（用户指定）
由于 Netlify 官方的 Functions 主推 Node.js 和 Go，原生直接跑 Python 较为繁琐且由于 `matplotlib` 包体积过大经常报错，但你可以通过以下变通方式部署在 Netlify：
1. **Netlify Docker 容器化 / 自建 Build**：编写构建脚本使用 Netlify 的兼容环境。
2. 我们已经提供了基础的 `netlify.toml`，如果你在 Netlify 上启用了实验性的 Python 支持，可以使用它。但强烈建议生产环境中此类携带图形渲染计算的 API 部署在 Render.com 或 Vercel。

## 在 Coze 平台上的集成步骤
1. **创建插件**：在 Coze 工作台中，选择“创建插件” -> “基于 OpenAPI 创建”。
2. **导入 Schema**：将本目录下的 `openapi.yaml` 文件的内容复制粘贴到配置框中。
3. **配置服务器 URL**：将 `openapi.yaml` 中 `servers` 下的 url 替换为你部署成功后的真实 URL（例如 `https://dmind-api.vercel.app`）。
4. **测试调用**：验证返回含 `data`、`data_struct`、`log_id`、`msg`、`status_code`、`type_for_model`，以及兼容字段 `image`、`image_url`、`message`、`image_base64`。
5. **Prompt 设定**：在 Coze Bot 的提示词中，告知 AI（火山引擎）：
   *“当你被要求生成思维导图时，请先整理出 Markdown 层级文本，然后调用 GenerateMindmap 插件。展示用可直接输出 `data` 字段；外链图片用 `data_struct.pic` 或 `image_url`。不要把长图强制转成 Base64。”*

## 图片输出方式
- Coze 插件底层调用 `/generate`，响应为 JSON。
- **默认输出 JPEG 图片 URL**：`image_format` 默认为 `jpeg`，响应里的 **`data_struct.pic` / `image_url`** 是短链接，形如 `/image/<id>.jpeg`，不会把整段 Markdown 塞进 URL。
- 前端若固定读取 `image` 字段，可直接映射根字段 **`image`**；它与 `data_struct.pic`、`image_url` 完全相同。
- **不要默认返回 Base64**：`include_image_base64` 默认为 `false`，避免长图把 JSON 响应体撑大后触发网关 504。
- 确实需要 Data URI 时，可以传 **`include_image_base64: true`**；若图片超过服务端 `MAX_IMAGE_BASE64_BYTES`，该字段仍会返回空字符串。
- 请求体里也可传 `image_format: "jepg"`，会归一化为标准 JPEG。
- 如需 PNG，传 `image_format: "png"`，短链接会变成 `/image/<id>.png`。
- 旧的 `/render?markdown=...` 入口仍保留，默认返回 `image/jpeg`。

## 环境变量
- `PUBLIC_BASE_URL`: 对外可访问的服务地址，用于生成 `data_struct.pic` 图片 URL，默认 `https://dmindmap.zeabur.app`。
- `MINDMAP_JUMP_LINK`: 默认编辑链接；请求体里的 `jump_link` 优先级更高。未配置时，返回结构仍保留 `data_struct.jump_link`，值为空字符串。
- `IMAGE_CACHE_DIR`: 图片缓存目录，默认 `/tmp/dmind-api-images`。
- `MAX_IMAGE_BASE64_BYTES`: 允许返回 Base64 Data URI 的最大图片字节数，默认 2MB。
- `MINDMAP_DPI`: 渲染 DPI，默认 120，降低长图渲染耗时和体积。
- `MINDMAP_MAX_FIGURE_HEIGHT`: 最大画布高度（英寸），默认 80，避免超大长图拖垮网关。
- `MINDMAP_MAX_NODES`: 最大渲染节点数，默认 120；超过后会在图中追加“其余节点已省略”的提示，避免长文本请求超时。
- `MINDMAP_MAX_NODE_TEXT_CHARS`: 单个节点最多保留字符数，默认 80；超出后加省略号，避免单节点长段落拖慢渲染。

## Coze 试运行里 Response 显示 `{}` 时怎么排查

1. **`jump_link` 为空不会导致 `{}`**。空链接时仍会返回完整 JSON，只是没有「编辑」链接相关文案。
2. **先看「请求 / 原始响应」**：确认 HTTP 200，且 Body 里是否已有 `code`、`data`、`data_struct` 等。若原始 Body 正常、只有摘要区是 `{}`，多半是 **工具「输出参数」与响应字段名不一致**（例如仍绑定旧的 `image_url`、`message`，而接口只返回了新字段名）。
3. **处理办法**：在插件里用最新 `openapi.yaml` **重新导入/同步**该工具；或在工具的输出映射里绑定：`data`、`data_struct.pic`，或根字段 **`image_url`**、**`message`**（与 `pic` / `msg` 同源，专为兼容旧配置）。
4. **部署与 Schema 一致**：Coze 里填的 Base URL 必须指向已部署当前代码的实例；若线上仍是旧接口，字段对不上也会出现空映射。

这样，用户就可以在 Coze 的对话流中直接看到渲染好的精美图片了！
