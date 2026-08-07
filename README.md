# Jira Filter Permissions

This Python script retrieves a Jira filter by ID, parses its JQL to extract project references, and checks whether the authenticated user has "Create Sprint" permission in each referenced project.

The script supports both Jira Data Center (API v2) and Cloud (API v3) editions, automatically detecting the API version or allowing manual override.

**Limitation:** The script only parses the given filter's JQL directly. It does not currently support nested filters (filters that reference other filters).

For usage instructions, see [usage.md](usage.md) (generate it with `make usage`).

## Authentication

The script uses HTTP Basic auth with your Atlassian account email and API token
(`email:token`). Bearer tokens are not supported.

Set these environment variables (or the matching CLI flags):

| Variable | Flag | Example | Notes |
|---|---|---|---|
| `JIRA_URL` | `--url` | `https://redhat.atlassian.net` | Base site URL only — no path (`/jira`, `/browse/...`, etc.). A trailing slash is optional and is stripped. |
| `JIRA_EMAIL` | `--email` | `you@example.com` | Required. Atlassian account email used with the API token. |
| `JIRA_API_TOKEN` | `--token` | *(your token)* | Required. See below. |

Examples:

```bash
export JIRA_EMAIL=you@example.com
export JIRA_API_TOKEN=your-api-token
```

For **Jira Cloud**, create a token as follows:

1. Open your profile
2. Go to **Security**
3. Choose **Create and manage API tokens**
4. Select **Create API token**

## Development

This project uses [pre-commit](https://pre-commit.com/) hooks to ensure code quality. To set up:

```bash
pip install pre-commit
pre-commit install
```

The hooks will automatically check for unused imports, formatting issues, and other code quality problems before each commit.
