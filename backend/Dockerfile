FROM python:3.11-slim-bookworm

# Instal dependensi sistem untuk OpenCV dan SQLite
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Aturan Wajib Hugging Face: Buat user non-root (UID 1000)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /home/user/app

# Salin requirements dan instal
COPY --chown=user ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Salin seluruh kode backend
COPY --chown=user . /home/user/app

# Port wajib Hugging Face
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
