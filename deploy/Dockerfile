FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/bugbrief
COPY backend/requirements.txt /tmp/requirements.txt
# colorama is included in the Windows development lock; it is harmless on Linux.
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY backend/requirements-model.in /tmp/requirements-model.in
RUN pip install --no-cache-dir torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r /tmp/requirements-model.in
COPY backend/app ./backend/app
COPY ml/data/examples.json ./ml/data/examples.json
COPY models ./models
RUN useradd --create-home --uid 10001 bugbrief
USER bugbrief
WORKDIR /srv/bugbrief/backend
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
