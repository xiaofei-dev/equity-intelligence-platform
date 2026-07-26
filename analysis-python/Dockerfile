FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system analytics \
    && adduser --system --ingroup analytics analytics

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

USER analytics
EXPOSE 8000
CMD ["uvicorn", "equity_analysis.main:app", "--host", "0.0.0.0", "--port", "8000"]
