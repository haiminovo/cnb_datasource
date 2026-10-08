# CNB Datasource Plugin Privacy Policy

Effective date: September 30, 2026

## Data accessed

This plugin reads only data that the configured CNB access token or OAuth
authorization can access. Depending on how it is used, that data can include:

- CNB account profile and account ID
- repositories visible to the account
- repository metadata and README/file contents
- issues, pull requests, labels, assignees, reviewers, and comments

## Data use

The data is used only to list importable CNB documents and return the selected
content to Dify. The plugin does not modify or delete CNB resources.

## Third-party services

The plugin sends requests directly to CNB. CNB receives the configured access
token and the API requests needed to read the selected account, repositories,
files, issues, pull requests, and comments. CNB processes that data under the
CNB privacy policy:

https://docs.cnb.cool/zh/saas/privacy.html

The plugin does not add analytics, advertising, tracking, or any other
third-party data recipient.

## Credentials

Access tokens and OAuth tokens are stored by Dify using its credential storage.
Requests are sent directly from the plugin runner to the configured CNB API
endpoint over the configured URL. Use HTTPS for production deployments.

## Retention

This plugin does not maintain an independent database. Any retention, cache, or
embedding behavior is controlled by the Dify deployment that installs the
plugin.

## User control

You can revoke access at any time by deleting or rotating the CNB access token,
or by revoking the OAuth application authorization in CNB.
