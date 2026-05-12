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
4. **测试调用**：在调试界面输入一段 Markdown，验证它是否返回生产兼容 JSON：`code`、`data`、`data_struct`、`log_id`、`msg`、`status_code`、`type_for_model`。
5. **Prompt 设定**：在 Coze Bot 的提示词中，告知 AI（火山引擎）：
   *“当你被要求生成思维导图时，请先整理出 Markdown 层级文本，然后调用 GenerateMindmap 插件。插件会返回 `data` 字段，请直接将 `data` 内容展示给用户；`data_struct.pic` 是 PNG/JPEG 图片 URL，`data_struct.jump_link` 是可选编辑链接。”*

## 图片输出方式
- Coze 插件底层调用 `/generate`，响应必须是 JSON；因此真实图片通过 JSON 中的 `data_struct.pic` 返回。
- 默认生成 JPEG 图片 URL，例如 `/render.jpeg?markdown=...`；也兼容请求体中传 `image_format: "jepg"`，最终会归一化为标准 JPEG。
- 如需 PNG，可以在请求体中传 `image_format: "png"`，生成 `/render.png?markdown=...`。
- 旧的 `/render?markdown=...` 入口仍保留，默认返回 `image/jpeg`。

## 环境变量
- `PUBLIC_BASE_URL`: 对外可访问的服务地址，用于生成 `data_struct.pic` 图片 URL，默认 `https://dmindmap.zeabur.app`。
- `MINDMAP_JUMP_LINK`: 默认编辑链接；请求体里的 `jump_link` 优先级更高。未配置时，返回结构仍保留 `data_struct.jump_link`，值为空字符串。

这样，用户就可以在 Coze 的对话流中直接看到渲染好的精美图片了！
