FROM python:3.13-alpine

# Install dependencies
RUN apk add --no-cache bash curl jq git

# Install Python packages
RUN pip install requests pyyaml

# Copy everything including your local Python module
COPY . /app
WORKDIR /app

# Install the local cfn-sanitizer module
RUN pip install .

# Make entrypoint executable
RUN chmod +x /app/entrypoint.py

ENTRYPOINT ["python", "/app/entrypoint.py"]

