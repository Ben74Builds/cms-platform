# Runtime container for pre-compiled backend binaries
# Using Ubuntu because binaries are compiled with glibc (not musl/Alpine)
FROM ubuntu:22.04

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 \
    libgcc-s1 \
    libcurl4 \
    libprotobuf23 \
    zlib1g \
    libhiredis0.14 \
    libpq5 \
    libgomp1 \
    wget \
    supervisor \
    libboost-serialization1.74.0 \
    && rm -rf /var/lib/apt/lists/*

# Install libssl1.1 from Ubuntu 18.04 (required for pre-compiled binaries)
# Create symlink for boost serialization to match the binary's expected library name
RUN wget -q http://archive.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2_amd64.deb \
    && dpkg -i libssl1.1_1.1.1f-1ubuntu2_amd64.deb \
    && rm libssl1.1_1.1.1f-1ubuntu2_amd64.deb \
    && ln -sf /usr/lib/x86_64-linux-gnu/libboost_serialization.so.1.74.0 /usr/lib/x86_64-linux-gnu/libboost_serialization.so.1.66.0

# Create directory structure
RUN mkdir -p /app/bin /app/data /app/lib

# Copy pre-compiled binaries
COPY bin /app/bin

# Copy data files
COPY data /app/data

# Copy library files
COPY lib /app/lib

# Install custom shared libraries to system library path
RUN cp /app/lib/redis-plus-plus/compile/libredis++.so /usr/lib/libredis++.so.1 && \
    cp /app/lib/RoutingKit/lib/libroutingkit.so /usr/lib/libroutingkit.so && \
    cp /app/lib/librdkafka/src/librdkafka.so.1 /usr/lib/librdkafka.so.1 && \
    cp /app/lib/librdkafka/src-cpp/librdkafka++.so.1 /usr/lib/librdkafka++.so.1 && \
    cp /app/lib/hiredis/libhiredis.so /usr/lib/libhiredis.so.1.0.0 && \
    ln -sf /usr/lib/libhiredis.so.1.0.0 /usr/lib/libhiredis.so.1 && \
    cp /app/lib/protobuf/src/.libs/libprotobuf-lite.so.22 /usr/lib/libprotobuf-lite.so.22 && \
    cp /app/lib/protobuf/src/.libs/libprotobuf.so.22 /usr/lib/libprotobuf.so.22 && \
    cp /app/lib/OSM-binary/src/libosmpbf.so /usr/lib/libosmpbf.so.1 && \
    ldconfig

# Make binaries executable
RUN chmod +x /app/bin/*

# Set working directory
WORKDIR /app

# Copy supervisord configuration
COPY supervisord.conf /etc/supervisor/conf.d/cms.conf

# Expose the API port
EXPOSE 9080

# Run supervisord to manage both services
CMD ["supervisord", "-n"]
