"""Run frago's own CLI as ``python -m frago``.

The console script on PATH and this entry point reach the same command tree.
The difference is which frago answers: the script on PATH is whatever the
machine installed, while ``-m`` under a given interpreter is the frago that
interpreter imports.

That distinction is the reason this file exists. The hub runs frago commands on
behalf of confined recipes, and it has to be the *same* frago that is serving
the request — a server on one version shelling out to a differently-versioned
script on PATH would enforce one set of rules and execute another, and nothing
would say so. Starting it with the server's own interpreter makes that
impossible rather than unlikely.
"""

from frago.cli.main import cli

if __name__ == "__main__":
    cli()
