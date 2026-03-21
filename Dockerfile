FROM python:3.12-slim

WORKDIR /app

# 先复制依赖声明，利用 layer 缓存
COPY pyproject.toml .

# 创建空包目录让 pip install 能找到包
RUN mkdir -p review_radar && \
    touch review_radar/__init__.py && \
    pip install --no-cache-dir . && \
    pip install --no-cache-dir streamlit plotly && \
    rm -rf review_radar

# 再复制实际代码（代码变更不会重新安装依赖）
COPY review_radar/ review_radar/
COPY web/ web/

# Streamlit 配置
RUN mkdir -p /root/.streamlit
COPY .streamlit/config.toml /root/.streamlit/config.toml

EXPOSE 8080

CMD ["streamlit", "run", "web/app.py", "--server.port=8080", "--server.address=0.0.0.0"]
