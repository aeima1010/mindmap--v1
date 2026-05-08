FROM python:3.11-slim

# 安装必要的系统库（可选，防止部分字体渲染问题）
RUN apt-get update && apt-get install -y --no-install-recommends \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制所有项目代码
COPY . .

# 暴露端口
ENV PORT=8080
EXPOSE 8080

# 启动服务
CMD ["python", "main.py"]
