# 第一阶段：安装依赖
FROM python:3.12-slim AS builder

# 安装 Poetry
RUN pip install poetry

WORKDIR /app

COPY pyproject.toml poetry.lock ./

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

# 使用 Poetry 安装依赖
RUN poetry install --no-root && rm -rf $POETRY_CACHE_DIR

# 第二阶段：构建最终镜像
FROM python:3.12-slim

WORKDIR /app

# 从第一阶段复制依赖
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# 复制应用代码
COPY app.py .
COPY botpage.py .
COPY bot_management.py .
COPY st_copy_to_clipboard .

# 暴露 Streamlit 的默认端口
EXPOSE 8501

# 启动 Streamlit 应用程序
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]