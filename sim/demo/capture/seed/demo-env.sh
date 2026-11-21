# Source-free wrapper: run a command with a clean env and the demo's own Claude config.
exec env -i HOME=/root PATH=/usr/local/bin:/usr/bin:/bin TERM=xterm-256color LANG=C.UTF-8 \
  TMPDIR=/var/tmp/claude-agent CLAUDE_CONFIG_DIR=/root/demo-claude \
  UV_CACHE_DIR=/cache/uv UV_PYTHON_INSTALL_DIR=/usr/libexec/claude-sandbox/python UV_PYTHON=3.13 UV_LINK_MODE=copy \
  /root/.local/bin/claude "$@"
