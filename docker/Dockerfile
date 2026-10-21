# syntax=docker/dockerfile:1
# 复用本机已缓存的 python:3.13-slim-bookworm 镜像，避免拉取新基础层
FROM --platform=linux/amd64 python:3.13-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/workspace/src

# 安装 frago 运行期最小 Python 依赖（不保留缓存，控制增量体积 <150MB）
RUN pip install --no-cache-dir \
    "websocket-client>=1.9.0" \
    "click>=8.1.0" \
    "pydantic>=2.0.0" \
    "python-dotenv>=1.0.0" \
    "python-frontmatter>=1.0.0" \
    "pyyaml>=6.0.0" \
    "certifi>=2025.11.12" \
    "charset-normalizer>=3.4.4" \
    "idna>=3.11" \
    "psutil>=7.1.3" \
    "requests>=2.32.5" \
    "urllib3>=2.5.0" \
    "pypinyin>=0.51.0" \
    "python-slugify>=8.0.0" \
    "rapidfuzz>=3.0.0" \
    "arxiv>=2.3.1" \
    "pyperclip>=1.8.0" \
    "obsws-python>=1.8.0" \
    "questionary>=2.1.0" \
    "watchdog>=3.0.0" \
    "markdown>=3.4.0" \
    "fastapi>=0.100.0" \
    "uvicorn[standard]>=0.23.0" \
    "croniter>=1.3.0" \
    "json-repair>=0.30.0" \
    "pillow>=10.0.0" \
    "edge-tts>=7.2.8" \
    "pytest>=7.4.0"

# 提供直接调用源码的 frago 命令包装器，宿主机改代码无需重建镜像
RUN printf '#!/bin/sh\nexec python3 -m frago.cli.main "$@"\n' > /usr/local/bin/frago \
    && chmod +x /usr/local/bin/frago

WORKDIR /workspace
CMD ["python3", "/workspace/docker/verify_env.py"]
