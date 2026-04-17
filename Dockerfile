FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema necesarias para dlib e insightface
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    python3-dev \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Crear directorios para volúmenes (se montan desde el host)
RUN mkdir -p /app/data /app/reference_images

# Copiar configuración de Streamlit
COPY .streamlit /root/.streamlit

EXPOSE 8501

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true"]