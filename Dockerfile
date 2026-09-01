# CyberFeedback — production image.
#
# Serves the app under waitress (never Flask's development server). Assessment
# data and generated PDFs live on a mounted volume, not in the image layer, so
# a redeploy cannot destroy a client's campaign.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: this layer is cached unless requirements change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/

# The two directories that hold client data. Declared as volumes so they are
# not baked into the image and survive container replacement.
RUN mkdir -p /app/src/data /app/src/Generated_PDF_Report
VOLUME ["/app/src/data", "/app/src/Generated_PDF_Report"]

# Assessment responses are sensitive; the process that handles them does not
# need root, and the data directories are readable only by its owner.
RUN useradd --create-home --uid 10001 cyberfeedback \
    && chown -R cyberfeedback:cyberfeedback /app \
    && chmod 700 /app/src/data /app/src/Generated_PDF_Report
USER cyberfeedback

# Bind to every interface *inside the container*; publish it deliberately, and
# put HTTPS in front of it. serve.py refuses to start on a non-loopback bind
# without CYBERFEEDBACK_ADMIN_TOKEN and CYBERFEEDBACK_PUBLIC_URL set.
ENV CYBERFEEDBACK_HOST=0.0.0.0 \
    CYBERFEEDBACK_PORT=8080
EXPOSE 8080

CMD ["python", "src/serve.py"]
