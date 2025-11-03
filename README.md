# python-cdpctl

`python-cdpctl` provides a batteries-included command-line interface and a small
Python helper library for interacting with the [Chrome DevTools Protocol
(CDP)](https://chromedevtools.github.io/devtools-protocol/). The tool makes it
easy to inspect targets, automate navigation, and collect artifacts such as
screenshots or PDF printouts without leaving the terminal.

## Features

* **Zero-setup CLI** – run `cdpctl list-tabs` or `python -m cdpctl list-tabs`
  after launching Chrome with remote debugging enabled to discover available
  targets.
* **Tab lifecycle management** – create, activate, and close tabs via
  HTTP helper APIs.
* **Navigation helpers** – instruct pages to navigate to a URL and optionally
  wait for DOM readiness, load events, or network idleness.
* **Data extraction** – retrieve DOM text, HTML snapshots, and evaluate
  arbitrary JavaScript expressions.
* **Artifact capture** – grab screenshots (including full-page) and generate
  PDF printouts directly from the command line.
* **Live logging** – stream console messages or network activity for a target
  to aid debugging and monitoring workflows.

## Installation

Install the package from a clone of this repository:

```bash
pip install git+https://github.com/grantjenks/python-cdpctl.git
```

Alternatively, install the project in editable mode while working on
contributions:

```bash
git clone https://github.com/grantjenks/python-cdpctl.git
cd python-cdpctl
pip install -e .[dev]
```

## Python compatibility

`python-cdpctl` targets CPython 3.10 and newer. The asynchronous implementation
relies on `asyncio` and `aiohttp`, both of which are available on the supported
interpreters.

## Quick start

1. Launch Chrome or Chromium with a remote debugging port. On macOS this might
   look like:

   ```bash
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
       --remote-debugging-port=9222 --user-data-dir=/tmp/cdpctl
   ```

2. Explore available commands:

   ```bash
   cdpctl list-tabs
   cdpctl browser-info
   cdpctl new-tab https://example.com --json
   cdpctl navigate <target_id> https://news.ycombinator.com --wait load
   cdpctl screenshot <target_id> --full --out page.png
   cdpctl console-log <target_id> --duration 15
   ```

   Replace `<target_id>` with an identifier returned from `list-tabs`.

## Testing

Run the unit tests locally before sending changes:

```bash
pytest
# or use the automation profile
nox -s tests
```

## Contributing

Issues and pull requests are always welcome. When proposing changes, include
tests where practical and ensure the existing suite continues to pass. If a bug
is too complex for Codex to handle, file an issue describing the problem and the
expected behaviour.
