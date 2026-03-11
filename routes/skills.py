"""
Skills API Routes
"""
import os
import sys
import logging

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import jsonify, request, Blueprint

logger = logging.getLogger(__name__)

bp = Blueprint('skills', __name__, url_prefix='/api/skills')


def get_skill_registry_with_init():
    """获取 Skill 注册表（带初始化）"""
    from core.skills import get_skill_registry, initialize_skills

    registry = get_skill_registry()
    # 如果还没有注册任何 skill，进行初始化
    if not registry.list_skills():
        initialize_skills(registry)

    return registry


@bp.route('', methods=['GET'])
def list_skills():
    """列出所有可用 Skills"""
    try:
        registry = get_skill_registry_with_init()
        category = request.args.get('category')

        skills = registry.list_skills(category=category)

        return jsonify({
            "success": True,
            "skills": skills,
            "count": len(skills),
            "categories": registry.get_categories()
        })

    except Exception as e:
        logger.error(f"Error listing skills: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/<skill_id>', methods=['GET'])
def get_skill(skill_id):
    """获取指定 Skill 详情"""
    try:
        registry = get_skill_registry_with_init()
        skill = registry.get_skill(skill_id)

        if not skill:
            return jsonify({
                "success": False,
                "error": f"Skill {skill_id} not found"
            }), 404

        return jsonify({
            "success": True,
            "skill": skill.to_dict()
        })

    except Exception as e:
        logger.error(f"Error getting skill: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/match', methods=['POST'])
def match_skill():
    """根据查询匹配 Skill"""
    try:
        data = request.json
        query = data.get('query', '')

        if not query:
            return jsonify({
                "success": False,
                "error": "Query is required"
            }), 400

        registry = get_skill_registry_with_init()
        skill = registry.match_skill(query)

        if not skill:
            return jsonify({
                "success": True,
                "matched": False,
                "message": "No matching skill found"
            })

        return jsonify({
            "success": True,
            "matched": True,
            "skill": skill.to_dict()
        })

    except Exception as e:
        logger.error(f"Error matching skill: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/categories', methods=['GET'])
def list_categories():
    """获取所有 Skill 分类"""
    try:
        registry = get_skill_registry_with_init()
        categories = registry.get_categories()

        return jsonify({
            "success": True,
            "categories": categories
        })

    except Exception as e:
        logger.error(f"Error listing categories: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
