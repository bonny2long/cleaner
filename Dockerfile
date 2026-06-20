FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -e .
ENV PYTHONUNBUFFERED=1
EXPOSE 8092
CMD ["python", "-m", "cleaner.server", "--host", "0.0.0.0", "--port", "8092"]
