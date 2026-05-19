#!/usr/bin/env bash
# AI Validation Pipeline – Local Launcher (macOS/Linux)
set -e
cd "$(dirname "$0")"

echo ""
echo "  ======================================="
echo "  AI Validation Pipeline - Local Edition"
echo "  ======================================="
echo ""

# Check Python
PYTHON=""
for cmd in python3 python; do
  if command -v $cmd &>/dev/null && $cmd -c "import sys; assert sys.version_info >= (3,10)" 2>/dev/null; then
    PYTHON=$cmd
    echo "  [OK] $($cmd --version)"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "  [ERROR] Python 3.10+ required."; exit 1
fi

# Create venv if needed
VENV="backend/.venv"
if [ ! -f "$VENV/bin/python" ]; then
  echo "  Creating virtual environment..."
  $PYTHON -m venv $VENV
fi

# Install deps
echo "  Installing dependencies..."
$VENV/bin/pip install -q -r backend/requirements.txt

# Check .env
if [ ! -f "backend/.env" ]; then
  echo "  [WARN] .env not found. Copying from .env.example"
  cp backend/.env.example backend/.env
  echo "  Please edit backend/.env with your API keys."
fi

echo ""
echo "  Starting on http://127.0.0.1:8000"
echo "  Press Ctrl+C to stop."
echo ""

cd backend
# Open browser (best-effort)
(sleep 1 && open "http://127.0.0.1:8000" 2>/dev/null || xdg-open "http://127.0.0.1:8000" 2>/dev/null) &
exec $VENV/bin/python main.py
