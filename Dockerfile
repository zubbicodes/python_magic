FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TOOL_SITE_HOST=0.0.0.0
ENV TOOL_SITE_PORT=8080

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
  && python -m pip install --no-cache-dir -r /app/requirements.txt \
  && python -m playwright install --with-deps chromium

COPY . /app

EXPOSE 8080

CMD ["python", "tool_site/server.py"]
