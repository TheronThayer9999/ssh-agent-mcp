FROM python:3.14-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY main.py ./

ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "main.py"]
