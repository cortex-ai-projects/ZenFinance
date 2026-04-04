#!/bin/bash
# ZenFinance — One-click launcher
# Usage: bash run.sh

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  💰  ZenFinance — Personal Finance Audit"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Resolve Python & pip ──────────────────────────
if command -v python3 &> /dev/null; then
  PYTHON=python3
elif command -v python &> /dev/null; then
  PYTHON=python
else
  echo "❌  Python 3 not found. Install from https://www.python.org/downloads/"
  exit 1
fi

# Prefer pip3, fall back to pip, fall back to python -m pip
if command -v pip3 &> /dev/null; then
  PIP=pip3
elif command -v pip &> /dev/null; then
  PIP=pip
else
  PIP="$PYTHON -m pip"
fi

echo "🐍  Using: $($PYTHON --version)  |  pip: $PIP"

# ── Install / upgrade dependencies ───────────────
echo "📦  Installing dependencies…"
$PIP install -q --upgrade \
  streamlit \
  pandas \
  plotly \
  openpyxl \
  xlrd \
  pymupdf \
  "thefuzz[speedup]"

# Create required dirs
mkdir -p data backups

# ── Launch ────────────────────────────────────────
echo ""
echo "🚀  Starting ZenFinance → http://localhost:8501"
echo "    Press Ctrl+C to stop."
echo ""

$PYTHON -m streamlit run app.py \
  --server.headless true \
  --server.port 8501 \
  --theme.base dark
