# Preserve the previously verified ARM64 runtime and pin the server upgrade.
# Build with this directory as context; no repository/auth files are copied.
FROM sha256:dab903a5999b1d3165a70de99147029809fa26d3cb1881b7c7790aac185a4726
USER root
COPY feynman_bounded_read_adapter.mjs /opt/feynman/feynman_bounded_read_adapter.mjs
RUN npm install --global @openai/codex@0.154.0 && test "$(codex --version)" = "codex-cli 0.154.0"
USER 1000:1000
