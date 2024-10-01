# 第一阶段：安装依赖
FROM python:3.12-slim AS builder

WORKDIR /app

COPY pyproject.toml poetry.lock ./

# 安装 Poetry
RUN pip install poetry

# 使用 Poetry 安装依赖
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main

# 第二阶段：构建最终镜像
FROM python:3.12-slim

WORKDIR /app

# 从第一阶段复制依赖
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# 复制应用代码
COPY . .

# 暴露 Streamlit 的默认端口
EXPOSE 8501

# 启动 Streamlit 应用程序
CMD ["streamlit", "run", "app.py"]