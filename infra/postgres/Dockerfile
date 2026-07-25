# PostgreSQL for CMS Platform
FROM postgres:16-alpine

LABEL maintainer="CMS Platform"
LABEL description="PostgreSQL database for EMS data"

# Copy initialization scripts
COPY init/ /docker-entrypoint-initdb.d/

# Healthcheck
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-ems}
