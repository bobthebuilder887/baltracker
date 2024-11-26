# Balance Tracker

Tools for tracking crypto wallet balances

## Requirements

- Python3.12
- Telegram Bot API key.
- Moralis API keys

## Install

Uses python's built-in virtual environment

### Basic

```{bash}
make install
```

### Dev

```{bash}
make install_dev
```

## Usage

Before running the tracker, set up the `config.json` file. Use `config.json.example` as a template.

### Tracker

Track balance (see `track --help` for cli args)

```{bash}
source ./.venv/bin/activate && track
```

### Plot

Plot balance (see `plot --help` for cli args)

```{bash}
source ./.venv/bin/activate && plot
```

### Remote setup

Set up on a remote ubuntu machine as non-root (make sure to have a configuration file ready in home directory):

```{bash}
cd ~ && git clone https://github.com/bobthebuilder887/baltracker && cd baltracker && cp ../config.json . && bash sys/install.sh
```
