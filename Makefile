# NT Groundwater Stress Atlas
.DEFAULT_GOAL := help
SHELL := /bin/sh

.PHONY: help install-hooks check-hooks test

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install-hooks: ## Install the git pre-commit data guard
	@mkdir -p .git/hooks
	@cp scripts/hooks/pre-commit .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "installed .git/hooks/pre-commit"

check-hooks: ## Fail if the pre-commit guard is not installed / is stale
	@test -x .git/hooks/pre-commit \
	  || { echo "pre-commit hook not installed - run 'make install-hooks'"; exit 1; }
	@cmp -s scripts/hooks/pre-commit .git/hooks/pre-commit \
	  || { echo "pre-commit hook is stale - run 'make install-hooks'"; exit 1; }
	@echo "pre-commit guard installed and current"

test: ## Run the test suite (phase 1 onward)
	@echo "No test suite yet - phase 1 not started (awaiting plan approval)."
	@echo "Guard check:"
	@$(MAKE) --no-print-directory check-hooks
