# =============================================================================
# Balance Tracker Project Makefile
# Handles project setup, development, and remote deployment tasks
# =============================================================================

# Python environment configuration
PY := python3.12
ENV_DIR := .venv
ENV := ./$(ENV_DIR)/bin/$(PY)
PIP := ./$(ENV_DIR)/bin/pip

# Project structure
PROJECT_NAME := baltracker
PROJECT_DIR := src/balance_tracker
LOCAL := ~/Projects/$(PROJECT_NAME)

# Development tools
RUFF := ./$(ENV_DIR)/bin/ruff
ISORT := ./$(ENV_DIR)/bin/isort

# Project configuration
CFG_FILE := config.json
DATA_DIR := .data
REMOTE :=
KEY :=

# Make sure these targets work even if files with the same names exist
.PHONY: all install install_dev format clean help \
        get_config get_log get_data upload_data update_config update_remote

# Default target shows help
.DEFAULT_GOAL := help

# Development Environment Setup -----------------------------------------------------
all: clean install_dev  ## Clean and set up development environment (default)

install:  ## Install production dependencies only
	${PY} -m venv ${ENV_DIR}
	${PIP} install --upgrade pip
	${PIP} install '.[plot]'

install_dev:  ## Install development dependencies and tools
	${PY} -m venv ${ENV_DIR}
	${PIP} install --upgrade pip
	${PIP} install -e '.[all]'

format:  ## Format code using ruff and isort
	${RUFF} format ${PROJECT_DIR}/*.py && ${ISORT} ${PROJECT_DIR}/*.py

clean:  ## Remove virtual environment and cached files
	rm -rf ${ENV_DIR}
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Remote Management Commands ------------------------------------------------------
get_config:  ## Download configuration file from remote server
	@if [ -z "${REMOTE}" ]; then echo "Error: REMOTE not set"; exit 1; fi
	@if [ -z "${KEY}" ]; then echo "Error: KEY not set"; exit 1; fi
	scp -i ${KEY} ${REMOTE}:~/${PROJECT_NAME}/${CFG_FILE} ${LOCAL}/${CFG_FILE}

get_log:  ## Download log file from remote server
	@if [ -z "${REMOTE}" ]; then echo "Error: REMOTE not set"; exit 1; fi
	@if [ -z "${KEY}" ]; then echo "Error: KEY not set"; exit 1; fi
	scp -i ${KEY} ${REMOTE}:~/${PROJECT_NAME}/${PROJECT_NAME}.log ${LOCAL}

get_data:  ## Download data directory from remote server
	@if [ -z "${REMOTE}" ]; then echo "Error: REMOTE not set"; exit 1; fi
	@if [ -z "${KEY}" ]; then echo "Error: KEY not set"; exit 1; fi
	scp -i ${KEY} -r ${REMOTE}:~/${PROJECT_NAME}/${DATA_DIR} ${LOCAL}

upload_data:  ## Upload local data directory to remote server
	@if [ -z "${REMOTE}" ]; then echo "Error: REMOTE not set"; exit 1; fi
	@if [ -z "${KEY}" ]; then echo "Error: KEY not set"; exit 1; fi
	scp -i ${KEY} -r .data ${REMOTE}:~/${PROJECT_NAME}

update_config:  ## Upload configuration file to remote server
	@if [ -z "${REMOTE}" ]; then echo "Error: REMOTE not set"; exit 1; fi
	@if [ -z "${KEY}" ]; then echo "Error: KEY not set"; exit 1; fi
	scp -i ${KEY} ${CFG_FILE} ${REMOTE}:~/${PROJECT_NAME}/${CFG_FILE}

update_remote:  ## Update remote repository and restart service
	@if [ -z "${REMOTE}" ]; then echo "Error: REMOTE not set"; exit 1; fi
	@if [ -z "${KEY}" ]; then echo "Error: KEY not set"; exit 1; fi
	ssh -i ${KEY} ${REMOTE} "cd ~/${PROJECT_NAME} && git pull && systemctl --user restart ${PROJECT_NAME}.service"

# Help Target -------------------------------------------------------------------
help:  ## Display this help message
	@echo "Balance Tracker Makefile Commands:"
	@echo
	@echo "Usage: make [target] [REMOTE=user@host] [KEY=path/to/key]"
	@echo
	@echo "Available targets:"
	@awk -F '##' '/^[a-zA-Z_-]+:.*?##/ { printf "  %-15s %s\n", $$1, $$2 }' $(MAKEFILE_LIST) | sort
	@echo
	@echo "Remote operations require REMOTE and KEY variables to be set:"
	@echo "  REMOTE: SSH connection string (e.g., user@hostname)"
	@echo "  KEY: Path to SSH private key"
