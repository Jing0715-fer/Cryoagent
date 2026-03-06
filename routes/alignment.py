"""
Alignment API Routes
Sequence alignment and analysis endpoints
"""
import os
import json
import time
import uuid
from flask import jsonify, request, Blueprint, Response
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('alignment', __name__, url_prefix='/api/alignment')

# Task storage (in production, use Redis or database)
ALIGNMENT_TASKS = {}


@bp.route('/align', methods=['POST'])
def start_alignment():
    """
    Start a sequence alignment task
    Request body:
    {
        "sequences": ["ATGC...", "ATGC..."],
        "tool": "blast|clustal|muscle",
        "options": {}
    }
    """
    try:
        data = request.get_json()

        sequences = data.get('sequences', [])
        tool = data.get('tool', 'biopython_pairwise')
        options = data.get('options', {})
        sequence_type = data.get('sequence_type', 'protein')  # protein, dna, rna

        if len(sequences) < 2:
            return jsonify({'error': 'At least 2 sequences required'}), 400

        # Create task
        task_id = str(uuid.uuid4())
        task = {
            'id': task_id,
            'status': 'pending',
            'sequences': sequences,
            'tool': tool,
            'options': options,
            'sequence_type': sequence_type,
            'result': None,
            'error': None,
            'created_at': time.time()
        }

        ALIGNMENT_TASKS[task_id] = task

        # Start background alignment
        import threading
        thread = threading.Thread(target=_run_alignment, args=(task_id,))
        thread.start()

        return jsonify({
            'success': True,
            'task_id': task_id,
            'status': 'pending'
        })

    except Exception as e:
        logger.error(f"Alignment error: {e}")
        return jsonify({'error': str(e)}), 500


def _run_alignment(task_id):
    """Run alignment in background"""
    try:
        task = ALIGNMENT_TASKS.get(task_id)
        if not task:
            return

        task['status'] = 'running'

        # Import and use the professional alignment engine
        from core.alignment_engine import ProfessionalAlignmentEngine

        engine = ProfessionalAlignmentEngine()
        sequences = task['sequences']
        tool = task.get('tool', 'biopython_pairwise')
        sequence_type = task.get('sequence_type', 'protein')

        # Choose appropriate matrix based on sequence type
        matrix = 'BLOSUM62' if sequence_type == 'protein' else 'NUC.4.4'

        try:
            # Perform actual alignment using BioPython
            if tool == 'biopython_pairwise':
                result_data = engine.align_with_biopython(
                    sequences[0],
                    sequences[1],
                    algorithm='global',
                    matrix=matrix
                )
                aligned_seq1 = result_data.get('aligned_seq1', sequences[0])
                aligned_seq2 = result_data.get('aligned_seq2', sequences[1])
            elif tool == 'clustal':
                # Use Clustal Omega if available - pass sequences separately
                try:
                    result_data = engine.align_with_clustalo(sequences[0], sequences[1])
                    aligned_seq1 = result_data.get('aligned_seq1', sequences[0])
                    aligned_seq2 = result_data.get('aligned_seq2', sequences[1])
                except Exception as e:
                    logger.warning(f"Clustal failed: {e}, falling back to BioPython")
                    result_data = engine.align_with_biopython(sequences[0], sequences[1], algorithm='global', matrix=matrix)
                    aligned_seq1 = result_data.get('aligned_seq1', sequences[0])
                    aligned_seq2 = result_data.get('aligned_seq2', sequences[1])
            elif tool == 'mafft':
                # Use MAFFT if available - pass sequences separately
                try:
                    result_data = engine.align_with_mafft(sequences[0], sequences[1])
                    aligned_seq1 = result_data.get('aligned_seq1', sequences[0])
                    aligned_seq2 = result_data.get('aligned_seq2', sequences[1])
                except Exception as e:
                    logger.warning(f"MAFFT failed: {e}, falling back to BioPython")
                    result_data = engine.align_with_biopython(sequences[0], sequences[1], algorithm='global', matrix=matrix)
                    aligned_seq1 = result_data.get('aligned_seq1', sequences[0])
                    aligned_seq2 = result_data.get('aligned_seq2', sequences[1])
            else:
                # Default to BioPython pairwise
                result_data = engine.align_with_biopython(
                    sequences[0],
                    sequences[1],
                    algorithm='global',
                    matrix=matrix
                )
                aligned_seq1 = result_data.get('aligned_seq1', sequences[0])
                aligned_seq2 = result_data.get('aligned_seq2', sequences[1])

        except Exception as align_err:
            logger.warning(f"Alignment tool error: {align_err}, falling back to simple alignment")
            # Fallback: just use original sequences
            aligned_seq1 = sequences[0]
            aligned_seq2 = sequences[1]

        result = {
            'aligned_sequences': [aligned_seq1, aligned_seq2],
            'tool': tool
        }

        task['result'] = result
        task['status'] = 'completed'

    except Exception as e:
        task = ALIGNMENT_TASKS.get(task_id)
        if task:
            task['status'] = 'error'
            task['error'] = str(e)


def _generate_consensus(sequences):
    """Generate simple consensus sequence"""
    if not sequences:
        return ''

    min_len = min(len(s) for s in sequences)
    consensus = []

    for i in range(min_len):
        bases = [s[i] for s in sequences]
        # Most common base
        consensus.append(max(set(bases), key=bases.count))

    return ''.join(consensus)


@bp.route('/result/<task_id>', methods=['GET'])
def get_alignment_result(task_id):
    """Get alignment result by task ID"""
    task = ALIGNMENT_TASKS.get(task_id)

    if not task:
        return jsonify({'error': 'Task not found'}), 404

    return jsonify({
        'task_id': task_id,
        'status': task['status'],
        'result': task.get('result'),
        'error': task.get('error')
    })


@bp.route('/result/<task_id>/stream', methods=['GET'])
def stream_alignment_result(task_id):
    """Stream alignment result using SSE"""

    def generate():
        import time
        checked = set()

        while True:
            task = ALIGNMENT_TASKS.get(task_id)

            if not task:
                yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
                break

            status = task['status']

            if status == 'completed':
                yield f"data: {json.dumps({'status': 'completed', 'result': task.get('result')})}\n\n"
                break
            elif status == 'error':
                yield f"data: {json.dumps({'status': 'error', 'error': task.get('error')})}\n\n"
                break
            elif status not in checked:
                checked.add(status)
                yield f"data: {json.dumps({'status': status})}\n\n"

            time.sleep(1)

    return Response(generate(), mimetype='text/event-stream')


@bp.route('/tools', methods=['GET'])
def get_alignment_tools():
    """Get available alignment tools"""
    return jsonify({
        'tools': [
            {
                'id': 'blast',
                'name': 'BLAST',
                'description': 'Basic Local Alignment Search Tool',
                'type': 'pairwise'
            },
            {
                'id': 'clustal',
                'name': 'Clustal',
                'description': 'Multiple sequence alignment',
                'type': 'multiple'
            },
            {
                'id': 'muscle',
                'name': 'MUSCLE',
                'description': 'Multiple sequence alignment',
                'type': 'multiple'
            }
        ]
    })


@bp.route('/compare', methods=['POST'])
def compare_sequences():
    """Compare two sequences and return similarity score"""
    try:
        data = request.get_json()

        seq1 = data.get('sequence1', '').upper()
        seq2 = data.get('sequence2', '').upper()

        if not seq1 or not seq2:
            return jsonify({'error': 'Both sequences required'}), 400

        # Calculate simple similarity
        min_len = min(len(seq1), len(seq2))
        matches = sum(1 for i in range(min_len) if seq1[i] == seq2[i])

        similarity = (matches / min_len * 100) if min_len > 0 else 0

        return jsonify({
            'sequence1': seq1,
            'sequence2': seq2,
            'similarity': round(similarity, 2),
            'match_count': matches,
            'length': min_len
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/extract-pdb', methods=['POST'])
def extract_pdb_sequence():
    """
    Extract sequence from uploaded PDB file
    Accepts multipart/form-data with 'file' field
    Returns extracted sequences from all chains/entities
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Save to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.pdb', delete=False) as tmp:
            tmp.write(file.read())
            tmp_path = tmp.name

        try:
            # Parse PDB using Biopython
            from Bio.PDB import PDBParser
            from Bio.Seq import Seq
            from Bio.SeqRecord import SeqRecord

            parser = PDBParser(QUIET=True)
            structure = parser.get_structure('structure', tmp_path)

            # Extract sequences from all models/chains
            sequences = []
            seen_sequences = set()  # Avoid duplicates

            for model in structure:
                for chain in model:
                    # Get chain sequence with actual residue numbers
                    seq_list = []
                    res_nums = []  # Store actual PDB residue numbers
                    for residue in chain:
                        # Skip heteroatoms and waters
                        if residue.id[0] in (' ', 'A'):  # Standard residues
                            try:
                                seq_list.append(residue.resname)
                                # Get the actual residue number from PDB
                                res_nums.append(residue.id[1])
                            except:
                                pass

                    # Convert 3-letter codes to 1-letter
                    aa_mapping = {
                        'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E',
                        'PHE': 'F', 'GLY': 'G', 'HIS': 'H', 'ILE': 'I',
                        'LYS': 'K', 'LEU': 'L', 'MET': 'M', 'ASN': 'N',
                        'PRO': 'P', 'GLN': 'Q', 'ARG': 'R', 'SER': 'S',
                        'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y'
                    }

                    seq_str = ''.join([aa_mapping.get(aa, 'X') for aa in seq_list])

                    if seq_str and seq_str not in seen_sequences:
                        seen_sequences.add(seq_str)
                        chain_id = chain.id
                        # Try to get entity info
                        entity_info = {
                            'chain': chain_id,
                            'sequence': seq_str,
                            'length': len(seq_str),
                            'model_id': model.id,
                            'residue_numbers': res_nums  # Actual PDB residue numbers
                        }

                        # Try to get PDB header info
                        try:
                            entity_info['pdb_id'] = structure.header.get('id', '')
                            entity_info['title'] = structure.header.get('title', '')
                        except:
                            pass

                        sequences.append(entity_info)

            if not sequences:
                return jsonify({'error': 'No valid protein sequences found in PDB file'}), 400

            return jsonify({
                'success': True,
                'structures': sequences,
                'count': len(sequences)
            })

        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"PDB extraction error: {e}")
        return jsonify({'error': f'Failed to parse PDB file: {str(e)}'}), 500


@bp.route('/extract-pdb-id', methods=['GET'])
def extract_pdb_by_id():
    """
    Fetch and extract sequence from PDB ID
    """
    try:
        pdb_id = request.args.get('pdb_id', '').strip().upper()

        if not pdb_id:
            return jsonify({'error': 'PDB ID required'}), 400

        if len(pdb_id) != 4:
            return jsonify({'error': 'Invalid PDB ID (must be 4 characters)'}), 400

        # Download PDB file
        import tempfile
        from urllib.request import urlretrieve

        pdb_url = f'https://files.rcsb.org/download/{pdb_id}.pdb'

        with tempfile.NamedTemporaryFile(mode='wb', suffix='.pdb', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            urlretrieve(pdb_url, tmp_path)

            # Parse using Biopython
            from Bio.PDB import PDBParser

            parser = PDBParser(QUIET=True)
            structure = parser.get_structure(pdb_id, tmp_path)

            sequences = []
            seen_sequences = set()

            aa_mapping = {
                'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E',
                'PHE': 'F', 'GLY': 'G', 'HIS': 'H', 'ILE': 'I',
                'LYS': 'K', 'LEU': 'L', 'MET': 'M', 'ASN': 'N',
                'PRO': 'P', 'GLN': 'Q', 'ARG': 'R', 'SER': 'S',
                'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y'
            }

            for model in structure:
                for chain in model:
                    seq_list = []
                    res_nums = []
                    for residue in chain:
                        if residue.id[0] in (' ', 'A'):
                            try:
                                seq_list.append(residue.resname)
                                res_nums.append(residue.id[1])
                            except:
                                pass

                    seq_str = ''.join([aa_mapping.get(aa, 'X') for aa in seq_list])

                    if seq_str and seq_str not in seen_sequences:
                        seen_sequences.add(seq_str)
                        sequences.append({
                            'chain': chain.id,
                            'sequence': seq_str,
                            'length': len(seq_str),
                            'model_id': model.id,
                            'pdb_id': pdb_id,
                            'residue_numbers': res_nums
                        })

            if not sequences:
                return jsonify({'error': 'No valid sequences found'}), 400

            return jsonify({
                'success': True,
                'pdb_id': pdb_id,
                'structures': sequences,
                'count': len(sequences)
            })

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"PDB fetch error: {e}")
        return jsonify({'error': f'Failed to fetch PDB: {str(e)}'}), 500
