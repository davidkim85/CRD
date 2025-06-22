FROM python:3.11-slim

WORKDIR /app

# Install system dependencies

RUN apt-get update && apt-get install -y gcc libpq-dev \
  && apt-get clean && rm -rf /var/lib/apt/lists/*
# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "--workers=4"]