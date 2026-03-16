# Use MCR image to avoid Docker Hub rate limits
FROM mcr.microsoft.com/devcontainers/python:3.11

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/app/ ./app/

# Expose port
EXPOSE 3978

# Set environment variable for port
ENV PORT=3978

# Run the application
CMD ["python", "-m", "app"]