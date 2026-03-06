#!/bin/bash
# CryoAgent Pro - Flask Application Runner

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check for virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Install dependencies if needed
if ! python -c "import flask" 2>/dev/null; then
    echo "Installing Flask dependencies..."
    pip install flask flask-cors gunicorn
fi

# Set Python path
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Run Flask app
echo "Starting CryoAgent Pro Flask Application..."
echo "============================================"
echo "Server running at: http://localhost:5000"
echo "API docs at: http://localhost:5000/api"
echo ""
echo "Press Ctrl+C to stop"
echo "============================================"

python app.py
