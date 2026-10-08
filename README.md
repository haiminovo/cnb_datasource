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

For a repository-scoped token, set `Repository path` in the datasource
credentials. Validation then skips `/user` and `/user/repos`, and checks only:

```text
GET /organization/group/repository
GET /organization/group/repository/-/git/contents
```

That mode requires `repo-basic-info:r` and `repo-code:r`, but does not require
`account-profile:r` or `account-engage:r`.

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
- `Branch, tag, or commit`: optional CNB `ref`; leave empty for the default
  branch
- `Maximum repositories`: default `20`
- `Include code files`: enabled by default
- `Code files per repository`: default `100`
- `Issues per repository`: default `5`
- `Pull requests per repository`: default `5`

After the page list is generated, select the repository metadata, README, code,
issue, and pull request documents that should be imported.

### Repository paths

Copy the repository path from the CNB browser URL. For example:

```text
https://cnb.cool/organization/group/repository
```

The corresponding repository path is:

```text
organization/group/repository
```

Accepted formats:

```text
organization/group/repository
https://cnb.cool/organization/group/repository
https://cnb.cool/organization/group/repository.git
https://cnb.cool/organization/group/repository/-/blob/main/README.md
```

Multiple repositories can be separated by commas or new lines:

```text
organization/group/repository-a
organization/group/repository-b
organization/other/repository
```

Do not enter only the repository name, such as `repository`. The full
namespace path is required. Leave this field empty to scan all repositories
accessible to the configured CNB token.

`Maximum repositories` only limits automatic repository discovery. Explicit
repository paths are all processed and are not truncated by that value.

If you leave repository paths empty and also set a ref, the plugin applies that
ref to every accessible repository. Repositories where the ref does not exist or
cannot be read are shown with `(ref unavailable)` and their README/code files
are skipped. This prevents one inaccessible repository from failing the whole
datasource.

### Branch, tag, and commit

The import form exposes three optional fields:

```text
Branch
Tag
Commit SHA
```

Set only one of them:

| Field | Example | Resolution |
| :- | :- | :- |
| Branch | `develop` | Resolves the branch through the CNB branches API |
| Tag | `v1.0.0` | Resolves the tag through the CNB tags API |
| Commit SHA | `a1b2c3d4...` | Uses the commit SHA directly |

If all three fields are empty, the repository default branch is used. Setting
more than one field returns a validation error.

The plugin resolves branch and tag values to a commit SHA before reading files.
This keeps branch and tag names distinct when both use the same name. For branch
names containing slashes, enter the complete name directly, such as
`feature/login`.

## Import Behavior

- Access is read-only.
- Leave the ref empty to read the repository default branch through CNB `HEAD`.
- Set the ref to a branch, tag, or commit SHA to import that version.
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
