FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY .env .env

# Expose port
EXPOSE 3978

# Set environment variable for port
ENV PORT=3978

# Run the application
CMD ["python", "-m", "app"]