FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg for media; EGL/GLES are loaded by MediaPipe even when it runs on the CPU.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libegl1 libgles2 libgl1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY egolabs ./egolabs
RUN pip install .

COPY alembic.ini ./
COPY alembic ./alembic

# Bake the pinned models (hand landmarker, object detector) into the image (checksum-verified) so workers need no download at runtime.
ENV MODEL_CACHE_DIR=/opt/egolabs/models
RUN python -c "from egolabs.cv.assets import PINNED, ensure; [print(ensure(a)) for a in PINNED]"

RUN useradd --create-home --uid 1000 egolabs
USER egolabs

EXPOSE 8000
CMD ["sh", "-c", "python -m egolabs.bootstrap && exec uvicorn egolabs.app:app --host 0.0.0.0 --port 8000"]
