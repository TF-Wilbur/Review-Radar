FROM python:3.12-slim

WORKDIR /app

# 安装 nginx
RUN apt-get update && apt-get install -y --no-install-recommends nginx && rm -rf /var/lib/apt/lists/*

# 先复制依赖声明，利用 layer 缓存
COPY pyproject.toml .

# 安装依赖（创建临时包目录让 pip 能解析 pyproject.toml）
RUN mkdir -p review_radar && \
    touch review_radar/__init__.py && \
    pip install --no-cache-dir ".[web]" && \
    rm -rf review_radar review_radar.egg-info

# 复制实际源码
COPY review_radar/ review_radar/
COPY web/ web/
COPY landing/ landing/

# 确保 Python 能找到 /app 下的包
ENV PYTHONPATH=/app

# Streamlit 配置
RUN mkdir -p /root/.streamlit
COPY .streamlit/config.toml /root/.streamlit/config.toml

# Nginx 配置
COPY nginx.conf /etc/nginx/sites-enabled/default
RUN rm -f /etc/nginx/sites-enabled/default.bak

# 启动脚本
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8080

CMD ["./start.sh"]
