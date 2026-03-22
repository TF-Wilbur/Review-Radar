#!/bin/bash
# 启动 Streamlit（后台运行，监听 8501，basePath=/app）
streamlit run web/app.py \
  --server.port=8501 \
  --server.address=127.0.0.1 \
  --server.baseUrlPath=/app \
  --server.headless=true &

# 启动 Nginx（前台运行，监听 8080）
nginx -g 'daemon off;'
