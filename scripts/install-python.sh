#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_DIR="$SCRIPT_DIR/../python"
VENV_DIR="$PYTHON_DIR/venv"

echo "🔧 Setting up VoiceClaw Python environment..."

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
  echo "✓ Created venv at $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install -r "$PYTHON_DIR/requirements.txt"
echo "✓ Dependencies installed"
echo "🟢 VoiceClaw Python setup complete"
