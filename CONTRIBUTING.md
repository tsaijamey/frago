# Contributing to frago

Thank you for your interest in the frago project! We welcome contributions of all kinds.

## How to Contribute

### Reporting Issues

If you find a bug or have a feature suggestion:

1. Check if a related issue already exists
2. Create a new issue with a detailed description
3. Provide reproduction steps and environment information

### Submitting Code

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Create a Pull Request

### Code Standards

- Python code follows PEP 8
- Shell scripts follow ShellCheck guidelines
- Provide clear comments and documentation
- Ensure all tests pass

### Development Environment Setup

```bash
# Clone the repository
git clone https://github.com/tsaijamey/frago.git
cd frago

# Install with uv in development mode
uv pip install -e .

# Or use the dev command to sync resources
frago dev pack
```

### Testing

Before running tests, ensure:

1. Chrome CDP is running on port 9222
2. Screen recording permissions are granted (macOS)
3. All dependencies are properly installed

## Areas Where Help is Needed

- Recipe development and testing
- Documentation improvements
- Bug fixes
- Performance optimization
- Cross-platform compatibility

## Code of Conduct

Please follow these guidelines:

- Use friendly and inclusive language
- Respect differing viewpoints and experiences
- Gracefully accept constructive criticism
- Focus on what is best for the community

## Contact

If you have questions:

- Create an issue on GitHub
- Join project Discussions

Thank you for contributing!
