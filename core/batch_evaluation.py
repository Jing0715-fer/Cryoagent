# batch_evaluation.py - 批量评估服务
"""
批量蛋白质评估服务 - 从 protein_evaluator 迁移
功能：
1. 批量评估多个蛋白质
2. 获取蛋白相互作用数据
3. 生成批量分析报告
"""

import os
import sys
import json
import logging
import threading
import time
import re
from typing import Dict, List, Optional, Any
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# 导入数据库操作
from core.literature_db import (
    create_protein_evaluation,
    get_protein_evaluation,
    update_protein_evaluation,
    create_batch_evaluation,
    get_batch_evaluation,
    get_all_batch_evaluations,
    update_batch_evaluation,
    delete_batch_evaluation,
    create_protein_interaction,
    get_protein_interactions,
    delete_protein_interactions,
    get_default_prompt_template,
    get_all_prompt_templates,
    create_prompt_template,
    update_prompt_template,
    delete_prompt_template,
    set_default_prompt_template,
    get_prompt_template,
    get_all_protein_evaluations
)

# 导入API客户端
from core.uniprot_client import UniProtAPIClient
from core.pdb_fetcher import PDBFetcher
from utils.ai_client import get_ai_client, OpenAIClient, AnthropicClient

# 尝试导入 protein_interaction_client
try:
    from core.protein_interaction_client import StringDBClient
    HAS_STRING_DB = True
except ImportError:
    HAS_STRING_DB = False


class BatchEvaluationService:
    """批量蛋白质评估服务"""

    def __init__(self):
        self.uniprot_client = UniProtAPIClient()
        self.pdb_fetcher = PDBFetcher()
        self.ai_client = None
        self.config = {
            'max_pdb': 100,
            'max_literature': 20,
            'ai_temperature': 0.3,
            'ai_max_tokens': 6000,
            'ai_prompt': ''
        }
        self._init_ai_client()

    def _init_ai_client(self):
        """初始化AI客户端"""
        try:
            self.ai_client = get_ai_client()
            logger.info("AI客户端初始化成功")
        except Exception as e:
            logger.warning(f"AI客户端初始化失败: {e}")

    def start_batch_evaluation(self, uniprot_ids: List[str], name: str = None, config: Dict = None) -> Dict[str, Any]:
        """
        开始批量蛋白质评估

        参数:
            uniprot_ids: UniProt蛋白质ID列表
            name: 批量评估名称（可选）
            config: 配置选项（可选）

        返回:
            批量评估任务信息
        """
        # 解析和验证 UniProt IDs
        parsed_ids = []
        for uniprot_id in uniprot_ids:
            clean_id = uniprot_id.strip().upper()
            if clean_id and clean_id not in parsed_ids:
                parsed_ids.append(clean_id)

        if not parsed_ids:
            return {'success': False, 'error': '请提供有效的UniProt ID列表'}

        if len(parsed_ids) < 2:
            return {'success': False, 'error': '批量评估至少需要2个UniProt ID'}

        try:
            # 创建批量评估记录
            batch_name = name or f"批量评估_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            batch = create_batch_evaluation(
                name=batch_name,
                uniprot_ids=parsed_ids,
                config=config or {}
            )

            if not batch:
                return {'success': False, 'error': '创建批量评估记录失败'}

            # 在后台线程中执行批量评估
            thread = threading.Thread(
                target=self._run_batch_evaluation_task,
                args=(batch.id, parsed_ids, config or {})
            )
            thread.daemon = True
            thread.start()

            return {
                'success': True,
                'batch_id': batch.id,
                'uniprot_ids': parsed_ids,
                'name': batch_name,
                'message': '批量评估任务已启动'
            }

        except Exception as e:
            logger.error(f"启动批量评估失败: {e}")
            return {'success': False, 'error': str(e)}

    def _add_batch_log(self, batch_id: int, message: str, level: str = 'info'):
        """添加日志到批量评估记录"""
        try:
            batch = get_batch_evaluation(batch_id)
            if batch:
                logs = batch.logs or []
                logs.append({
                    'timestamp': time.strftime('%H:%M:%S'),
                    'level': level,
                    'message': message
                })
                update_batch_evaluation(batch_id, {'logs': logs})
        except Exception as e:
            logger.warning(f"添加批量评估日志失败: {e}")

    def _run_batch_evaluation_task(self, batch_id: int, uniprot_ids: List[str], config: Dict):
        """在后台线程中执行批量评估任务"""
        try:
            # 设置配置
            default_config = {
                'max_pdb': 100,
                'max_literature': 20,
                'ai_temperature': 0.3,
                'ai_max_tokens': 6000,
                'ai_prompt': ''
            }
            if config:
                default_config.update(config)
            self.config = default_config

            logger.info(f"========== 开始批量评估任务 [ID={batch_id}, UniProt IDs={uniprot_ids}] ==========")

            # 更新状态为处理中
            update_batch_evaluation(batch_id, {
                'status': 'processing',
                'progress': 10
            })

            # 获取蛋白相互作用数据
            self._add_batch_log(batch_id, "开始获取蛋白相互作用数据...")
            interaction_data = self._fetch_protein_interactions(uniprot_ids)
            if interaction_data.get('interactions'):
                self._add_batch_log(batch_id, f"获取到 {len(interaction_data['interactions'])} 个相互作用")
            else:
                self._add_batch_log(batch_id, "未获取到蛋白相互作用数据，将使用AI分析")

            # 步骤2: 对每个蛋白进行单独评估
            update_batch_evaluation(batch_id, {'progress': 15})
            self._add_batch_log(batch_id, f"开始评估 {len(uniprot_ids)} 个蛋白质...")

            total_proteins = len(uniprot_ids)
            individual_results = []

            for idx, uniprot_id in enumerate(uniprot_ids):
                self._add_batch_log(batch_id, f"[{idx+1}/{total_proteins}] 开始评估蛋白 {uniprot_id}...")

                # 创建单独评估记录
                evaluation = create_protein_evaluation(uniprot_id=uniprot_id)
                if evaluation:
                    # 关联到批量评估
                    update_protein_evaluation(evaluation.id, {'batch_id': batch_id})

                    # 同步执行单独评估
                    try:
                        eval_result = self._run_evaluation_task_sync(evaluation.id, uniprot_id, default_config)
                        individual_results.append({
                            'uniprot_id': uniprot_id,
                            'evaluation_id': evaluation.id,
                            'status': eval_result.get('status', 'unknown')
                        })
                    except Exception as e:
                        logger.error(f"评估蛋白 {uniprot_id} 失败: {e}")
                        individual_results.append({
                            'uniprot_id': uniprot_id,
                            'evaluation_id': evaluation.id,
                            'status': 'failed',
                            'error': str(e)
                        })

                # 更新批量评估进度 (15% - 65%)
                progress = 15 + int((idx + 1) / total_proteins * 50)
                update_batch_evaluation(batch_id, {'progress': progress})

            self._add_batch_log(batch_id, "所有蛋白评估完成")

            # 步骤3: 运行批量AI分析
            update_batch_evaluation(batch_id, {'progress': 75})
            self._add_batch_log(batch_id, "开始批量AI分析...")

            batch_ai_result = self._run_batch_ai_analysis(
                uniprot_ids=uniprot_ids,
                interaction_data=interaction_data,
                individual_results=individual_results
            )

            update_batch_evaluation(batch_id, {
                'batch_ai_analysis': batch_ai_result,
                'interaction_data': interaction_data,
                'progress': 90
            })

            # 步骤4: 生成最终批量报告
            self._add_batch_log(batch_id, "生成综合报告...")
            batch_report = self._generate_batch_report(uniprot_ids, interaction_data, individual_results, batch_ai_result)

            # 标记完成
            update_batch_evaluation(batch_id, {
                'status': 'completed',
                'progress': 100,
                'batch_report': batch_report
            })

            self._add_batch_log(batch_id, "批量评估完成!")

            logger.info(f"========== 批量评估任务完成 [ID={batch_id}] ==========")

        except Exception as e:
            logger.error(f"批量评估任务失败: {e}")
            update_batch_evaluation(batch_id, {
                'status': 'failed'
            })
            self._add_batch_log(batch_id, f"评估失败: {str(e)}", 'error')

    def _fetch_protein_interactions(self, uniprot_ids: List[str]) -> Dict[str, Any]:
        """从String Database获取蛋白互作数据"""
        if not HAS_STRING_DB:
            return {'interactions': [], 'source': 'ai_analysis'}

        try:
            client = StringDBClient()
            return client.get_interactions(uniprot_ids)
        except Exception as e:
            logger.warning(f"获取蛋白互作数据失败: {e}")
            return {'interactions': [], 'source': 'string_db', 'error': str(e)}

    def _run_evaluation_task_sync(self, evaluation_id: int, uniprot_id: str, config: Dict) -> Dict:
        """同步执行单独蛋白质评估任务"""
        from core.protein_evaluation import get_evaluation_service

        try:
            # 使用现有的评估服务执行评估
            service = get_evaluation_service()

            # 直接运行评估任务（同步方式）
            service._run_evaluation_task(evaluation_id, uniprot_id, config)

            # 获取评估结果
            evaluation = get_protein_evaluation(evaluation_id)
            if evaluation:
                return {
                    'status': evaluation.evaluation_status,
                    'uniprot_id': uniprot_id
                }
            return {'status': 'unknown'}
        except Exception as e:
            logger.error(f"同步评估失败: {e}")
            return {'status': 'failed', 'error': str(e)}

    def _run_batch_ai_analysis(self, uniprot_ids: List[str], interaction_data: Dict,
                                 individual_results: List[Dict]) -> Dict[str, Any]:
        """运行批量AI分析"""
        try:
            # 获取AI客户端
            ai_client = get_ai_client()

            # 获取各个单独评估的报告
            individual_reports = self._get_individual_reports(uniprot_ids)

            # 构建批量分析prompt
            prompt = self._build_batch_prompt(uniprot_ids, interaction_data, individual_reports)

            # 调用AI
            messages = [
                {"role": "system", "content": "你是一个专业的蛋白质结构生物学家和生物信息学专家。请对多个蛋白质进行综合比较分析。"},
                {"role": "user", "content": prompt}
            ]

            response = ai_client.chat(
                messages,
                max_tokens=self.config.get('ai_max_tokens', 8000),
                temperature=self.config.get('ai_temperature', 0.3),
                timeout=300
            )

            if response.get('success'):
                return {
                    'success': True,
                    'analysis': response.get('content', ''),
                    'model': response.get('model', '')
                }
            else:
                return {'success': False, 'error': response.get('error', 'AI分析失败')}

        except Exception as e:
            logger.error(f"批量AI分析失败: {e}")
            return {'success': False, 'error': str(e)}

    def _get_individual_reports(self, uniprot_ids: List[str]) -> Dict[str, str]:
        """获取各单独评估的报告"""
        reports = {}
        for uniprot_id in uniprot_ids:
            try:
                # 从数据库获取最新的评估
                evaluations = get_all_protein_evaluations(limit=100)
                for ev in evaluations:
                    if ev.uniprot_id.upper() == uniprot_id.upper():
                        reports[uniprot_id] = ev.report or ''
                        break
                else:
                    reports[uniprot_id] = ''
            except Exception as e:
                logger.warning(f"获取蛋白 {uniprot_id} 报告失败: {e}")
                reports[uniprot_id] = ''
        return reports

    def _build_batch_prompt(self, uniprot_ids: List[str], interaction_data: Dict,
                             individual_reports: Dict[str, str]) -> str:
        """构建批量分析prompt"""
        # 获取批量分析模板
        template = get_default_prompt_template('batch')
        if template:
            prompt_template = template.content
        else:
            # 默认模板
            prompt_template = """请分析以下蛋白质的相互作用关系和功能特征：

蛋白质列表：{uniprot_ids}

相互作用数据：{interaction_data}

各蛋白质单独评估报告：
{individual_reports}

请提供：
1. 这些蛋白质之间的相互作用网络分析
2. 功能相关性分析
3. 结构研究价值评估
4. 潜在的研究方向建议
"""

        # 格式化相互作用数据
        interactions_str = ""
        if interaction_data.get('interactions'):
            for i in interaction_data['interactions']:
                interactions_str += f"- {i.get('protein_a')} <-> {i.get('protein_b')}: {i.get('interaction_type', 'unknown')}\n"

        # 格式化单独报告
        reports_str = ""
        for uniprot_id, report in individual_reports.items():
            reports_str += f"\n## {uniprot_id}\n{report[:1000]}\n"

        return prompt_template.format(
            uniprot_ids=', '.join(uniprot_ids),
            interaction_data=interactions_str or "无相互作用数据",
            individual_reports=reports_str
        )

    def _generate_batch_report(self, uniprot_ids: List[str], interaction_data: Dict,
                               individual_results: List[Dict], batch_ai_result: Dict) -> str:
        """生成批量评估综合报告"""
        # 使用AI分析结果作为报告
        if batch_ai_result.get('success') and batch_ai_result.get('analysis'):
            return batch_ai_result['analysis']

        # 如果AI分析失败，生成简单报告
        report = f"""# 批量蛋白质评估报告

评估时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 评估蛋白列表
{', '.join(uniprot_ids)}

## 评估结果摘要
- 总蛋白数: {len(uniprot_ids)}
- 成功评估: {len([r for r in individual_results if r.get('status') == 'completed'])}
- 评估失败: {len([r for r in individual_results if r.get('status') == 'failed'])}

## 蛋白相互作用
"""
        if interaction_data.get('interactions'):
            for i in interaction_data['interactions']:
                report += f"- {i.get('protein_a')} <-> {i.get('protein_b')}: {i.get('interaction_type', 'unknown')}\n"
        else:
            report += "无显著相互作用数据\n"

        return report

    # ========== 批量评估管理方法 ==========

    def list_batch_evaluations(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """获取批量评估列表"""
        try:
            batches = get_all_batch_evaluations(limit=limit, offset=offset)
            return {
                'success': True,
                'batches': [b.to_dict() for b in batches],
                'total': len(batches)
            }
        except Exception as e:
            logger.error(f"获取批量评估列表失败: {e}")
            return {'success': False, 'error': str(e)}

    def get_batch_evaluation_status(self, batch_id: int) -> Dict[str, Any]:
        """获取批量评估状态"""
        try:
            batch = get_batch_evaluation(batch_id)
            if not batch:
                return {'success': False, 'error': '批量评估不存在'}

            # 获取关联的单独评估
            from core.literature_db import get_all_protein_evaluations
            all_evals = get_all_protein_evaluations(limit=100)
            related_evals = [e for e in all_evals if e.batch_id == batch_id]

            return {
                'success': True,
                'batch': batch.to_dict(),
                'evaluations': [e.to_dict() for e in related_evals]
            }
        except Exception as e:
            logger.error(f"获取批量评估状态失败: {e}")
            return {'success': False, 'error': str(e)}

    def delete_batch_evaluation(self, batch_id: int) -> Dict[str, Any]:
        """删除批量评估"""
        try:
            # 先删除关联的相互作用数据
            delete_protein_interactions(batch_id)

            # 删除批量评估
            if delete_batch_evaluation(batch_id):
                return {'success': True, 'message': '批量评估已删除'}
            return {'success': False, 'error': '删除失败'}
        except Exception as e:
            logger.error(f"删除批量评估失败: {e}")
            return {'success': False, 'error': str(e)}


# 全局服务实例
_batch_evaluation_service = None


def get_batch_evaluation_service() -> BatchEvaluationService:
    """获取批量评估服务单例"""
    global _batch_evaluation_service
    if _batch_evaluation_service is None:
        _batch_evaluation_service = BatchEvaluationService()
    return _batch_evaluation_service