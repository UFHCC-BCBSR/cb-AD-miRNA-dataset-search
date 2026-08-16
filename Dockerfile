# -------------------------------------------------
# Base image – lightweight Python with pip
# -------------------------------------------------
FROM python:3.11-slim

# Install OS packages needed by pandas & lxml (gcc, libxml2-dev, libxslt1-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies as root so they go to /usr/local/bin
RUN pip install --no-cache-dir flask gunicorn pandas requests lxml pysradb

# Create a non‑root user (recommended on Hipergator)
RUN useradd -m appuser
USER appuser
WORKDIR /home/appuser/app

# Copy repository contents (excluding .git, .venv, etc.)
COPY --chown=appuser . .

# Expose the port the Flask app will listen on (pubapps forwards this)
EXPOSE 3838

# Default command – run the app with Gunicorn (production‑grade WSGI server)
CMD ["gunicorn", "-b", "0.0.0.0:3838", "app:app"]
