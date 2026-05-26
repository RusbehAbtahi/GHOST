FROM python:3.11-slim

# 1. Set workdir inside container
WORKDIR /app

# 2. Install system packages if needed (keep minimal for now)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 3. Copy requirements and install Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN python -m playwright install --with-deps chromium

# 4. Copy the whole project into the image
COPY . /app

# 5. Ensure Python can see the project root (like your PYTHONPATH trick)
ENV PYTHONPATH=/app

# 6. Streamlit default port + listen on all interfaces
ENV STREAMLIT_SERVER_PORT=8501
EXPOSE 8501

# 7. Default command: run your UI
CMD ["streamlit", "run", "ragstream/app/ui_streamlit.py", "--server.port=8501", "--server.address=0.0.0.0"]
