#!/usr/bin/env python3
"""
Jira Filter Permissions Script

Retrieves a Jira filter, parses its JQL to extract project references,
and checks "Create Sprint" permissions for each project.
"""

import argparse
import json
import os
import re
import sys
from json import JSONDecodeError
from typing import Dict, List, Optional, Set, Tuple

import requests


def get_auth_headers(api_token: str) -> Dict[str, str]:
    """Create authentication headers for Jira API."""
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def detect_api_version(jira_url: str, auth_headers: Dict[str, str]) -> int:
    """Try to detect Jira API version by testing both endpoints."""
    print(f"Detecting API version for {jira_url}...", file=sys.stderr)
    # Try API v3 first (Cloud)
    try:
        url = f"{jira_url}/rest/api/3/serverInfo"
        print(f"  Trying API v3: {url}", file=sys.stderr)
        response = requests.get(url, headers=auth_headers, timeout=5)
        if response.status_code == 200:
            print("  ✓ API v3 (Cloud) detected", file=sys.stderr)
            return 3
    except requests.RequestException as e:
        print(f"  API v3 not available: {e}", file=sys.stderr)

    # Fall back to API v2 (Data Center)
    print("  ✓ Using API v2 (Data Center)", file=sys.stderr)
    return 2


def get_filter(
    jira_url: str, filter_id: str, api_version: int, auth_headers: Dict[str, str]
) -> Dict:
    """Fetch filter details from Jira."""
    url = f"{jira_url}/rest/api/{api_version}/filter/{filter_id}"
    print(f"Fetching filter {filter_id}...", file=sys.stderr)
    print(f"  URL: {url}", file=sys.stderr)
    response = requests.get(url, headers=auth_headers)

    print(f"  Status code: {response.status_code}", file=sys.stderr)
    
    if response.status_code == 404:
        raise ValueError(f"Filter {filter_id} not found")
    if response.status_code == 401:
        raise ValueError("Authentication failed - check your API token")
    response.raise_for_status()

    try:
        return response.json()
    except JSONDecodeError as e:
        print(f"  Error: Failed to parse JSON response", file=sys.stderr)
        print(f"  Response text (first 500 chars): {response.text[:500]}", file=sys.stderr)
        raise ValueError(f"Invalid JSON response from filter endpoint: {e}. Response was: {response.text[:200]}")


def parse_jql_for_projects(jql: str) -> Set[str]:
    """Extract project identifiers from JQL string."""
    projects = set()

    # Pattern for project = "NAME" or project = KEY or project = 12345
    project_eq_pattern = re.compile(r'project\s*=\s*"?(?P<project>[^"\s()]+)"?', re.IGNORECASE)

    # Pattern for project in (P_ID1, P_ID2, ...)
    project_in_pattern = re.compile(
        r'project\s+in\s*\((?P<projects>[^\)]+)\)', re.IGNORECASE
    )

    # Find all project = matches
    for match in project_eq_pattern.finditer(jql):
        project = match.group("project").strip().strip('"')
        if project:
            projects.add(project)

    # Find all project in (...) matches
    for match in project_in_pattern.finditer(jql):
        projects_str = match.group("projects")
        # Split by comma and clean up each project identifier
        for project in projects_str.split(","):
            project = project.strip().strip('"')
            if project:
                projects.add(project)

    return projects


def resolve_project(
    identifier: str, jira_url: str, api_version: int, auth_headers: Dict[str, str]
) -> Optional[Dict[str, str]]:
    """Convert project identifier (key/name/ID) to project details."""
    print(f"  Resolving project: {identifier}", file=sys.stderr)
    # If identifier is numeric, treat it as project ID
    if identifier.isdigit():
        project_id = identifier
        print(f"    Treating as project ID", file=sys.stderr)
    else:
        # Otherwise, fetch project info to get ID
        url = f"{jira_url}/rest/api/{api_version}/project/{identifier}"
        print(f"    Fetching project by key/name: {url}", file=sys.stderr)
        try:
            response = requests.get(url, headers=auth_headers)
            print(f"    Status code: {response.status_code}", file=sys.stderr)
            if response.status_code == 404:
                print(f"Warning: Project '{identifier}' not found", file=sys.stderr)
                return None
            if response.status_code == 401:
                raise ValueError("Authentication failed - check your API token")
            response.raise_for_status()
            try:
                project_data = response.json()
            except JSONDecodeError as e:
                print(f"    Error: Failed to parse JSON response", file=sys.stderr)
                print(f"    Response text (first 500 chars): {response.text[:500]}", file=sys.stderr)
                raise ValueError(f"Invalid JSON response when resolving project '{identifier}': {e}. Response: {response.text[:200]}")
            project_id = str(project_data["id"])
        except requests.RequestException as e:
            print(f"Error fetching project '{identifier}': {e}", file=sys.stderr)
            return None

    # Fetch full project details using ID
    url = f"{jira_url}/rest/api/{api_version}/project/{project_id}"
    print(f"    Fetching project details by ID: {url}", file=sys.stderr)
    try:
        response = requests.get(url, headers=auth_headers)
        print(f"    Status code: {response.status_code}", file=sys.stderr)
        if response.status_code == 404:
            print(f"Warning: Project ID '{project_id}' not found", file=sys.stderr)
            return None
        response.raise_for_status()
        try:
            project_data = response.json()
        except JSONDecodeError as e:
            print(f"    Error: Failed to parse JSON response", file=sys.stderr)
            print(f"    Response text (first 500 chars): {response.text[:500]}", file=sys.stderr)
            raise ValueError(f"Invalid JSON response when fetching project ID '{project_id}': {e}. Response: {response.text[:200]}")
        return {
            "id": str(project_data["id"]),
            "key": project_data.get("key", ""),
            "name": project_data.get("name", ""),
        }
    except requests.RequestException as e:
        print(f"Error fetching project details for ID '{project_id}': {e}", file=sys.stderr)
        return None


def check_create_sprint_permission(
    project_id: str, jira_url: str, api_version: int, auth_headers: Dict[str, str]
) -> bool:
    """Check if user has 'Create Sprint' permission for the project."""
    url = f"{jira_url}/rest/api/{api_version}/mypermissions"
    params = {"projectId": project_id}
    print(f"    Checking permissions for project {project_id}...", file=sys.stderr)
    print(f"      URL: {url}?projectId={project_id}", file=sys.stderr)

    try:
        response = requests.get(url, headers=auth_headers, params=params)
        print(f"      Status code: {response.status_code}", file=sys.stderr)
        if response.status_code == 401:
            raise ValueError("Authentication failed - check your API token")
        response.raise_for_status()

        try:
            permissions_data = response.json()
        except JSONDecodeError as e:
            print(f"      Error: Failed to parse JSON response", file=sys.stderr)
            print(f"      Response text (first 500 chars): {response.text[:500]}", file=sys.stderr)
            raise ValueError(f"Invalid JSON response when checking permissions for project {project_id}: {e}. Response: {response.text[:200]}")

        permissions = permissions_data.get("permissions", {})
        create_sprint = permissions.get("CREATE_SPRINTS", {})
        return create_sprint.get("havePermission", False)
    except requests.RequestException as e:
        print(f"Error checking permissions for project {project_id}: {e}", file=sys.stderr)
        return False


def format_text_output(filter_data: Dict, project_results: List[Dict]) -> str:
    """Format results as text output."""
    lines = []
    lines.append(f"Filter: {filter_data.get('name', 'Unknown')} (ID: {filter_data.get('id', 'Unknown')})")
    lines.append(f"JQL: {filter_data.get('jql', 'N/A')}")
    lines.append("")
    lines.append("Projects:")

    for project in project_results:
        key = project.get("key", "N/A")
        project_id = project.get("id", "N/A")
        name = project.get("name", "N/A")
        has_permission = project.get("has_create_sprint_permission", False)
        permission_text = "Yes" if has_permission else "No"

        lines.append(
            f'  {key} (ID: {project_id}, Name: "{name}"): Create Sprint Permission: {permission_text}'
        )

    return "\n".join(lines)


def format_json_output(filter_data: Dict, project_results: List[Dict]) -> Dict:
    """Format results as JSON output."""
    return {
        "filter": {
            "id": filter_data.get("id", ""),
            "name": filter_data.get("name", ""),
            "jql": filter_data.get("jql", ""),
        },
        "projects": project_results,
    }


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Check 'Create Sprint' permissions for projects in a Jira filter"
    )
    parser.add_argument(
        "filter_id",
        type=str,
        nargs="?",
        help="Jira filter ID (numeric)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Export results to JSON file",
    )
    parser.add_argument(
        "--json-file",
        type=str,
        default="permissions.json",
        help="Custom JSON output file path (default: permissions.json)",
    )
    parser.add_argument(
        "--url",
        type=str,
        help="Jira instance URL (overrides JIRA_URL environment variable)",
    )
    parser.add_argument(
        "--token",
        type=str,
        help="Jira API token (overrides JIRA_API_TOKEN environment variable)",
    )
    parser.add_argument(
        "--api-version",
        type=int,
        choices=[2, 3],
        help="Force API version (2 for Data Center, 3 for Cloud)",
    )
    parser.add_argument(
        "--export-usage",
        action="store_true",
        help="Export usage documentation in markdown code block format",
    )

    args = parser.parse_args()

    # Handle --export-usage early
    if args.export_usage:
        help_text = parser.format_help()
        print("```")
        print(help_text.rstrip())
        print("```")
        sys.exit(0)

    # Validate filter_id is provided
    if not args.filter_id:
        parser.error("filter_id is required")
    
    # Validate filter_id is numeric
    if not args.filter_id.isdigit():
        print(f"Error: filter_id must be numeric, got '{args.filter_id}'", file=sys.stderr)
        sys.exit(1)

    # Get configuration from environment or arguments
    jira_url = args.url or os.getenv("JIRA_URL", "https://issues.redhat.com")
    api_token = args.token or os.getenv("JIRA_API_TOKEN")

    if not api_token:
        print(
            "Error: Jira API token required. Set JIRA_API_TOKEN environment variable or use --token",
            file=sys.stderr,
        )
        sys.exit(1)

    # Remove trailing slash from URL
    jira_url = jira_url.rstrip("/")

    # Setup authentication
    auth_headers = get_auth_headers(api_token)

    # Determine API version
    if args.api_version:
        api_version = args.api_version
    else:
        api_version = detect_api_version(jira_url, auth_headers)

    try:
        # Get filter
        print("Step 1: Fetching filter from Jira...", file=sys.stderr)
        filter_data = get_filter(jira_url, args.filter_id, api_version, auth_headers)
        print("  ✓ Filter fetched successfully", file=sys.stderr)
        jql = filter_data.get("jql", "")

        if not jql:
            print("Warning: Filter has no JQL", file=sys.stderr)
            sys.exit(0)

        # Print filter info
        print(f"\nFilter: {filter_data.get('name', 'Unknown')} (ID: {filter_data.get('id', 'Unknown')})")
        print(f"JQL: {jql}")
        print()

        # Parse JQL for projects
        print("Step 2: Parsing JQL for project references...", file=sys.stderr)
        project_identifiers = parse_jql_for_projects(jql)
        print(f"  ✓ Found {len(project_identifiers)} project reference(s): {sorted(project_identifiers)}", file=sys.stderr)

        if not project_identifiers:
            print("No projects found in filter JQL")
            sys.exit(0)

        # Resolve projects and check permissions
        print(f"\nStep 3: Resolving projects and checking permissions...", file=sys.stderr)
        project_results = []
        for identifier in sorted(project_identifiers):
            project_info = resolve_project(identifier, jira_url, api_version, auth_headers)
            if project_info:
                has_permission = check_create_sprint_permission(
                    project_info["id"], jira_url, api_version, auth_headers
                )
                project_info["has_create_sprint_permission"] = has_permission
                project_results.append(project_info)
                print(f"  ✓ {project_info.get('key', 'N/A')} - Permission: {'Yes' if has_permission else 'No'}", file=sys.stderr)

        # Output results
        print("\nStep 4: Generating output...", file=sys.stderr)
        if args.json:
            output = format_json_output(filter_data, project_results)
            with open(args.json_file, "w") as f:
                json.dump(output, f, indent=2)
            print(f"Results exported to {args.json_file}")
        else:
            output_text = format_text_output(filter_data, project_results)
            print(output_text)
        print("  ✓ Complete", file=sys.stderr)

    except ValueError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as e:
        print(f"\nHTTP error: {e}", file=sys.stderr)
        if hasattr(e, "response") and e.response is not None:
            print(f"Status code: {e.response.status_code}", file=sys.stderr)
            print(f"Response: {e.response.text[:500]}", file=sys.stderr)
        sys.exit(1)
    except JSONDecodeError as e:
        print(f"\nJSON parsing error: {e}", file=sys.stderr)
        print(f"This usually means the server returned HTML or plain text instead of JSON.", file=sys.stderr)
        print(f"Check that the Jira URL and API version are correct.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

