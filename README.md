# CNB Datasource for Dify

Import repositories, source files, issues, pull requests, and comments from
[CNB](https://cnb.cool) into Dify knowledge pipelines.

Source repository:
https://github.com/haiminovo/cnb_datasource

## Features

- Import repository metadata and README files
- Recursively list source, configuration, and documentation files
- Import issues, pull requests, labels, and comments
- Filter imports to one or more repository paths
- Support CNB SaaS and enterprise API endpoints
- Read-only access to CNB data

## Requirements

- Dify 1.9.0 or later
- Python 3.12 plugin runtime
- A CNB access token or an approved CNB OAuth application

## Setup

### 1. Create a CNB access token

Open CNB Personal Settings, then create an access token with these scopes:

```text
account-profile:r
account-engage:r
repo-basic-info:r
repo-code:r
repo-issue:r
repo-pr:r
repo-notes:r
```

Private repositories also require the matching private-resource scope and
repository access.

### 2. Connect the datasource in Dify

Configure:

- `CNB Access Token`: the token created above
- `CNB API URL`: `https://api.cnb.cool` for CNB SaaS
- `CNB URL`: `https://cnb.cool` for CNB SaaS

For an enterprise deployment, replace the URL fields with the deployment
endpoints.

### 3. Configure the import

- `Repository paths`: optional comma-separated paths such as
  `group/repository`
- `Maximum repositories`: default `20`
- `Include code files`: enabled by default
- `Code files per repository`: default `100`
- `Issues per repository`: default `5`
- `Pull requests per repository`: default `5`

After the page list is generated, select the repository metadata, README, code,
issue, and pull request documents that should be imported.

## Import Behavior

- Access is read-only.
- The plugin reads the repository default branch through CNB `HEAD`.
- Other branches, tags, and individual commits are not selected.
- Generated output, dependency, cache, binary, and lock directories are skipped.
- Code files are exposed as separate Dify documents.

## OAuth

The plugin includes a CNB OAuth 2.0 authorization flow. CNB currently requires
an operator to approve and register OAuth applications. Access-token
authentication is the recommended setup for normal use.

## Connection

The plugin connects directly to:

- `https://api.cnb.cool`
- `https://cnb.cool`

For enterprise deployments, the configured API and web endpoints are used
instead.

## Privacy

The plugin accesses only CNB data allowed by the configured token or OAuth
authorization. The data is sent directly to CNB and the Dify installation that
runs the plugin. See [PRIVACY.md](PRIVACY.md) for details.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```
