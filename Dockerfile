FROM ghcr.io/astral-sh/uv:python3.12-alpine as builder

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

FROM python:3.12-alpine
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

COPY . .

CMD ["python", "main.py"]
