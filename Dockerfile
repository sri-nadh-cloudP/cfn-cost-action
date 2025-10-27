FROM python:3.13-alpine

# Install system dependencies and runtimes for all CDK languages
# - Node.js/npm: Required for CDK CLI and JavaScript/TypeScript CDK apps
# - openjdk11: For Java CDK apps
# - maven: For Java CDK apps dependency management (Maven projects)
# - gradle: For Java CDK apps dependency management (Gradle projects)
# - go: For Go CDK apps
# - dotnet8-sdk: For C# CDK apps
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    git \
    nodejs \
    npm \
    openjdk11 \
    maven \
    gradle \
    go \
    dotnet8-sdk

# Install AWS CDK CLI globally
RUN npm install -g aws-cdk

# Set up Go environment
ENV GOPATH=/go
ENV PATH=$PATH:$GOPATH/bin

# Install Python packages with proper YAML handling for CloudFormation
# Also install aws-cdk-lib for Python CDK apps
RUN pip install requests pyyaml cfn-flip aws-cdk-lib constructs

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

