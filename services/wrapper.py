"""
Service Wrapper Classes
Encapsulates existing backend modules for Flask API consumption
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.literature_db import (
    search_literature,
    get_literature_entry,
    delete_literature_entry,
    update_literature_entry,
    get_literature_stats
)
from core.literature_agent import LiteratureManager, intelligent_qa_search
from core.agent_core import (
    search_literature_with_ai_context,
    ask_literature_question
)
from core.structure_database import StructureOfflineDatabase, get_enhanced_structure_manager
from core.alignment_engine import ProfessionalAlignmentEngine
from core.literature_parser import LiteratureParserManager


class LiteratureService:
    """Literature management service wrapper"""

    @staticmethod
    def search(query, page=1, per_page=20, filters=None):
        """Search literature with pagination"""
        filters = filters or {}
        result = search_literature(
            query=query,
            author=filters.get('author', ''),
            journal=filters.get('journal', ''),
            year_from=filters.get('year_from'),
            year_to=filters.get('year_to'),
            status=filters.get('status'),
            has_cryoem_targets=filters.get('has_cryoem'),
            has_vector_embeddings=filters.get('has_embeddings'),
            tags=filters.get('tags'),
            limit=per_page * page
        )
        start = (page - 1) * per_page
        return result[start:start + per_page]

    @staticmethod
    def get_detail(lit_id):
        """Get literature entry detail"""
        entry = get_literature_entry(lit_id)
        if entry and hasattr(entry, 'to_dict'):
            return entry.to_dict()
        return entry

    @staticmethod
    def delete(lit_id):
        """Delete a literature entry"""
        return delete_literature_entry(lit_id)

    @staticmethod
    def update(lit_id, updates):
        """Update a literature entry"""
        return update_literature_entry(lit_id, updates)

    @staticmethod
    def get_stats():
        """Get literature statistics"""
        return get_literature_stats()


class QAService:
    """Question Answering service wrapper"""

    @staticmethod
    def ask(question, literature_id=None, conversation_context=None):
        """Ask a question about literature"""
        context = None
        if literature_id:
            entry = get_literature_entry(literature_id)
            if entry:
                context = [entry]

        result = ask_literature_question(
            query=question,
            conversation_context=conversation_context or [],
            literature_context=context,
            use_rag=True
        )
        return {
            'answer': result.get('answer', ''),
            'sources': result.get('relevant_entries', []),
            'model': result.get('model', 'unknown'),
            'tokens_used': result.get('tokens_used', 0)
        }

    @staticmethod
    def ai_search(question, top_k=5):
        """AI-enhanced literature search"""
        result = search_literature_with_ai_context(
            query=question,
            top_k=top_k
        )
        return {
            'answer': result.get('answer', ''),
            'literature': result.get('literature', []),
            'structures': result.get('structures', [])
        }


class StructureService:
    """Structure information service wrapper"""

    @staticmethod
    def get_detail(structure_id):
        """Get structure detail"""
        db = StructureOfflineDatabase()
        structure = db.get_structure(structure_id)
        if structure:
            return {
                'id': structure.id,
                'type': str(structure.type),
                'title': structure.title,
                'resolution': structure.resolution,
                'method': structure.method,
                'organism': structure.organism,
                'authors': structure.authors,
                'citation_count': structure.citation_count
            }
        return None

    @staticmethod
    def get_by_literature(lit_id):
        """Get structures associated with literature"""
        manager = get_enhanced_structure_manager()
        structures = manager.get_structures_for_literature(lit_id)
        return structures

    @staticmethod
    def search(query, limit=20):
        """Search structures by protein name"""
        db = StructureOfflineDatabase()
        results = db.find_structures_by_protein_name(query, limit=limit)
        return [
            {
                'id': s.id,
                'type': str(s.type),
                'title': s.title,
                'resolution': s.resolution,
                'method': s.method
            }
            for s in results
        ]


class AlignmentService:
    """Sequence alignment service wrapper"""

    @staticmethod
    def align(sequence1, sequence2, alignment_type='global'):
        """Run sequence alignment"""
        engine = ProfessionalAlignmentEngine()
        result = engine.align_with_biopython(sequence1, sequence2, alignment_type)
        return result
