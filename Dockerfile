FROM python:3.13-alpine

# Install dependencies
RUN apk add --no-cache bash curl jq git

# Install Python packages with proper YAML handling for CloudFormation
RUN pip install requests pyyaml cfn-flip

# Copy everything including your local Python module
COPY . /app
WORKDIR /app

# Install the local cfn-sanitizer module
RUN pip install .

# Fix git permissions for GitHub Actions
RUN git config --global --add safe.directory /github/workspace

# Make entrypoint executable
RUN chmod +x /app/entrypoint.py

ENTRYPOINT ["python", "/app/entrypoint.py"]

