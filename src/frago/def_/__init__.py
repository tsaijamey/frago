"""frago def — structured knowledge domain system.

Allows agents to define knowledge domains, save structured documents,
and query them with minimal token overhead.

Storage layout:
    ~/.frago/books/registry.json    Domain registry
    ~/.frago/books/<domain>/*.md    Knowledge documents (YAML frontmatter + content arrays)
"""
