FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY xlclient ./xlclient

# Hugging Face Spaces: container harus listen di port 7860
ENV PORT=7860
EXPOSE 7860

CMD ["gunicorn", "bot:app", "--bind", "0.0.0.0:7860", "--workers", "1", "--threads", "4"]
