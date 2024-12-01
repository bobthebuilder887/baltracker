# Python project related variables
PY := python3.12
PROJECT_NAME := baltracker
PROJECT_DIR := src/balance_tracker
ENV_DIR := .venv
ENV := ./$(ENV_DIR)/bin/$(PY)
PIP := ./$(ENV_DIR)/bin/pip
RUFF := ./$(ENV_DIR)/bin/ruff
ISORT := ./$(ENV_DIR)/bin/isort
LOCAL := ~/Projects/$(PROJECT_NAME)
# Project defined variables
CFG_FILE := config.json
DATA_DIR := .data
REMOTE :=
KEY :=

.PHONY: all install install_dev format clean get_config get_log get_data upload_data update_config update_remote

all: clean install_dev

install:
	${PY} -m venv ${ENV_DIR};
	${PIP} install --upgrade pip;
	${PIP} install  '.[plot]'

install_dev:
	${PY} -m venv ${ENV_DIR};
	${PIP} install --upgrade pip;
	${PIP} install -e '.[all]'

format:
	${RUFF} format ${PROJECT_DIR}/*.py && ${ISORT} ${PROJECT_DIR}/*.py

clean:
	rm -rf ${ENV_DIR}

# REMOTE COMMANDS ----------------------------------------------------------------------
get_config:
	scp -i ${KEY} ${REMOTE}:~/${PROJECT_NAME}/${CFG_FILE} ${LOCAL}/${CFG_FILE}

get_log:
	scp -i ${KEY} ${REMOTE}:~/${PROJECT_NAME}/${PROJECT_NAME}.log ${LOCAL}

get_data:
	scp -i ${KEY} -r ${REMOTE}:~/${PROJECT_NAME}/${DATA_DIR} ${LOCAL}

upload_data:
	scp -i ${KEY} -r .data ${REMOTE}:~/${PROJECT_NAME}

update_config:
	scp -i ${KEY} ${CFG_FILE} ${REMOTE}:~/${PROJECT_NAME}/${CFG_FILE}

update_remote:
	ssh -i ${KEY} ${REMOTE} "cd ~/${PROJECT_NAME} && git pull && systemctl --user restart ${PROJECT_NAME}.service"
