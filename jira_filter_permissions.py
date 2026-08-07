#!/usr/bin/env python3
"""
Jira Filter Permissions Script

Retrieves a Jira filter, parses its JQL to extract project references,
and checks "Create Sprint" permissions for each project.
"""

import argparse
import base64
import json
import logging
import os
import re
import sys
from json import JSONDecodeError
from typing import Dict, List, Optional, Set

import requests

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def get_auth_headers(email: str, api_token: str) -> Dict[str, str]:
    """Create authentication headers for Jira API (Basic auth: email + API token)."""
    credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def detect_api_version(jira_url: str, auth_headers: Dict[str, str]) -> int:
    """Try to detect Jira API version by testing both endpoints.

    Cloud (*.atlassian.net) prefers API v3. Data Center typically uses v2.
    Cloud also serves many v2 endpoints, so hostname and accountId are used
    to avoid mis-detecting Cloud as Data Center.
    """
    logger.info(f"Detecting API version for {jira_url}...")

    # Cloud sites always use API v3 for this tool
    if ".atlassian.net" in jira_url:
        logger.info("API v3 (Cloud) selected based on atlassian.net hostname")
        return 3

    # Try API v2 first (Data Center/Server - more common for self-hosted instances)
    try:
        url = f"{jira_url}/rest/api/2/myself"
        logger.debug(f"Trying API v2: {url}")
        response = requests.get(url, headers=auth_headers, timeout=5)
        if response.status_code == 200:
            try:
                data = response.json()
                # Verify it's actually JSON with expected fields
                if isinstance(data, dict) and (
                    "self" in data or "key" in data or "accountId" in data
                ):
                    logger.info("API v2 (Data Center/Server) detected")
                    return 2
            except JSONDecodeError:
                # Not valid JSON, probably HTML error page
                logger.debug("API v2 returned non-JSON response")
    except requests.RequestException as e:
        logger.debug(f"API v2 check failed: {e}")

    # Try API v3 (Cloud or newer instances)
    try:
        url = f"{jira_url}/rest/api/3/myself"
        logger.debug(f"Trying API v3: {url}")
        response = requests.get(url, headers=auth_headers, timeout=5)
        if response.status_code == 200:
            try:
                data = response.json()
                # Verify it's actually JSON with expected fields (v3 uses accountId)
                if isinstance(data, dict) and ("accountId" in data or "self" in data):
                    logger.info("API v3 (Cloud) detected")
                    return 3
            except JSONDecodeError:
                # Not valid JSON
                logger.debug("API v3 returned non-JSON response")
    except requests.RequestException as e:
        logger.debug(f"API v3 check failed: {e}")

    # Default to v2 if detection fails (safer for Data Center)
    logger.warning("Could not detect API version, defaulting to v2 (Data Center)")
    return 2


def get_filter(
    jira_url: str, filter_id: str, api_version: int, auth_headers: Dict[str, str]
) -> Dict:
    """Fetch filter details from Jira."""
    url = f"{jira_url}/rest/api/{api_version}/filter/{filter_id}"
    logger.debug(f"Fetching filter {filter_id}")
    logger.debug(f"URL: {url}")
    response = requests.get(url, headers=auth_headers)

    logger.debug(f"Status code: {response.status_code}")

    if response.status_code == 404:
        raise ValueError(f"Filter {filter_id} not found")
    if response.status_code == 401:
        raise ValueError("Authentication failed - check your API token")
    response.raise_for_status()

    try:
        return response.json()
    except JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.debug(f"Response text (first 500 chars): {response.text[:500]}")
        raise ValueError(
            f"Invalid JSON response from filter endpoint: {e}. Response was: {response.text[:200]}"
        )


def parse_jql_for_projects(jql: str) -> Set[str]:
    """Extract project identifiers from JQL string."""
    projects = set()

    # Pattern for project = "NAME" or project = KEY or project = 12345
    project_eq_pattern = re.compile(
        r'project\s*=\s*"?(?P<project>[^"\s()]+)"?', re.IGNORECASE
    )

    # Pattern for project in (P_ID1, P_ID2, ...)
    project_in_pattern = re.compile(
        r"project\s+in\s*\((?P<projects>[^\)]+)\)", re.IGNORECASE
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
    logger.debug(f"Resolving project: {identifier}")
    # If identifier is numeric, treat it as project ID
    if identifier.isdigit():
        project_id = identifier
        logger.debug("Treating as project ID")
    else:
        # Otherwise, fetch project info to get ID
        url = f"{jira_url}/rest/api/{api_version}/project/{identifier}"
        logger.debug(f"Fetching project by key/name: {url}")
        try:
            response = requests.get(url, headers=auth_headers)
            logger.debug(f"Status code: {response.status_code}")
            if response.status_code == 404:
                logger.warning(f"Project '{identifier}' not found")
                return None
            if response.status_code == 401:
                raise ValueError("Authentication failed - check your API token")
            response.raise_for_status()
            try:
                project_data = response.json()
            except JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                logger.debug(f"Response text (first 500 chars): {response.text[:500]}")
                raise ValueError(
                    f"Invalid JSON response when resolving project '{identifier}': {e}. Response: {response.text[:200]}"
                )
            project_id = str(project_data["id"])
        except requests.RequestException as e:
            logger.error(f"Error fetching project '{identifier}': {e}")
            return None

    # Fetch full project details using ID
    url = f"{jira_url}/rest/api/{api_version}/project/{project_id}"
    logger.debug(f"Fetching project details by ID: {url}")
    try:
        response = requests.get(url, headers=auth_headers)
        logger.debug(f"Status code: {response.status_code}")
        if response.status_code == 404:
            logger.warning(f"Project ID '{project_id}' not found")
            return None
        response.raise_for_status()
        try:
            project_data = response.json()
        except JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Response text (first 500 chars): {response.text[:500]}")
            raise ValueError(
                f"Invalid JSON response when fetching project ID '{project_id}': {e}. Response: {response.text[:200]}"
            )
        return {
            "id": str(project_data["id"]),
            "key": project_data.get("key", ""),
            "name": project_data.get("name", ""),
        }
    except requests.RequestException as e:
        logger.error(f"Error fetching project details for ID '{project_id}': {e}")
        return None


def log_permissions_structure(obj: Dict, indent: int = 0, prefix: str = "") -> None:
    """Recursively log permissions structure for debugging."""
    indent_str = " " * indent
    for key, value in obj.items():
        if isinstance(value, dict):
            logger.debug(f"{indent_str}{prefix}{key}:")
            log_permissions_structure(value, indent + 2, "  ")
        elif isinstance(value, list):
            logger.debug(f"{indent_str}{prefix}{key}: [list with {len(value)} items]")
            if value and isinstance(value[0], dict):
                log_permissions_structure(value[0], indent + 2, "  [0] ")
        else:
            logger.debug(f"{indent_str}{prefix}{key}: {value}")


def get_all_permission_keys(
    jira_url: str, api_version: int, auth_headers: Dict[str, str]
) -> List[str]:
    """Return all permission keys defined on the Jira instance."""
    url = f"{jira_url}/rest/api/{api_version}/permissions"
    logger.debug(f"Fetching all permission definitions: {url}")
    response = requests.get(url, headers=auth_headers)
    if response.status_code == 401:
        raise ValueError("Authentication failed - check your API token")
    response.raise_for_status()
    data = response.json()
    permissions = data.get("permissions", data)
    if not isinstance(permissions, dict):
        raise ValueError("Unexpected response from /permissions endpoint")
    return sorted(permissions.keys())


def get_permissions(
    project_id: str,
    jira_url: str,
    api_version: int,
    auth_headers: Dict[str, str],
    permission_keys: List[str],
) -> Optional[Dict]:
    """Get permissions for a project. Returns permissions dict or None on error.

    Jira Cloud requires the ``permissions`` query parameter (comma-separated
    keys). Data Center accepts it as well, so we always send it.
    """
    if not permission_keys:
        raise ValueError("permission_keys must not be empty")

    url = f"{jira_url}/rest/api/{api_version}/mypermissions"
    params = {
        "projectId": project_id,
        "permissions": ",".join(permission_keys),
    }
    logger.debug(f"Getting permissions for project {project_id}")
    logger.debug(f"URL: {url}")
    logger.debug(f"Params: projectId={project_id}, permissions={params['permissions']}")

    try:
        response = requests.get(url, headers=auth_headers, params=params)
        logger.debug(f"Status code: {response.status_code}")
        if response.status_code == 401:
            raise ValueError("Authentication failed - check your API token")
        if response.status_code >= 400:
            logger.debug(f"Error response body: {response.text[:500]}")
        response.raise_for_status()

        try:
            permissions_data = response.json()
        except JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Response text (first 500 chars): {response.text[:500]}")
            raise ValueError(
                f"Invalid JSON response when checking permissions for project {project_id}: {e}. Response: {response.text[:200]}"
            )

        # Log the full permissions structure (DEBUG level)
        logger.debug("Full permissions response structure:")
        log_permissions_structure(permissions_data, indent=2)

        # Extract permissions object - handle different response structures
        permissions = permissions_data.get("permissions", {})
        if not permissions and isinstance(permissions_data, dict):
            # If no "permissions" key, maybe permissions are at top level?
            # Check for common patterns
            logger.debug("Note: No 'permissions' key found, checking top-level keys...")
            if len(permissions_data) == 1:
                # Maybe permissions are the only key?
                first_key = list(permissions_data.keys())[0]
                if isinstance(permissions_data[first_key], dict):
                    permissions = permissions_data[first_key]
                    logger.debug(f"Using '{first_key}' as permissions object")
            else:
                # Try using the whole response as permissions
                permissions = permissions_data
                logger.debug("Using entire response as permissions object")

        return permissions
    except requests.RequestException as e:
        logger.error(f"Error getting permissions for project {project_id}: {e}")
        return None


def check_permission(
    project_id: str,
    jira_url: str,
    api_version: int,
    auth_headers: Dict[str, str],
    permission_key: str,
) -> bool:
    """Check if user has a specific permission for the project."""
    permissions = get_permissions(
        project_id, jira_url, api_version, auth_headers, [permission_key]
    )
    if permissions is None:
        return False

    # List all available permission keys (DEBUG level)
    logger.debug("Available permission keys:")
    for perm_key in sorted(permissions.keys()):
        perm_value = permissions[perm_key]
        if isinstance(perm_value, dict):
            have_permission = perm_value.get("havePermission", False)
            perm_id = perm_value.get("id", "N/A")
            perm_name = perm_value.get("name", "N/A")
            logger.debug(
                f"  - {perm_key}: id={perm_id}, name='{perm_name}', havePermission={have_permission}"
            )
        else:
            logger.debug(f"  - {perm_key}: {perm_value}")

    # Check the specified permission key
    if permission_key in permissions:
        perm = permissions[permission_key]
        if isinstance(perm, dict):
            has_permission = perm.get("havePermission", False)
            logger.debug(f"Checking {permission_key}: havePermission={has_permission}")
            return has_permission
        else:
            logger.debug(
                f"Permission key {permission_key} exists but has unexpected format: {perm}"
            )
            return False
    else:
        logger.warning(
            f"Permission key '{permission_key}' not found in available permissions"
        )
        logger.debug("Available permission keys listed above.")
        return False


def format_text_output(
    filter_data: Dict, project_results: List[Dict], permission_key: str
) -> str:
    """Format results as text output."""
    lines = []
    lines.append(
        f"Filter: {filter_data.get('name', 'Unknown')} (ID: {filter_data.get('id', 'Unknown')})"
    )
    lines.append(f"JQL: {filter_data.get('jql', 'N/A')}")
    lines.append("")
    lines.append("Projects:")

    for project in project_results:
        key = project.get("key", "N/A")
        project_id = project.get("id", "N/A")
        name = project.get("name", "N/A")
        has_permission = project.get("has_permission", False)
        permission_text = "Yes" if has_permission else "No"

        lines.append(
            f'  {key} (ID: {project_id}, Name: "{name}"): {permission_key} Permission: {permission_text}'
        )

    return "\n".join(lines)


def format_json_output(
    filter_data: Dict, project_results: List[Dict], permission_key: str
) -> Dict:
    """Format results as JSON output."""
    return {
        "filter": {
            "id": filter_data.get("id", ""),
            "name": filter_data.get("name", ""),
            "jql": filter_data.get("jql", ""),
        },
        "permission_key": permission_key,
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
        "--email",
        type=str,
        help="Jira account email (overrides JIRA_EMAIL environment variable)",
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
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output (DEBUG level logging)",
    )
    parser.add_argument(
        "--list-permissions",
        action="store_true",
        help="List all available permission keys (union over all projects) and exit",
    )
    parser.add_argument(
        "--permission-key",
        type=str,
        default="MANAGE_SPRINTS_PERMISSION",
        help="Permission key to check (default: MANAGE_SPRINTS_PERMISSION)",
    )

    args = parser.parse_args()

    # Set logging level based on verbose flag
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)

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
        logger.error(f"filter_id must be numeric, got '{args.filter_id}'")
        sys.exit(1)

    # Get configuration from environment or arguments
    jira_url = args.url or os.getenv("JIRA_URL", "https://redhat.atlassian.net")
    api_token = args.token or os.getenv("JIRA_API_TOKEN")
    jira_email = args.email or os.getenv("JIRA_EMAIL")

    if not api_token:
        logger.error(
            "Jira API token required. Set JIRA_API_TOKEN environment variable or use --token"
        )
        sys.exit(1)

    if not jira_email:
        logger.error(
            "Jira account email required. Set JIRA_EMAIL environment variable or use --email"
        )
        sys.exit(1)

    # Remove trailing slash from URL
    jira_url = jira_url.rstrip("/")

    # Setup authentication (Basic auth: email + API token)
    auth_headers = get_auth_headers(jira_email, api_token)

    # Determine API version
    if args.api_version:
        api_version = args.api_version
    else:
        api_version = detect_api_version(jira_url, auth_headers)

    try:
        # Get filter
        logger.info("Step 1: Fetching filter from Jira...")
        filter_data = get_filter(jira_url, args.filter_id, api_version, auth_headers)
        logger.info("Filter fetched successfully")
        jql = filter_data.get("jql", "")

        if not jql:
            logger.warning("Filter has no JQL")
            sys.exit(0)

        # Print filter info (to stdout)
        print(
            f"\nFilter: {filter_data.get('name', 'Unknown')} (ID: {filter_data.get('id', 'Unknown')})"
        )
        print(f"JQL: {jql}")
        print()

        # Parse JQL for projects
        logger.info("Step 2: Parsing JQL for project references...")
        project_identifiers = parse_jql_for_projects(jql)
        logger.info(
            f"Found {len(project_identifiers)} project reference(s): {sorted(project_identifiers)}"
        )

        if not project_identifiers:
            print("No projects found in filter JQL")
            sys.exit(0)

        # Resolve projects
        logger.info("Step 3: Resolving projects...")
        projects = []
        for identifier in sorted(project_identifiers):
            project_info = resolve_project(
                identifier, jira_url, api_version, auth_headers
            )
            if project_info:
                projects.append(project_info)

        if not projects:
            logger.warning("No valid projects found")
            sys.exit(0)

        # Handle --list-permissions mode
        if args.list_permissions:
            logger.info("Collecting all permission keys from all projects...")
            all_permission_keys_list = get_all_permission_keys(
                jira_url, api_version, auth_headers
            )
            logger.info(
                f"Found {len(all_permission_keys_list)} permission definition(s)"
            )
            all_permission_keys = set()
            permission_details = {}  # key -> {id, name, projects_with_permission}

            for project_info in projects:
                project_id = project_info["id"]
                project_key = project_info.get("key", "N/A")
                logger.info(f"Checking permissions for {project_key}...")

                permissions = get_permissions(
                    project_id,
                    jira_url,
                    api_version,
                    auth_headers,
                    all_permission_keys_list,
                )
                if permissions:
                    for perm_key, perm_value in permissions.items():
                        all_permission_keys.add(perm_key)
                        if perm_key not in permission_details:
                            permission_details[perm_key] = {
                                "id": perm_value.get("id", "N/A")
                                if isinstance(perm_value, dict)
                                else "N/A",
                                "name": perm_value.get("name", "N/A")
                                if isinstance(perm_value, dict)
                                else "N/A",
                                "projects": [],
                            }
                        if isinstance(perm_value, dict) and perm_value.get(
                            "havePermission", False
                        ):
                            permission_details[perm_key]["projects"].append(project_key)

            print()
            title = "All available permission keys:"
            print(title)
            print("=" * len(title))
            print()
            # Print all permission keys (two lines each)
            for perm_key in sorted(all_permission_keys):
                details = permission_details.get(perm_key, {})
                perm_name = details.get("name", "N/A")
                projects_with = details.get("projects", [])

                print(f'{perm_key} "{perm_name}"')
                if projects_with:
                    projects_str = ", ".join(sorted(projects_with))
                    print(f"  Granted in projects: {projects_str}")
                else:
                    print("  Not granted in any project")
            sys.exit(0)

        # Check permissions
        logger.info("Step 4: Checking permissions...")
        logger.info(f"Checking permission key: {args.permission_key}")
        project_results = []
        for project_info in projects:
            has_permission = check_permission(
                project_info["id"],
                jira_url,
                api_version,
                auth_headers,
                args.permission_key,
            )
            project_info["has_permission"] = has_permission
            project_results.append(project_info)
            logger.info(
                f"{project_info.get('key', 'N/A')} - Permission: {'Yes' if has_permission else 'No'}"
            )

        # Output results
        logger.info("Step 5: Generating output...")
        if args.json:
            output = format_json_output(
                filter_data, project_results, args.permission_key
            )
            with open(args.json_file, "w") as f:
                json.dump(output, f, indent=2)
            print(f"Results exported to {args.json_file}")
        else:
            output_text = format_text_output(
                filter_data, project_results, args.permission_key
            )
            print(output_text)
        logger.info("Complete")

    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
    except requests.RequestException as e:
        logger.error(f"HTTP error: {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.debug(f"Status code: {e.response.status_code}")
            logger.debug(f"Response: {e.response.text[:500]}")
        sys.exit(1)
    except JSONDecodeError as e:
        logger.error(f"JSON parsing error: {e}")
        logger.info(
            "This usually means the server returned HTML or plain text instead of JSON."
        )
        logger.info("Check that the Jira URL and API version are correct.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
