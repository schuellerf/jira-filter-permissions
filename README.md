# Jira Filter Permissions

This Python script retrieves a Jira filter by ID, parses its JQL to extract project references, and checks whether the authenticated user has "Create Sprint" permission in each referenced project.

The script supports both Jira Data Center (API v2) and Cloud (API v3) editions, automatically detecting the API version or allowing manual override.

For usage instructions, see [usage.md](usage.md) (generate it with `make usage`).

