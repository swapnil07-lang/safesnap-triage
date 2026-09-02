import sys
from pathlib import Path

# Ensure the backend root directory is in sys.path so main can be imported
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Expose the FastAPI app instance for Vercel Serverless Functions
from main import app
