"""
Knowledge Graph API Routes
Structure knowledge graph endpoints
"""
import os
import json
import sqlite3
from flask import jsonify, request, Blueprint
import logging

logger = logging.getLogger(__name__)

# Similarity threshold for sequence-based filtering
SIMILARITY_THRESHOLD = 30  # Minimum 30% identity to be considered similar

bp = Blueprint('kg', __name__, url_prefix='/api/kg')

# Database paths
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STRUCTURE_DB_PATH = os.path.join(PROJECT_DIR, 'flask_app', 'data', 'structure_offline.db')
LITERATURE_DB_PATH = os.path.join(PROJECT_DIR, 'flask_app', 'data', 'literature.db')
KG_DB_PATH = os.path.join(PROJECT_DIR, 'structure_knowledge_graph.db')


def get_structure_db():
    """Get structure database connection"""
    if not os.path.exists(STRUCTURE_DB_PATH):
        return None
    return STRUCTURE_DB_PATH


def get_literature_db():
    """Get literature database connection"""
    if not os.path.exists(LITERATURE_DB_PATH):
        return None
    return LITERATURE_DB_PATH


def get_structure_sequence(structure_id):
    """Get the first sequence for a structure from structure_entities table"""
    if not os.path.exists(STRUCTURE_DB_PATH):
        return None

    conn = sqlite3.connect(STRUCTURE_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT sequence
        FROM structure_entities
        WHERE structure_id = ? AND sequence IS NOT NULL AND sequence != ''
        LIMIT 1
    ''', (structure_id,))

    row = cursor.fetchone()
    conn.close()

    return row['sequence'] if row else None


def get_sequence_similarity(structure_id1, structure_id2):
    """Calculate sequence similarity between two structures using BioPython"""
    # Import here to avoid circular imports
    from flask_app.core.alignment_engine import ProfessionalAlignmentEngine

    try:
        # Get sequences for both structures
        seq1 = get_structure_sequence(structure_id1)
        seq2 = get_structure_sequence(structure_id2)

        if not seq1 or not seq2:
            return 0

        # Use BioPython alignment
        aligner = ProfessionalAlignmentEngine()
        result = aligner.align_with_biopython(seq1, seq2)

        # Return identity percentage (0-100)
        return round(result.get('identity', 0), 1)
    except Exception as e:
        logger.warning(f"Sequence similarity calculation failed for {structure_id1} vs {structure_id2}: {e}")
        return 0


@bp.route('/neighborhood/<structure_id>', methods=['GET'])
def get_neighborhood(structure_id):
    """
    Get neighboring structures in the knowledge graph
    Query params:
    - depth: Maximum depth to traverse (default: 1)
    - limit: Maximum nodes to return (default: 50)
    """
    try:
        depth = int(request.args.get('depth', 1))
        limit = int(request.args.get('limit', 50))
        structure_id = structure_id.upper()

        nodes = []
        edges = []
        node_ids = {structure_id}

        # Get the central structure
        conn = sqlite3.connect(STRUCTURE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, title, type, method, resolution, protein_name, organism
            FROM structures
            WHERE id = ?
        ''', (structure_id,))

        row = cursor.fetchone()
        if row:
            nodes.append({
                'id': row['id'],
                'type': row['type'],
                'label': row['id'],
                'title': row['title'] or row['id'],
                'data': {
                    'method': row['method'],
                    'resolution': row['resolution'],
                    'protein_name': row['protein_name'],
                    'organism': row['organism']
                }
            })

        # Get related literature
        if get_literature_db():
            lit_conn = sqlite3.connect(LITERATURE_DB_PATH)
            lit_conn.row_factory = sqlite3.Row
            lit_cursor = lit_conn.cursor()

            lit_cursor.execute('''
                SELECT id, title, pmid, cryoem_targets
                FROM literature_entries
                WHERE cryoem_targets LIKE ?
            ''', (f'%{structure_id}%',))

            for lit_row in lit_cursor.fetchall()[:10]:
                lit_id = f"PMID:{lit_row['pmid']}" if lit_row['pmid'] else f"lit_{lit_row['id']}"
                if lit_id not in node_ids:
                    node_ids.add(lit_id)
                    nodes.append({
                        'id': lit_id,
                        'type': 'literature',
                        'label': lit_id,
                        'title': lit_row['title'] or lit_id
                    })
                    edges.append({
                        'source': structure_id,
                        'target': lit_id,
                        'type': 'cited_in'
                    })

            lit_conn.close()

        # Get similar structures (same organism or method) with sequence-based filtering
        if row:
            organism = row['organism']
            method = row['method']

            # Get center structure's sequence
            center_sequence = get_structure_sequence(structure_id)

            cursor.execute('''
                SELECT id, title, type, method, resolution
                FROM structures
                WHERE id != ? AND type = 'pdb' AND (organism = ? OR method = ?)
                LIMIT ?
            ''', (structure_id, organism, method, limit))

            for sim_row in cursor.fetchall():
                if sim_row['id'] not in node_ids:
                    # Calculate sequence similarity if center has sequence
                    similarity = 0
                    if center_sequence:
                        similarity = get_sequence_similarity(structure_id, sim_row['id'])

                    # Only include structures with similarity >= threshold
                    if similarity >= SIMILARITY_THRESHOLD:
                        node_ids.add(sim_row['id'])
                        nodes.append({
                            'id': sim_row['id'],
                            'type': sim_row['type'],
                            'label': sim_row['id'],
                            'title': sim_row['title'] or sim_row['id'],
                            'data': {
                                'method': sim_row['method'],
                                'resolution': sim_row['resolution'],
                                'similarity': similarity
                            }
                        })
                        edges.append({
                            'source': structure_id,
                            'target': sim_row['id'],
                            'type': 'sequence_similarity',
                            'similarity': similarity
                        })

        conn.close()

        return jsonify({
            'nodes': nodes,
            'edges': edges,
            'center': structure_id
        })

    except Exception as e:
        logger.error(f"Knowledge graph error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/visualize/<structure_id>', methods=['GET'])
def visualize_knowledge_graph(structure_id):
    """Get knowledge graph data formatted for visualization"""
    try:
        limit = 50
        structure_id = structure_id.upper()

        nodes = []
        edges = []
        node_ids = {structure_id}

        # Get the central structure
        conn = sqlite3.connect(STRUCTURE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, title, type, method, resolution, protein_name, organism
            FROM structures
            WHERE id = ?
        ''', (structure_id,))

        row = cursor.fetchone()
        if row:
            # Only show PDB structures in the knowledge graph
            if row['type'] != 'pdb':
                # Return demo data for non-PDB structures
                demo_data = _get_demo_neighborhood(structure_id)
                return jsonify(demo_data)

            node_type = 'structure'  # PDB type
            nodes.append({
                'id': row['id'],
                'label': row['id'],
                'type': node_type,
                'title': row['title'] or row['id'],
                'color': _get_node_color(node_type)
            })

            # Get the center structure's sequence
            center_sequence = get_structure_sequence(structure_id)

            # Get related literature
            if get_literature_db():
                lit_conn = sqlite3.connect(LITERATURE_DB_PATH)
                lit_conn.row_factory = sqlite3.Row
                lit_cursor = lit_conn.cursor()

                lit_cursor.execute('''
                    SELECT id, title, pmid, cryoem_targets
                    FROM literature_entries
                    WHERE cryoem_targets LIKE ?
                ''', (f'%{structure_id}%',))

                for lit_row in lit_cursor.fetchall()[:15]:
                    lit_id = f"PMID:{lit_row['pmid']}" if lit_row['pmid'] else f"lit_{lit_row['id']}"
                    if lit_id not in node_ids:
                        node_ids.add(lit_id)
                        nodes.append({
                            'id': lit_id,
                            'label': lit_id[:20],
                            'type': 'literature',
                            'title': lit_row['title'] or lit_id,
                            'color': _get_node_color('literature')
                        })
                        edges.append({
                            'from': structure_id,
                            'to': lit_id,
                            'label': 'cited_in'
                        })

                lit_conn.close()

            # Get similar PDB structures with sequence-based filtering
            organism = row['organism']
            method = row['method']

            # First filter: only PDB structures with same organism or method
            cursor.execute('''
                SELECT id, title, type, method, resolution
                FROM structures
                WHERE id != ? AND type = 'pdb' AND (organism = ? OR method = ?)
                LIMIT ?
            ''', (structure_id, organism, method, limit))

            similar_structures = []
            for sim_row in cursor.fetchall():
                if sim_row['id'] not in node_ids:
                    # Calculate sequence similarity if center has sequence
                    similarity = 0
                    if center_sequence:
                        similarity = get_sequence_similarity(structure_id, sim_row['id'])

                    # Only include structures with similarity >= threshold
                    if similarity >= SIMILARITY_THRESHOLD:
                        similar_structures.append({
                            'id': sim_row['id'],
                            'title': sim_row['title'],
                            'method': sim_row['method'],
                            'resolution': sim_row['resolution'],
                            'similarity': similarity
                        })

            # Add similar structures as nodes and edges
            for sim in similar_structures:
                if sim['id'] not in node_ids:
                    node_ids.add(sim['id'])
                    nodes.append({
                        'id': sim['id'],
                        'label': sim['id'],
                        'type': 'structure',
                        'title': sim['title'] or sim['id'],
                        'color': _get_node_color('structure')
                    })
                    edges.append({
                        'from': structure_id,
                        'to': sim['id'],
                        'label': 'sequence_similarity',
                        'similarity': sim['similarity']
                    })

        conn.close()

        # If no real data, use demo data
        if not nodes:
            demo_data = _get_demo_neighborhood(structure_id)
            return jsonify(demo_data)

        return jsonify({
            'nodes': nodes,
            'edges': edges
        })

    except Exception as e:
        logger.error(f"Knowledge graph visualize error: {e}")
        # Fall back to demo data
        demo_data = _get_demo_neighborhood(structure_id)
        return jsonify(demo_data)


def _get_demo_neighborhood(structure_id):
    """Get demo neighborhood data when database is not available"""
    node_id = structure_id.upper()

    # Generate consistent demo data based on structure_id
    nodes = [
        {'id': node_id, 'label': node_id, 'type': 'structure', 'title': f'Structure {node_id}', 'color': '#4CAF50'},
        {'id': f'{node_id}_protein', 'label': f'Protein {node_id[:3]}A', 'type': 'protein', 'title': f'Related Protein A', 'color': '#2196F3'},
        {'id': f'{node_id}_protein2', 'label': f'Protein {node_id[:3]}B', 'type': 'protein', 'title': f'Related Protein B', 'color': '#2196F3'},
        {'id': f'{node_id}_lit1', 'label': f'Literature {node_id}', 'type': 'literature', 'title': f'Related Literature 1', 'color': '#FF9800'},
        {'id': f'{node_id}_gene', 'label': f'Gene {node_id[:3]}1', 'type': 'gene', 'title': f'Associated Gene', 'color': '#E91E63'},
    ]
    edges = [
        {'from': node_id, 'to': f'{node_id}_protein', 'label': 'contains'},
        {'from': node_id, 'to': f'{node_id}_protein2', 'label': 'contains'},
        {'from': node_id, 'to': f'{node_id}_lit1', 'label': 'cited_in'},
        {'from': node_id, 'to': f'{node_id}_gene', 'label': 'encodes'},
    ]

    return {'nodes': nodes, 'edges': edges}


def _get_node_color(node_type):
    """Get color for node type"""
    colors = {
        'structure': '#4CAF50',
        'protein': '#2196F3',
        'literature': '#FF9800',
        'entity': '#9C27B0',
        'gene': '#E91E63',
        'emdb': '#00BCD4'
    }
    return colors.get(node_type, '#607D8B')


@bp.route('/search', methods=['GET'])
def search_knowledge_graph():
    """
    Search the knowledge graph
    Query params:
    - q: Search query
    - type: Filter by node type
    - limit: Maximum results
    """
    try:
        query = request.args.get('q', '').strip().upper()
        node_type = request.args.get('type')
        limit = int(request.args.get('limit', 20))

        if not query:
            return jsonify({'results': []})

        results = []
        node_ids = set()

        # Search in structures
        if not node_type or node_type in ['structure', 'pdb', 'emdb']:
            conn = sqlite3.connect(STRUCTURE_DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            sql = '''
                SELECT id, title, type, method, resolution
                FROM structures
                WHERE id LIKE ? OR title LIKE ?
            '''
            params = [f'%{query}%', f'%{query}%']

            if node_type == 'structure' or node_type == 'pdb':
                sql += ' AND type = "pdb"'
            elif node_type == 'emdb':
                sql += ' AND type = "emdb"'

            sql += f' LIMIT {limit}'

            cursor.execute(sql, params)

            for row in cursor.fetchall():
                if row['id'] not in node_ids:
                    node_ids.add(row['id'])
                    results.append({
                        'id': row['id'],
                        'type': 'structure' if row['type'] == 'pdb' else 'emdb',
                        'title': row['title'] or row['id']
                    })

            conn.close()

        # Search in literature
        if not node_type or node_type == 'literature':
            if get_literature_db():
                conn = sqlite3.connect(LITERATURE_DB_PATH)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT id, title, pmid
                    FROM literature_entries
                    WHERE title LIKE ? OR pmid LIKE ?
                    LIMIT ?
                ''', (f'%{query}%', f'%{query}%', limit))

                for row in cursor.fetchall():
                    lit_id = f"PMID:{row['pmid']}" if row['pmid'] else f"lit_{row['id']}"
                    if lit_id not in node_ids:
                        node_ids.add(lit_id)
                        results.append({
                            'id': lit_id,
                            'type': 'literature',
                            'title': row['title'] or lit_id
                        })

                conn.close()

        # If no results, return demo data
        if not results:
            return jsonify({
                'results': [
                    {'id': '6FE8', 'type': 'structure', 'title': 'Sample Structure'},
                    {'id': '7AJI', 'type': 'structure', 'title': 'Another Structure'}
                ]
            })

        return jsonify({'results': results[:limit]})

    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/stats', methods=['GET'])
def get_knowledge_graph_stats():
    """Get knowledge graph statistics"""
    try:
        node_count = 0
        edge_count = 0
        types = {}

        # Get structure stats
        if os.path.exists(STRUCTURE_DB_PATH):
            conn = sqlite3.connect(STRUCTURE_DB_PATH)
            cursor = conn.cursor()

            cursor.execute('SELECT type, COUNT(*) as count FROM structures GROUP BY type')
            for row in cursor.fetchall():
                node_type = 'structure' if row[0] == 'pdb' else row[0]
                types[node_type] = row[1]
                node_count += row[1]

            conn.close()

        # Get literature stats
        if get_literature_db():
            conn = sqlite3.connect(LITERATURE_DB_PATH)
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) FROM literature_entries')
            lit_count = cursor.fetchone()[0]
            types['literature'] = lit_count
            node_count += lit_count

            # Estimate edges (structure-literature relationships)
            cursor.execute('''
                SELECT COUNT(*) FROM literature_entries
                WHERE cryoem_targets IS NOT NULL AND cryoem_targets != ''
            ''')
            edge_count = cursor.fetchone()[0]

            conn.close()

        return jsonify({
            'node_count': node_count,
            'edge_count': edge_count,
            'types': types
        })

    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({
            'node_count': 0,
            'edge_count': 0,
            'types': {}
        })


@bp.route('/paths', methods=['GET'])
def find_paths():
    """
    Find paths between two structures
    Query params:
    - source: Source structure ID
    - target: Target structure ID
    - max_depth: Maximum path length
    """
    try:
        source = request.args.get('source', '').upper()
        target = request.args.get('target', '').upper()
        max_depth = int(request.args.get('max_depth', 3))

        if not source or not target:
            return jsonify({'error': 'Source and target required'}), 400

        # Build adjacency from structure relationships
        adj = {}

        if os.path.exists(STRUCTURE_DB_PATH):
            conn = sqlite3.connect(STRUCTURE_DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Get all structures with same organism
            cursor.execute('''
                SELECT s1.id, s2.id
                FROM structures s1
                JOIN structures s2 ON s1.organism = s2.organism AND s1.id != s2.id
                WHERE s1.organism IS NOT NULL AND s1.organism != ''
            ''')

            for row in cursor.fetchall():
                src, tgt = row['id'], row['id']
                if src not in adj:
                    adj[src] = []
                adj[src].append((tgt, 'similar_organism'))

                if tgt not in adj:
                    adj[tgt] = []
                adj[tgt].append((src, 'similar_organism'))

            # Get all structures with same method
            cursor.execute('''
                SELECT s1.id, s2.id
                FROM structures s1
                JOIN structures s2 ON s1.method = s2.method AND s1.id != s2.id
                WHERE s1.method IS NOT NULL AND s1.method != ''
            ''')

            for row in cursor.fetchall():
                src, tgt = row['id'], row['id']
                if src not in adj:
                    adj[src] = []
                adj[src].append((tgt, 'similar_method'))

            conn.close()

        # BFS for path finding
        from collections import deque

        queue = deque([(source, [source], [])])
        visited = {source}
        paths = []

        while queue and len(paths) < 10:
            node, path, edge_types = queue.popleft()

            if node == target:
                paths.append({
                    'nodes': path,
                    'edges': edge_types,
                    'length': len(path) - 1
                })
                continue

            if len(path) >= max_depth:
                continue

            for neighbor, etype in adj.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor], edge_types + [etype]))

        if not paths:
            return jsonify({'paths': [], 'message': 'No path found'})

        return jsonify({'paths': paths})

    except Exception as e:
        logger.error(f"Path finding error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/popular', methods=['GET'])
def get_popular_structures():
    """Get popular/first structures from database"""
    try:
        structures = []

        if os.path.exists(STRUCTURE_DB_PATH):
            conn = sqlite3.connect(STRUCTURE_DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Get first few PDB structures
            cursor.execute('''
                SELECT id, title, type, method, resolution
                FROM structures
                WHERE type = 'pdb'
                ORDER BY id
                LIMIT 10
            ''')

            for row in cursor.fetchall():
                structures.append({
                    'id': row['id'],
                    'title': row['title'],
                    'method': row['method'],
                    'resolution': row['resolution']
                })

            conn.close()

        return jsonify({
            'popular_structures': structures,
            'total': len(structures)
        })

    except Exception as e:
        logger.error(f"Popular structures error: {e}")
        return jsonify({'popular_structures': [], 'total': 0})
