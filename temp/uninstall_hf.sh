#!/usr/bin/env bash
# Remove all HuggingFace / torch / transformers packages from the venv.
# These are leftovers from the local-embedding attempt and cause the
# "Accessing __path__ from .models.<xyz>.image_processing_*" warning spam.
# Embeddings are now back on Gemini; none of these are needed.

set -e

cd "$(dirname "$0")/.."

if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
elif [ -f venv/bin/activate ]; then
  source venv/bin/activate
fi

pip uninstall -y \
  langchain-huggingface \
  sentence-transformers \
  transformers \
  torch \
  torchvision \
  tokenizers \
  safetensors \
  huggingface-hub \
  accelerate || true

echo
echo "Verifying removal:"
pip list | grep -iE "torch|transform|huggingface|sentence" || echo "  (clean — nothing left)"

echo
echo "Next:"
echo "  pkill -f 'streamlit run streamlit_app'; pkill -f 'mcp_server.py'"
echo "  streamlit run streamlit_app.py"
