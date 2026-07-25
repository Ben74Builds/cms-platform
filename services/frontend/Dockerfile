# Use the specified base image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Copy only requirements.txt first to leverage Docker cache
COPY app/requirements.txt /app/requirements.txt

# Install locales, build tools for tippecanoe, and spatial libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    locales \
    build-essential \
    libsqlite3-dev \
    zlib1g-dev \
    git \
    libspatialindex-dev \
    libgeos-dev \
    osmium-tool \
    && echo "en_US.UTF-8 UTF-8" > /etc/locale.gen \
    && echo "fr_FR.UTF-8 UTF-8" >> /etc/locale.gen \
    && locale-gen \
    && rm -rf /var/lib/apt/lists/*

# Install tippecanoe
RUN git clone --depth 1 https://github.com/felt/tippecanoe.git /tmp/tippecanoe \
    && cd /tmp/tippecanoe && make -j$(nproc) && make install \
    && rm -rf /tmp/tippecanoe

# Install setuptools (required by pykafka) and requirements
RUN pip install --no-cache-dir "setuptools<71"
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY app/ /app

# Expose port 5001 to the outside world
EXPOSE 5001

# Run the application with uvicorn (FastAPI)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5001", "--workers", "4"]
