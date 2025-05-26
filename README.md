# CloudFormation Cost Action

A GitHub Action that detects changes in CloudFormation templates, sanitizes sensitive information, and provides cost estimates as PR comments.

## Usage

```yaml
name: CloudFormation Cost Analysis

on:
  pull_request:
    paths:
      - '**.yml'
      - '**.yaml'
      - '**.json'

jobs:
  analyze-cfn-costs:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0
      
      - name: CFN Cost Analysis
        uses: your-username/cfn-cost-action@main
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

## Token Permissions

For this action to work correctly, you need to ensure the GitHub token has the right permissions:

### Option 1: Set Permissions in Workflow

Add a `permissions` section to your job as shown in the example above:

```yaml
permissions:
  contents: read
  pull-requests: write
```

### Option 2: Use a Personal Access Token (PAT)

If you're using a PAT instead of `GITHUB_TOKEN`, make sure it has `repo` scope:

```yaml
- name: CFN Cost Analysis
  uses: your-username/cfn-cost-action@main
  with:
    github-token: ${{ secrets.PAT_TOKEN }}
```

## How it Works

1. Detects CloudFormation templates changed in the PR
2. Sanitizes the templates to remove sensitive data
3. Sends templates to the cost analysis service
4. Posts detailed cost breakdown as PR comments

## Requirements

- Python 3.10+
- Docker (for local development) 