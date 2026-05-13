import os
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from api.index import app, generate_mindmap, MindmapRequest

markdown_data = """# 深圳证券交易所首次公开发行证券发行与承销细则 · 第一章 总则
## 第一条 制定目的与依据
### 制定目的
#### 规范深交所首次公开发行证券发行与承销行为
#### 维护市场秩序
#### 保护投资者合法权益
### 制定依据
#### 《证券发行与承销管理办法》
#### 《首次公开发行股票注册管理办法》
#### 其他有关规定
## 第二条 适用范围
### 本细则适用情形
#### 经中国证监会注册的首次公开发行股票/存托凭证在深交所的发行承销业务
### 细则未作规定的适用规则
#### 《深圳市场首次公开发行股票网上发行实施细则》
#### 《深圳市场首次公开发行股票网下发行实施细则》
#### 其他有关规定
## 第三条 承销与主体行为规范
### 证券公司承销要求
#### 制度建设：制定严格风险管理制度与内部控制制度，加强定价配售过程管理，落实承销责任，防范利益冲突
#### 操作要求：制定详细业务流程，按深交所规则、指南完成操作，保证提交的发行数据真实、准确、完整
### 其他相关主体要求
#### 适用对象：保荐人、承销商、投资者及其他相关主体
#### 行为要求：诚实守信，遵守法律法规、深交所业务规则、行业规范，不得进行利益输送或谋取不正当利益
## 第四条 信息披露要求
### 发行人和主承销商
#### 按规定编制并及时、公平披露发行承销信息披露文件
#### 保证披露信息真实、准确、完整，无虚假记载、误导性陈述、重大遗漏
### 证券服务机构及人员
#### 严格遵守法律法规和深交所业务规则，遵循行业业务标准和道德规范
#### 严格履行法定职责，对所出具文件的真实性、准确性、完整性承担责任
## 第五条 自律管理规定
### 实施主体：深圳证券交易所
### 管理依据：相关法律法规、业务规则、本细则
### 监管对象
#### 首次公开发行证券发行承销活动
#### 各参与主体：发行人及其控股股东/实际控制人、董监高，证券公司、证券服务机构、投资者等"""

def run():
    print("Calling API function...")
    os.environ["PUBLIC_BASE_URL"] = "http://testserver"
    client = TestClient(app, base_url="http://testserver")

    # HTTP 路径自测（与 Coze 调用一致）
    http_res = client.post(
        "/generate",
        json={
            "markdown_text": "# 根\n## 子节点 A\n## 子节点 B",
            "jump_link": "https://example.com/edit-demo",
        },
    )
    assert http_res.status_code == 200
    payload = http_res.json()
    assert payload["code"] == 0 and payload["status_code"] == 0 and payload["type_for_model"] == 2
    assert "data_struct" in payload and payload["data_struct"]["jump_link"] == "https://example.com/edit-demo"
    assert "[编辑](https://example.com/edit-demo)" in payload["data"]
    assert payload["image_base64"] == ""
    pic = payload["data_struct"]["pic"]
    parsed = urlparse(pic)
    assert parsed.path.startswith("/image/")
    assert parsed.path.endswith(".jpeg")
    assert parsed.query == ""
    img = client.get(f"{parsed.path}?{parsed.query}")
    assert img.status_code == 200 and img.headers.get("content-type", "").startswith("image/")
    assert img.headers.get("content-type", "").startswith("image/jpeg")
    assert img.content.startswith(b"\xff\xd8")

    jpeg_res = client.post(
        "/generate",
        json={
            "markdown_text": "# 根\n## 子节点 A\n## 子节点 B",
            "image_format": "jepg",
        },
    )
    assert jpeg_res.status_code == 200
    jpeg_payload = jpeg_res.json()
    jpeg_pic = jpeg_payload["data_struct"]["pic"]
    jpeg_parsed = urlparse(jpeg_pic)
    assert jpeg_parsed.path.startswith("/image/")
    assert jpeg_parsed.path.endswith(".jpeg")
    jpeg_img = client.get(f"{jpeg_parsed.path}?{jpeg_parsed.query}")
    assert jpeg_img.status_code == 200
    assert jpeg_img.headers.get("content-type", "").startswith("image/jpeg")
    assert jpeg_img.content.startswith(b"\xff\xd8")

    png_res = client.post(
        "/generate",
        json={
            "markdown_text": "# 根\n## 子节点 A\n## 子节点 B",
            "image_format": "png",
        },
    )
    assert png_res.status_code == 200
    png_payload = png_res.json()
    png_pic = png_payload["data_struct"]["pic"]
    png_parsed = urlparse(png_pic)
    assert png_parsed.path.startswith("/image/")
    assert png_parsed.path.endswith(".png")
    png_img = client.get(f"{png_parsed.path}?{png_parsed.query}")
    assert png_img.status_code == 200
    assert png_img.headers.get("content-type", "").startswith("image/png")
    assert png_img.content.startswith(b"\x89PNG")

    bad_format_res = client.post(
        "/generate",
        json={
            "markdown_text": "# 根\n## 子节点 A",
            "image_format": "gif",
        },
    )
    assert bad_format_res.status_code == 400

    no_b64_res = client.post(
        "/generate",
        json={
            "markdown_text": "# 根\n## 子",
            "include_image_base64": False,
        },
    )
    assert no_b64_res.status_code == 200
    assert no_b64_res.json()["image_base64"] == ""

    with_b64_res = client.post(
        "/generate",
        json={
            "markdown_text": "# 根\n## 子",
            "include_image_base64": True,
        },
    )
    assert with_b64_res.status_code == 200
    assert with_b64_res.json()["image_base64"].startswith("data:image/jpeg;base64,")

    long_markdown = "# 长文本测试\n" + "\n".join(
        f"## 第 {i} 个节点\n### 说明 {i} " + "长内容" * 20
        for i in range(1, 250)
    )
    long_res = client.post(
        "/generate",
        json={
            "markdown_text": long_markdown,
        },
    )
    assert long_res.status_code == 200
    long_payload = long_res.json()
    long_pic = long_payload["data_struct"]["pic"]
    long_parsed = urlparse(long_pic)
    assert long_payload["image_base64"] == ""
    assert long_parsed.path.startswith("/image/")
    assert long_parsed.path.endswith(".jpeg")
    assert long_parsed.query == ""
    assert len(long_pic) < 120
    long_img = client.get(long_parsed.path)
    assert long_img.status_code == 200
    assert long_img.headers.get("content-type", "").startswith("image/jpeg")
    assert long_img.content.startswith(b"\xff\xd8")

    huge_node_res = client.post(
        "/generate",
        json={
            "markdown_text": "# 根\n## " + "单节点超长内容" * 500,
        },
    )
    assert huge_node_res.status_code == 200
    huge_node_payload = huge_node_res.json()
    huge_node_pic = huge_node_payload["data_struct"]["pic"]
    huge_node_parsed = urlparse(huge_node_pic)
    assert huge_node_parsed.path.startswith("/image/")
    assert huge_node_parsed.query == ""

    # 直接调用路由函数
    req = MindmapRequest(markdown_text=markdown_data, jump_link="https://example.com/edit-demo", image_format="jepg")
    res = generate_mindmap(req)
    assert res.code == 0 and res.status_code == 0 and res.type_for_model == 2
    assert res.data_struct.pic and "/image/" in res.data_struct.pic and res.data_struct.pic.endswith(".jpeg")

    out_path = "api_output.jpeg"
    p2 = urlparse(res.data_struct.pic)
    img2 = client.get(f"{p2.path}?{p2.query}")
    assert img2.status_code == 200
    with open(out_path, "wb") as f:
        f.write(img2.content)

    print(f"Successfully generated mindmap (plugin format). Saved to {out_path}")

if __name__ == "__main__":
    run()
