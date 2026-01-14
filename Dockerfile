# frago Docker Image
# AI-driven multi-runtime automation framework with Chrome CDP support
#
# Build:
#   docker build -t frago .
#
# Run examples:
#   docker run --rm frago --help
#   docker run --rm frago chrome start --headless
#   docker run --rm -v ~/.frago:/home/frago/.frago frago recipe list

FROM python:3.13-slim-bookworm

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install Chrome and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Chrome dependencies
    wget gnupg ca-certificates \
    # Fonts (including CJK for Chinese/Japanese/Korean)
    fonts-liberation fonts-noto-cjk \
    # Runtime dependencies for Chrome
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libpangocairo-1.0-0 libgtk-3-0 \
    # Utilities
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install uv and frago as root (has write permission to /usr/local)
RUN pip install uv \
    && uv pip install --system frago-cli

# Create non-root user
RUN useradd -m -s /bin/bash frago \
    && mkdir -p /home/frago/.frago \
    && chown -R frago:frago /home/frago

# Switch to non-root user
USER frago
WORKDIR /home/frago

# Default headless mode for Docker environment
ENV FRAGO_NO_SANDBOX=1

ENTRYPOINT ["frago"]
CMD ["--help"]
