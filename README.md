# CryoAgent Pro - Flask Frontend

This is the Flask-based frontend for CryoAgent Pro, migrated from the original Streamlit application.

## Project Structure

```
flask_app/
├── app.py                    # Flask application entry point
├── config.py                 # Configuration settings
├── requirements.txt          # Python dependencies
├── run.sh                    # Startup script
├── routes/                   # API route modules
│   ├── __init__.py
│   ├── literature.py        # Literature CRUD operations
│   ├── structure.py         # Structure information
│   ├── qa.py               # Q&A system
│   ├── upload.py           # File upload handling
│   ├── search.py           # Search endpoints
│   └── utils.py            # Utility endpoints
├── services/                 # Service layer
│   ├── __init__.py
│   └── wrapper.py          # Backend module wrappers
├── templates/                # Jinja2 HTML templates
│   ├── base.html            # Base template
│   ├── index.html           # Main dashboard
│   ├── literature.html      # Literature list
│   ├── literature_detail.html # Detail view
│   ├── qa.html             # Q&A interface
│   ├── structures.html      # Structure browser
│   ├── error.html          # Error page
│   ├── api_docs.html       # API documentation
│   └── components/          # Reusable components
├── static/                  # Static resources
│   ├── css/                # Stylesheets
│   │   ├── main.css
│   │   ├── components.css
│   │   └── chat.css
│   └── js/                 # JavaScript
│       ├── utils.js
│       ├── app.js
│       ├── literature.js
│       ├── literature_detail.js
│       ├── qa.js
│       └── structures.js
└── uploads/                # Upload directory
```

## Installation

```bash
cd flask_app
pip install flask flask-cors
```

## Running

### Development

```bash
python app.py
# Access at http://localhost:5000
```

### Using run script

```bash
./run.sh
```

## Features

- **Literature Management**: Browse, search, upload, and manage Cryo-EM literature
- **Structure Browser**: View and search protein structures (PDB, EMDB, AlphaFold)
- **Intelligent Q&A**: AI-powered question answering about Cryo-EM research
- **Sequence Alignment**: Built-in sequence alignment tool
- **Card-based UI**: Clickable cards for literature and structures
- **Tab Navigation**: Easy switching between views

## API Endpoints

### Literature
- `GET /api/literature` - List literature with pagination/filtering
- `GET /api/literature/<id>` - Get literature details
- `DELETE /api/literature/<id>` - Delete literature
- `POST /api/literature/<id>/reparse` - Reparse literature

### Structure
- `GET /api/structure/<id>` - Get structure details
- `GET /api/structure/literature/<lit_id>` - Get structures by literature
- `POST /api/structure/search` - Search structures

### Q&A
- `POST /api/qa/ask` - Ask a question
- `POST /api/qa/ai-search` - AI-enhanced search

### Upload
- `POST /api/upload` - Upload PDF files

### Utilities
- `GET /api/stats` - Get statistics
- `POST /api/alignment` - Run sequence alignment
- `GET /api/health` - Health check

## Integration with Backend

The Flask frontend reuses all existing backend modules from the parent application:
- `literature_db.py` - Database operations
- `literature_agent.py` - Agent logic
- `structure_database.py` - Structure data
- `agent_core.py` - AI operations
- `literature_parser.py` - PDF parsing

## Notes

- Ensure the parent directory has the required `.env` file with API keys
- The application reads from existing databases (`literature.db`, etc.)
- Uploaded files are stored in the `uploads/` directory
