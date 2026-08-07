```
usage: jira_filter_permissions.py [-h] [--json] [--json-file JSON_FILE]
                                  [--url URL] [--token TOKEN] [--email EMAIL]
                                  [--api-version {2,3}] [--export-usage]
                                  [--verbose] [--list-permissions]
                                  [--permission-key PERMISSION_KEY]
                                  [filter_id]

Check 'Create Sprint' permissions for projects in a Jira filter

positional arguments:
  filter_id             Jira filter ID (numeric)

options:
  -h, --help            show this help message and exit
  --json                Export results to JSON file
  --json-file JSON_FILE
                        Custom JSON output file path (default:
                        permissions.json)
  --url URL             Jira instance URL (overrides JIRA_URL environment
                        variable)
  --token TOKEN         Jira API token (overrides JIRA_API_TOKEN environment
                        variable)
  --email EMAIL         Jira account email (overrides JIRA_EMAIL environment
                        variable)
  --api-version {2,3}   Force API version (2 for Data Center, 3 for Cloud)
  --export-usage        Export usage documentation in markdown code block
                        format
  --verbose, -v         Enable verbose output (DEBUG level logging)
  --list-permissions    List all available permission keys (union over all
                        projects) and exit
  --permission-key PERMISSION_KEY
                        Permission key to check (default:
                        MANAGE_SPRINTS_PERMISSION)
```
