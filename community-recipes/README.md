# frago Community Recipes

This directory contains community-contributed recipes for frago.

## Using Community Recipes

### Install a Recipe

```bash
# Install from community repository
frago recipe install community:<recipe-name>

# Install with force overwrite
frago recipe install community:<recipe-name> --force
```

### Search for Recipes

```bash
# Search by keyword
frago recipe search <query>

# List all community recipes
frago recipe list --source community
```

### Update Installed Recipes

```bash
# Update a specific recipe
frago recipe update <recipe-name>

# Update all installed recipes
frago recipe update --all
```

### Uninstall a Recipe

```bash
frago recipe uninstall <recipe-name>
```

## Installed Recipe Location

Community recipes are installed to `~/.frago/community-recipes/`.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines on submitting your own recipes.

## License

All recipes in this directory are contributed under the same license as frago.
