.PHONY: usage lint

usage:
	@python3 jira_filter_permissions.py --export-usage | tee usage.md

lint:
	@pre-commit run --all-files
