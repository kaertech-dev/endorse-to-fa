FROM python:3.11-slim

# Prevent python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1
# Prevent python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# PyMySQL and bcrypt both ship prebuilt wheels for this base image, so no
# compiler toolchain is needed. If you later add a package that needs to
# compile from source, add build-essential here.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user (this app handles login credentials + DB creds)
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 5005

CMD ["python", "app.py"]