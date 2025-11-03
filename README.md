# Jira Filter Permissions

This Python script retrieves a Jira filter by ID, parses its JQL to extract project references, and checks whether the authenticated user has "Create Sprint" permission in each referenced project.

The script supports both Jira Data Center (API v2) and Cloud (API v3) editions, automatically detecting the API version or allowing manual override.

**Limitation:** The script only parses the given filter's JQL directly. It does not currently support nested filters (filters that reference other filters).

For usage instructions, see [usage.md](usage.md) (generate it with `make usage`).

## Development

This project uses [pre-commit](https://pre-commit.com/) hooks to ensure code quality. To set up:

```bash
pip install pre-commit
pre-commit install
```

The hooks will automatically check for unused imports, formatting issues, and other code quality problems before each commit.
