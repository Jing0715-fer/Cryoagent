# protein_evaluation.py - 蛋白质评估服务
"""
蛋白质评估模块 - 从n8n工作流迁移
功能：
1. 获取PDB/RCSB元数据
2. 获取UniProt元数据
3. 运行BLAST搜索
4. 运行AI分析
5. 生成评估报告
"""

import os
import sys
import json
import logging
import requests
import threading
import time
from functools import wraps
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# 创建不使用代理的session
def get_no_proxy_session():
    """创建不使用代理的session"""
    session = requests.Session()
    session.trust_env = False  # 禁用环境变量中的代理
    return session

# 全局session
http_session = get_no_proxy_session()


# ========== 重试装饰器 ==========
def retry_on_failure(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    API调用重试装饰器

    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff: 延迟倍增因子
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = delay * (backoff ** attempt)
                        logger.warning(f"{func.__name__} 失败 (尝试 {attempt + 1}/{max_retries}), {wait_time:.1f}秒后重试: {e}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"{func.__name__} 失败 (已重试{max_retries}次): {e}")
            raise last_exception
        return wrapper
    return decorator

# 导入数据库模型
from core.literature_db import (
    create_protein_evaluation,
    get_protein_evaluation,
    get_protein_evaluation_by_uniprot,
    get_all_protein_evaluations,
    update_protein_evaluation,
    delete_protein_evaluation,
    search_protein_evaluations
)

# 导入API客户端
from core.uniprot_client import UniProtAPIClient
from core.pdb_fetcher import PDBFetcher
from utils.ai_client import get_ai_client

# 导入PubMed客户端
try:
    from core.literature_agent import PubMedClient
    HAS_PUBMED = True
except ImportError:
    HAS_PUBMED = False

# 尝试导入RAG模块
try:
    from core.lancedb_rag.rag import get_unified_rag
    HAS_RAG = True
except ImportError:
    HAS_RAG = False

# 评估步骤定义
EVALUATION_STEPS = {
    'pending': {'progress': 0, 'message': '等待开始'},
    'fetching_pdb': {'progress': 10, 'message': '获取PDB数据'},
    'fetching_uniprot': {'progress': 30, 'message': '获取UniProt数据'},
    'blasting': {'progress': 50, 'message': '执行BLAST搜索'},
    'analyzing': {'progress': 70, 'message': 'AI分析中'},
    'generating_report': {'progress': 90, 'message': '生成报告'},
    'completed': {'progress': 100, 'message': '评估完成'},
    'failed': {'progress': 0, 'message': '评估失败'}
}


class ProteinEvaluationService:
    """蛋白质评估服务"""

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

    def start_evaluation(self, uniprot_id: str, gene_name: str = None, protein_name: str = None, config: Dict = None) -> Dict[str, Any]:
        """
        开始蛋白质评估（异步执行）

        参数:
            uniprot_id: UniProt蛋白质ID
            gene_name: 基因名称（可选）
            protein_name: 蛋白质名称（可选）
            config: 配置选项（可选）

        返回:
            评估任务信息
        """
        # Set default config
        if config is None:
            config = {}

        default_config = {
            'max_pdb': 100,
            'max_literature': 20,
            'ai_temperature': 0.3,
            'ai_max_tokens': 6000,
            'ai_prompt': ''
        }
        default_config.update(config)

        # Set config for this evaluation
        self.config = default_config

        try:
            # 创建评估记录
            evaluation = create_protein_evaluation(
                uniprot_id=uniprot_id,
                gene_name=gene_name,
                protein_name=protein_name
            )

            if not evaluation:
                return {'success': False, 'error': '创建评估记录失败'}

            # 在后台线程中执行评估
            thread = threading.Thread(
                target=self._run_evaluation_task,
                args=(evaluation.id, uniprot_id, default_config)
            )
            thread.daemon = True
            thread.start()

            return {
                'success': True,
                'evaluation_id': evaluation.id,
                'uniprot_id': uniprot_id,
                'message': '评估任务已启动'
            }

        except Exception as e:
            logger.error(f"启动评估失败: {e}")
            return {'success': False, 'error': str(e)}

    def _run_evaluation_task(self, evaluation_id: int, uniprot_id: str, config: Dict = None):
        """在后台线程中执行评估任务"""
        task_start_time = time.time()
        step_times = {}  # 记录每个步骤的耗时

        try:
            logger.info(f"========== 开始评估任务 [ID={evaluation_id}, UniProt={uniprot_id}] ==========")

            # 更新状态为处理中
            update_protein_evaluation(evaluation_id, {
                'evaluation_status': 'processing',
                'current_step': 'fetching_pdb',
                'progress': 10
            })

            # 步骤1: 获取UniProt元数据
            step_start = time.time()
            uniprot_data = self._fetch_uniprot_metadata(uniprot_id)
            step_time = time.time() - step_start
            step_times['fetch_uniprot'] = step_time

            logger.info(f"[步骤1/6] 获取UniProt元数据: 耗时 {step_time:.2f}秒")
            if uniprot_data:
                logger.info(f"  - UniProt ID: {uniprot_data.get('uniprot_id')}")
                logger.info(f"  - 蛋白质名称: {uniprot_data.get('protein_name', 'N/A')[:50]}")
                logger.info(f"  - 基因名: {', '.join(uniprot_data.get('gene_names', []))}")
                logger.info(f"  - 物种: {uniprot_data.get('organism', 'N/A')}")
                logger.info(f"  - PDB结构数量: {len(uniprot_data.get('pdb_ids', []))}")

            update_protein_evaluation(evaluation_id, {
                'uniprot_data': uniprot_data,
                'current_step': 'fetching_uniprot',
                'progress': 30
            })

            # 从UniProt数据中提取基因名和蛋白质名
            if uniprot_data:
                gene_name = uniprot_data.get('gene_names', [None])[0]
                protein_name = uniprot_data.get('protein_name', None)
                update_protein_evaluation(evaluation_id, {
                    'gene_name': gene_name,
                    'protein_name': protein_name
                })

            # 步骤2: 获取PDB数据
            pdb_ids = uniprot_data.get('pdb_ids', []) if uniprot_data else []
            # Limit PDB count based on config
            max_pdb = self.config.get('max_pdb', 100)
            if len(pdb_ids) > max_pdb:
                pdb_ids = pdb_ids[:max_pdb]
                logger.info(f"  - 限制PDB数量为 {max_pdb} 个")
            step_start = time.time()
            pdb_data = self._fetch_pdb_metadata(pdb_ids)
            step_time = time.time() - step_start
            step_times['fetch_pdb'] = step_time

            logger.info(f"[步骤2/6] 获取PDB元数据: 耗时 {step_time:.2f}秒")
            logger.info(f"  - 获取到 {len(pdb_data.get('structures', []))} 个PDB结构")
            logger.info(f"  - 获取到 {sum(len(s.get('citations', [])) for s in pdb_data.get('structures', []))} 篇文献")

            # 统计分辨率信息
            resolutions = [s.get('basic_info', {}).get('resolution') for s in pdb_data.get('structures', []) if s.get('basic_info', {}).get('resolution')]
            if resolutions:
                logger.info(f"  - 分辨率范围: {min(resolutions):.2f} - {max(resolutions):.2f} Å (平均: {sum(resolutions)/len(resolutions):.2f} Å)")

            # 统计实验方法
            methods = {}
            for s in pdb_data.get('structures', []):
                method = s.get('basic_info', {}).get('experimental_method', 'Unknown')
                methods[method] = methods.get(method, 0) + 1
            logger.info(f"  - 实验方法: {methods}")

            update_protein_evaluation(evaluation_id, {
                'pdb_data': pdb_data,
                'current_step': 'blasting',
                'progress': 50
            })

            # 步骤3: 计算PDB覆盖度并决定是否运行BLAST搜索
            # 条件: 覆盖度 < 50% 或 PDB数量 < 5 时才执行BLAST
            protein_length = uniprot_data.get('sequence', 0) if uniprot_data else 0
            if isinstance(protein_length, str):
                protein_length = 0  # sequence字段应该是数字

            # 获取protein_length的正确字段
            protein_length = uniprot_data.get('sequence_length', 0) if uniprot_data else 0

            pdb_count = len(pdb_data.get('structures', []))
            coverage_info = self._calculate_pdb_coverage(pdb_data, protein_length, uniprot_id)
            coverage_pct = coverage_info.get('coverage_percent', 0)

            logger.info(f"  - PDB覆盖度: {coverage_pct:.1f}% (蛋白长度: {protein_length} aa, 覆盖残基: {coverage_info.get('covered_residues', 0)} aa)")

            # 判断是否需要运行BLAST
            need_blast = coverage_pct < 50 or pdb_count < 5

            if need_blast:
                logger.info(f"  - 开始BLAST搜索 (覆盖度 {coverage_pct:.1f}% < 50% 或 PDB {pdb_count} < 5)")
                sequence = uniprot_data.get('sequence', '') if uniprot_data else ''
                step_start = time.time()
                blast_results = self._run_blast_search(uniprot_id, sequence) if uniprot_id else {}
                step_time = time.time() - step_start
                step_times['blast_search'] = step_time
                logger.info(f"[步骤3/6] BLAST搜索: 耗时 {step_time:.2f}秒")
                logger.info(f"  - 找到 {len(blast_results.get('results', []))} 个相似蛋白")
            else:
                logger.info(f"  - 跳过BLAST搜索 (覆盖度 {coverage_pct:.1f}% >= 50% 且 PDB {pdb_count} >= 5)")
                blast_results = {}

            update_protein_evaluation(evaluation_id, {
                'blast_results': blast_results,
                'current_step': 'analyzing',
                'progress': 70
            })

            # 步骤4: 运行AI分析
            step_start = time.time()
            ai_analysis = self._run_ai_analysis(
                uniprot_data=uniprot_data,
                pdb_data=pdb_data,
                blast_results=blast_results
            )
            step_time = time.time() - step_start
            step_times['ai_analysis'] = step_time

            logger.info(f"[步骤4/6] AI分析: 耗时 {step_time:.2f}秒")
            if ai_analysis.get('analysis'):
                logger.info(f"  - 分析字数: {len(ai_analysis['analysis'])} 字符")
            if ai_analysis.get('model'):
                logger.info(f"  - 使用模型: {ai_analysis['model']}")

            update_protein_evaluation(evaluation_id, {
                'ai_analysis': ai_analysis,
                'current_step': 'generating_report',
                'progress': 90
            })

            # 步骤5: 生成报告
            step_start = time.time()
            report = self._generate_report(
                uniprot_data=uniprot_data,
                pdb_data=pdb_data,
                blast_results=blast_results,
                ai_analysis=ai_analysis
            )
            step_time = time.time() - step_start
            step_times['generate_report'] = step_time

            logger.info(f"[步骤5/6] 生成报告: 耗时 {step_time:.2f}秒")
            logger.info(f"  - 报告字数: {len(report)} 字符")

            update_protein_evaluation(evaluation_id, {
                'report': report,
                'evaluation_status': 'completed',
                'current_step': 'completed',
                'progress': 100,
                'completed_at': datetime.now()
            })

            # 步骤6: 保存到RAG
            step_start = time.time()
            self._save_to_rag(evaluation_id, uniprot_data, pdb_data, blast_results, ai_analysis, report)
            step_time = time.time() - step_start
            step_times['save_to_rag'] = step_time

            logger.info(f"[步骤6/6] 保存到RAG: 耗时 {step_time:.2f}秒")

            # 计算总耗时
            total_time = time.time() - task_start_time
            step_times['total'] = total_time

            # 输出汇总
            logger.info(f"========== 评估任务完成 [ID={evaluation_id}] ==========")
            logger.info(f"总耗时: {total_time:.2f}秒 ({total_time/60:.2f}分钟)")
            logger.info(f"各步骤耗时明细:")
            for step, t in step_times.items():
                if step != 'total':
                    pct = (t / total_time * 100) if total_time > 0 else 0
                    logger.info(f"  - {step}: {t:.2f}秒 ({pct:.1f}%)")

        except Exception as e:
            logger.error(f"评估任务失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            update_protein_evaluation(evaluation_id, {
                'evaluation_status': 'failed',
                'error_message': str(e),
                'current_step': 'failed'
            })

    @retry_on_failure(max_retries=3, delay=1.0)
    def _fetch_uniprot_metadata(self, uniprot_id: str) -> Dict[str, Any]:
        """获取UniProt元数据 - 直接调用API"""
        try:
            # 直接调用UniProt API，绕过代理问题
            url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}?format=json"
            response = http_session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            # 提取需要的字段
            uniprot_id = data.get('primaryAccession', '')
            entry_name = data.get('uniProtkbId', '')

            # 蛋白质名称
            protein_name = ''
            protein_desc = data.get('proteinDescription', {})
            if protein_desc.get('recommendedName'):
                protein_name = protein_desc['recommendedName'].get('fullName', {}).get('value', '')

            # 基因名
            gene_names = []
            genes = data.get('genes', [])
            for gene in genes:
                if gene.get('geneName'):
                    gene_names.append(gene['geneName'].get('value', ''))
                for syn in gene.get('synonyms', []):
                    gene_names.append(syn.get('value', ''))

            # 物种
            organism = ''
            org_data = data.get('organism', {})
            if org_data:
                organism = org_data.get('scientificName', '')

            # 功能描述 - 增加防御性检查
            function = ''
            try:
                comments = data.get('comments')
                if isinstance(comments, list):
                    for comment in comments:
                        if isinstance(comment, dict) and comment.get('type') == 'function':
                            texts = comment.get('texts')
                            if isinstance(texts, list) and len(texts) > 0:
                                first_text = texts[0]
                                if isinstance(first_text, dict):
                                    function = first_text.get('value', '') or ''
                            break
            except Exception as e:
                logger.warning(f"获取function失败: {e}")

            # 序列长度
            sequence_length = 0
            sequence_info = data.get('sequence', {})
            if sequence_info:
                sequence_length = sequence_info.get('length', 0)

            # 分子量
            mass = sequence_info.get('molWeight', 0)

            # PDB IDs - 从uniProtKBCrossReferences获取
            pdb_ids = []
            for ref in data.get('uniProtKBCrossReferences', []):
                if ref.get('database') == 'PDB':
                    pdb_ids.append(ref.get('id', ''))

            # 关键词 - 增加防御性检查
            keywords = []
            try:
                kw_list = data.get('keywords')
                if isinstance(kw_list, list):
                    for kw in kw_list:
                        if isinstance(kw, dict):
                            kw_obj = kw.get('keyword')
                            if isinstance(kw_obj, dict):
                                val = kw_obj.get('value')
                                if val:
                                    keywords.append(val)
            except Exception as e:
                logger.warning(f"获取keywords失败: {e}")

            # 记录详细日志
            logger.info(f"UniProt API 响应解析完成:")
            logger.info(f"  - primaryAccession: {uniprot_id}")
            logger.info(f"  - entryName: {entry_name}")
            logger.info(f"  - proteinName: {protein_name[:50]}..." if len(protein_name) > 50 else f"  - proteinName: {protein_name}")
            logger.info(f"  - geneNames: {gene_names}")
            logger.info(f"  - organism: {organism}")
            logger.info(f"  - sequenceLength: {sequence_length} aa")
            logger.info(f"  - mass: {mass} Da")
            logger.info(f"  - pdbIds: {list(set(pdb_ids))}")
            logger.info(f"  - keywords: {keywords[:10]}..." if len(keywords) > 10 else f"  - keywords: {keywords}")

            return {
                'uniprot_id': uniprot_id,
                'entry_name': entry_name,
                'protein_name': protein_name,
                'gene_names': gene_names,
                'organism': organism,
                'function': function,
                'sequence': sequence_length,
                'mass': mass,
                'pdb_ids': list(set(pdb_ids)),  # 去重
                'keywords': keywords,
                'raw_data': data  # 保存原始数据
            }
        except Exception as e:
            logger.error(f"获取UniProt元数据失败: {e}")
            # 尝试备用方法 - 调用uniprot_client
            try:
                entry = self.uniprot_client.get_by_uniprot_id(uniprot_id)
                if entry:
                    return {
                        'uniprot_id': entry.uniprot_id,
                        'entry_name': entry.entry_name,
                        'protein_name': entry.protein_name,
                        'gene_names': entry.gene_names,
                        'organism': entry.organism,
                        'function': entry.function,
                        'sequence': entry.sequence_length,
                        'mass': entry.mass,
                        'pdb_ids': entry.pdb_ids,
                        'keywords': entry.keywords,
                        'subcellular_location': entry.subcellular_location
                    }
            except:
                pass
        return {}

    @retry_on_failure(max_retries=3, delay=1.0)
    def _fetch_pdb_metadata(self, pdb_ids: List[str]) -> Dict[str, Any]:
        """获取PDB元数据 - 直接调用RCSB/PDBe API"""
        result = {'pdb_ids': [], 'structures': []}

        # 获取全部PDB结构，但限制最多100个以避免API超时
        pdb_ids_to_fetch = pdb_ids[:100] if len(pdb_ids) > 100 else pdb_ids

        logger.info(f"开始获取 {len(pdb_ids_to_fetch)} 个PDB结构 (共 {len(pdb_ids)} 个)")

        success_count = 0
        fail_count = 0

        for pdb_id in pdb_ids_to_fetch:
            try:
                # 调用RCSB API获取PDB元数据
                rcsb_url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
                rcsb_response = http_session.get(rcsb_url, timeout=30)

                if rcsb_response.status_code == 200:
                    rcsb_data = rcsb_response.json()

                    # 提取基本信息 - 增加防御性检查
                    basic_info = {
                        'title': '',
                        'experimental_method': '',
                        'resolution': None,
                        'deposition_date': '',
                    }

                    # 安全获取struct.title
                    try:
                        struct_data = rcsb_data.get('struct')
                        if struct_data and isinstance(struct_data, dict):
                            title_val = struct_data.get('title')
                            basic_info['title'] = title_val if isinstance(title_val, str) else ''
                    except Exception as e:
                        logger.warning(f"获取title失败: {e}")

                    # 实验方法 - 增加防御性检查
                    try:
                        exptl = rcsb_data.get('exptl')
                        if exptl and isinstance(exptl, list) and len(exptl) > 0:
                            first_exptl = exptl[0]
                            if first_exptl and isinstance(first_exptl, dict):
                                method_val = first_exptl.get('method')
                                basic_info['experimental_method'] = method_val if isinstance(method_val, str) else ''
                    except Exception as e:
                        logger.warning(f"获取experimental_method失败: {e}")

                    # 分辨率 - 增强获取，尝试多个来源
                    # 来源1: rcsb_entry_info.diffrn_resolution_high.value (X-ray)
                    try:
                        rcsb_info = rcsb_data.get('rcsb_entry_info')
                        if rcsb_info and isinstance(rcsb_info, dict):
                            diffrn_res = rcsb_info.get('diffrn_resolution_high')
                            if diffrn_res and isinstance(diffrn_res, dict):
                                res_val = diffrn_res.get('value')
                                if isinstance(res_val, (int, float)):
                                    basic_info['resolution'] = res_val
                    except Exception as e:
                        logger.warning(f"获取diffrn_resolution_high失败: {e}")

                    # 来源2: 如果来源1没有，尝试 reflns.d_resolution_high
                    if not basic_info['resolution']:
                        try:
                            refl = rcsb_data.get('reflns')
                            if refl and isinstance(refl, list) and len(refl) > 0:
                                first_refl = refl[0]
                                if first_refl and isinstance(first_refl, dict):
                                    res_val = first_refl.get('d_resolution_high')
                                    if isinstance(res_val, (int, float)):
                                        basic_info['resolution'] = res_val
                        except Exception as e:
                            logger.warning(f"获取reflns.d_resolution_high失败: {e}")

                    # 来源3: resolution_combined (可能是数组)
                    if not basic_info['resolution']:
                        try:
                            rcsb_info = rcsb_data.get('rcsb_entry_info')
                            if rcsb_info and isinstance(rcsb_info, dict):
                                res_combined = rcsb_info.get('resolution_combined')
                                if res_combined and isinstance(res_combined, list) and len(res_combined) > 0:
                                    res_val = res_combined[0]
                                    if isinstance(res_val, (int, float)):
                                        basic_info['resolution'] = res_val
                        except Exception as e:
                            logger.warning(f"获取resolution_combined失败: {e}")

                    # 沉积日期 - 增加防御性检查
                    try:
                        rcsb_info = rcsb_data.get('rcsb_entry_info')
                        if rcsb_info and isinstance(rcsb_info, dict):
                            # 尝试从rcsb_entry_info获取
                            date_val = rcsb_info.get('deposition_date')
                            basic_info['deposition_date'] = date_val if isinstance(date_val, str) else ''
                            # 如果没有，尝试从rcsb_accession_info获取
                            if not basic_info['deposition_date']:
                                acc_info = rcsb_data.get('rcsb_accession_info')
                                if acc_info and isinstance(acc_info, dict):
                                    date_val = acc_info.get('initial_release_date')
                                    basic_info['deposition_date'] = date_val if isinstance(date_val, str) else ''
                    except Exception as e:
                        logger.warning(f"获取deposition_date失败: {e}")

                    # 获取PDBe entities
                    pdbe_url = f"https://www.ebi.ac.uk/pdbe/api/pdb/entry/entities/{pdb_id}"
                    pdbe_response = http_session.get(pdbe_url, timeout=30)
                    entities = []
                    if pdbe_response.status_code == 200:
                        entities = pdbe_response.json()

                    # 只保留主要引用 (rcsb_primary_citation)
                    citations = []
                    primary_citation = rcsb_data.get('rcsb_primary_citation', {})

                    if isinstance(primary_citation, dict) and primary_citation.get('title'):
                        primary_pmids = primary_citation.get('pdbx_database_id_pub_med')
                        # 安全处理pubmed_id
                        pubmed_id = None
                        if isinstance(primary_pmids, str):
                            pubmed_id = primary_pmids
                        elif isinstance(primary_pmids, list) and len(primary_pmids) > 0:
                            pubmed_id = primary_pmids[0]
                        elif isinstance(primary_pmids, int):
                            pubmed_id = str(primary_pmids)

                        citations.append({
                            'title': primary_citation.get('title', ''),
                            'authors': primary_citation.get('rcsb_authors', []),
                            'journal': primary_citation.get('journal_abbrev', ''),
                            'year': primary_citation.get('year'),
                            'volume': primary_citation.get('journal_volume', ''),
                            'pages': f"{primary_citation.get('page_first', '')}-{primary_citation.get('page_last', '')}",
                            'doi': primary_citation.get('pdbx_database_id_doi', ''),
                            'pubmed_id': pubmed_id
                        })

                    result['structures'].append({
                        'pdb_id': pdb_id,
                        'basic_info': basic_info,
                        'entities': entities,
                        'citations': citations,
                        'rcsb_data': rcsb_data
                    })
                    result['pdb_ids'].append(pdb_id)
                    success_count += 1
                    logger.info(f"成功获取PDB {pdb_id} 元数据:")
                    logger.info(f"  - title: {basic_info.get('title', 'N/A')[:80]}...")
                    logger.info(f"  - experimental_method: {basic_info.get('experimental_method', 'N/A')}")
                    logger.info(f"  - resolution: {basic_info.get('resolution', 'N/A')} Å")
                    logger.info(f"  - deposition_date: {basic_info.get('deposition_date', 'N/A')}")
                    logger.info(f"  - citations: {len(citations)} 篇")
                else:
                    fail_count += 1
                    logger.warning(f"RCSB API返回 {rcsb_response.status_code} for {pdb_id}")

            except Exception as e:
                fail_count += 1
                logger.warning(f"获取PDB {pdb_id} 失败: {e}")

        logger.info(f"PDB获取完成: 成功 {success_count} 个, 失败 {fail_count} 个")

        # 获取PubMed摘要
        result = self._fetch_pubmed_abstracts(result)

        return result

    @retry_on_failure(max_retries=3, delay=2.0)
    def _fetch_pubmed_abstracts(self, pdb_data: Dict) -> Dict:
        """获取PDB相关文献的PubMed摘要"""
        if not HAS_PUBMED:
            logger.warning("PubMed客户端未安装，跳过摘要获取")
            return pdb_data

        try:
            pubmed_client = PubMedClient()

            for struct in pdb_data.get('structures', []):
                citations = struct.get('citations', [])
                for cit in citations:
                    pubmed_id = cit.get('pubmed_id')
                    if pubmed_id:
                        try:
                            article_info = pubmed_client.get_article_info_simple(str(pubmed_id))
                            if article_info:
                                cit['abstract'] = article_info.get('abstract', '')
                                logger.info(f"成功获取PMID {pubmed_id} 摘要")
                        except Exception as e:
                            logger.warning(f"获取PMID {pubmed_id} 摘要失败: {e}")

        except Exception as e:
            logger.warning(f"获取PubMed摘要失败: {e}")

        return pdb_data

    def _calculate_pdb_coverage(self, pdb_data: Dict, protein_length: int, target_uniprot_id: str = None) -> Dict[str, Any]:
        """计算 PDB 对蛋白质序列的覆盖度"""
        if not pdb_data or not pdb_data.get('structures') or protein_length <= 0:
            return {'coverage_percent': 0, 'covered_residues': 0, 'pdb_count': 0}

        # 获取每个 PDB 结构的序列覆盖范围
        covered_residues = set()
        pdb_ids = [s.get('pdb_id') for s in pdb_data.get('structures', [])]

        try:
            for pdb_id in pdb_ids:
                try:
                    # 使用 PDBe API 获取 UniProt 映射和序列范围
                    url = f"https://www.ebi.ac.uk/pdbe/api/mappings/all_isoforms/{pdb_id.lower()}"
                    resp = http_session.get(url, timeout=10)

                    if resp.status_code == 200:
                        data = resp.json()
                        pdb_entry = data.get(pdb_id.lower(), {})
                        uniprot_data = pdb_entry.get('UniProt', {})

                        for uniprot_id, uniprot_info in uniprot_data.items():
                            # 如果指定了目标 UniProt，只处理匹配的
                            if target_uniprot_id and uniprot_id.upper() != target_uniprot_id.upper():
                                # 跳过不匹配的 UniProt（比如 isoform ID 如 P04637-2）
                                if not uniprot_id.startswith(target_uniprot_id.upper()):
                                    continue

                            mappings = uniprot_info.get('mappings', [])
                            for mapping in mappings:
                                unp_start = mapping.get('unp_start')
                                unp_end = mapping.get('unp_end')

                                if unp_start and unp_end:
                                    for pos in range(unp_start, unp_end + 1):
                                        covered_residues.add(pos)
                except Exception as e:
                    logger.warning(f"获取 {pdb_id} 覆盖度失败: {e}")
                    continue

        except Exception as e:
            logger.warning(f"计算 PDB 覆盖度失败: {e}")

        # 计算覆盖度（不超过100%）
        covered_count = len(covered_residues)
        coverage_percent = min((covered_count / protein_length * 100), 100) if protein_length > 0 else 0

        return {
            'coverage_percent': coverage_percent,
            'covered_residues': covered_count,
            'pdb_count': len(pdb_ids)
        }

    @retry_on_failure(max_retries=3, delay=2.0)
    def _run_blast_search(self, uniprot_id: str, sequence: str = None) -> Dict[str, Any]:
        """
        运行相似蛋白搜索（使用UniProt API，替代NCBI BLAST）
        1. 先从UniProt获取蛋白质序列和分类信息
        2. 使用UniProt搜索API查找同源蛋白
        """
        results = []
        protein_sequence = sequence
        organism = None

        try:
            # 步骤1: 如果没有传入序列，从UniProt获取
            if not protein_sequence and uniprot_id:
                logger.info(f"从UniProt获取蛋白质信息: {uniprot_id}")
                url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}?format=json"
                response = http_session.get(url, timeout=30)

                if response.status_code == 200:
                    data = response.json()
                    seq_info = data.get('sequence', {})
                    protein_sequence = seq_info.get('value', '')

                    # 获取物种信息
                    organism_info = data.get('organism', {})
                    organism = organism_info.get('scientificName', None)
                    taxonomy_id = organism_info.get('taxonId', None)

                    logger.info(f"获取到序列长度: {len(protein_sequence)} aa, 物种: {organism}")

            if not protein_sequence:
                logger.warning(f"无法获取 {uniprot_id} 的序列")
                return {'query_id': uniprot_id, 'results': []}

            # 步骤2: 使用UniProt搜索同源蛋白
            logger.info("使用UniProt搜索同源蛋白...")

            # 搜索相同物种的蛋白（排除自身）
            if taxonomy_id:
                search_url = "https://rest.uniprot.org/uniprotkb/search"
                params = {
                    'query': f'taxon_id:{taxonomy_id}',
                    'format': 'json',
                    'size': 20,
                    'fields': 'accession,gene_names,protein_name,organism_name,sequence'
                }

                response = http_session.get(search_url, params=params, timeout=30)

                if response.status_code == 200:
                    data = response.json()
                    results_list = data.get('results', [])

                    # 过滤掉自身，并提取序列相似的蛋白
                    for entry in results_list:
                        accession = entry.get('primaryAccession', '')
                        if accession == uniprot_id:
                            continue

                        # 获取基因名
                        gene_names = entry.get('genes', [])
                        gene_name = gene_names[0].get('geneName', {}).get('value', '') if gene_names else ''

                        # 获取蛋白名
                        protein_rec = entry.get('proteinName', {})
                        protein_name_val = protein_rec.get('fullName', {}).get('value', '') if isinstance(protein_rec, dict) else str(protein_rec)

                        # 获取物种名
                        org_rec = entry.get('organism', {})
                        org_name = org_rec.get('scientificName', '') if isinstance(org_rec, dict) else ''

                        results.append({
                            'uniprot_id': accession,
                            'entry_name': gene_name,
                            'protein_name': protein_name_val[:100] if protein_name_val else '',
                            'organism': org_name
                        })

                    logger.info(f"UniProt搜索返回 {len(results)} 个同物种蛋白")

            # 步骤3: 如果结果不足，尝试搜索相似的PDB结构
            if len(results) < 10 and taxonomy_id:
                # 搜索PDB数据库中同物种的结构
                pdb_search_url = "https://search.rcsb.org/rcsbsearch/v1/query"
                pdb_query = {
                    "query": {
                        "type": "group",
                        "logical_operator": "and",
                        "nodes": [
                            {
                                "type": "taxonomy",
                                "operator": "exact_match",
                                "value": taxonomy_id
                            }
                        ]
                    },
                    "return_type": "entry",
                    "request_options": {
                        "page_size": 20,
                        "results_content_type": ["experimental"]
                    }
                }

                try:
                    pdb_response = http_session.post(pdb_search_url, json=pdb_query, timeout=30)
                    if pdb_response.status_code == 200:
                        pdb_data = pdb_response.json()
                        pdb_list = pdb_data.get('result_set', {}).get('dbrefs', [])

                        existing_pdb = set(r.get('uniprot_id', '').lower() for r in results)

                        for pdb_entry in pdb_list:
                            pdb_id = pdb_entry.get('uid', '')
                            if pdb_id and pdb_id.lower() not in existing_pdb and pdb_id.upper() != uniprot_id.upper():
                                results.append({
                                    'uniprot_id': pdb_id,
                                    'entry_name': '',
                                    'protein_name': f'PDB Structure {pdb_id}',
                                    'organism': organism or 'Various'
                                })
                                if len(results) >= 20:
                                    break

                        logger.info(f"从PDB数据库补充到 {len(results)} 个相似结构")
                except Exception as e:
                    logger.warning(f"PDB搜索失败: {e}")

            if not results:
                logger.warning("相似蛋白搜索无结果")

        except Exception as e:
            logger.error(f"相似蛋白搜索失败: {e}")

        logger.info(f"相似蛋白搜索完成，共找到 {len(results)} 个")
        return {'query_id': uniprot_id, 'results': results[:20]}

    def _run_ai_analysis(self, uniprot_data: Dict, pdb_data: Dict, blast_results: Dict) -> Dict[str, Any]:
        """运行AI分析"""
        if not self.ai_client:
            return {'error': 'AI客户端未初始化'}

        try:
            # 构建分析提示
            prompt = self._build_analysis_prompt(uniprot_data, pdb_data, blast_results)

            messages = [
                {"role": "system", "content": "你是一个专业的蛋白质结构生物学家。请对给定的蛋白质进行综合分析。"},
                {"role": "user", "content": prompt}
            ]

            # Use config values for AI parameters
            ai_max_tokens = self.config.get('ai_max_tokens', 6000)
            ai_temperature = self.config.get('ai_temperature', 0.3)

            response = self.ai_client.chat(messages, max_tokens=ai_max_tokens, temperature=ai_temperature, timeout=300)

            if response.get('success'):
                return {
                    'analysis': response.get('content', ''),
                    'model': response.get('model', 'unknown')
                }
            else:
                return {'error': response.get('error', 'AI分析失败')}

        except Exception as e:
            logger.error(f"AI分析失败: {e}")
            return {'error': str(e)}

    def _build_analysis_prompt(self, uniprot_data: Dict, pdb_data: Dict, blast_results: Dict) -> str:
        """构建AI分析提示 - 全面分析报告 (参考n8n工作流)"""
        parts = []

        # 系统指令 - 优化为更清晰的报告结构
        system_instruction = """# 蛋白质结构功能分析报告生成器

你是一个专业的蛋白质结构生物学家和生物信息学专家。请根据以下提供的蛋白质数据，生成一份**全面深入的综合分析报告**。

## 报告要求：
1. **字数要求**：报告总字数应在**4000字以上**
2. **分析深度**：每个分析维度都要有深度解读，包含足够的细节和科学见解
3. **结构清晰**：使用多级标题组织内容
4. **数据驱动**：结合具体的PDB结构数据、文献和相似蛋白进行分析
5. **实用价值**：分析结果应对后续研究有实际指导意义

## 数据来源：
- UniProt: 蛋白质序列和功能注释
- RCSB/PDBe: PDB结构元数据
- PubMed: 相关文献
- BLAST: 同源蛋白搜索

请按以下框架生成报告："""

        parts.append(system_instruction)

        # 1. 蛋白质基本信息
        if uniprot_data:
            uniprot_id = uniprot_data.get('uniprot_id', 'N/A')
            protein_name = uniprot_data.get('protein_name', 'N/A')
            gene_names = ', '.join(uniprot_data.get('gene_names', []))
            organism = uniprot_data.get('organism', 'N/A')
            sequence = uniprot_data.get('sequence', 'N/A')
            mass = uniprot_data.get('mass', 'N/A')
            function = uniprot_data.get('function', '无数据')
            if function and len(function) > 500:
                function = function[:500] + '...'
            keywords = ', '.join(uniprot_data.get('keywords', [])[:20])
            pdb_count = len(uniprot_data.get('pdb_ids', []))

            parts.append(f"""
# 蛋白质基础信息

| 属性 | 值 |
|------|-----|
| UniProt ID | {uniprot_id} |
| 蛋白质名称 | {protein_name} |
| 基因名 | {gene_names} |
| 物种 | {organism} |
| 序列长度 | {sequence} aa |
| 分子量 | {mass} Da |
| PDB结构数量 | {pdb_count}个 |

## 功能描述
{function if function != '无数据' else '暂无功能描述'}

## 关键词
{keywords if keywords else '暂无关键词'}
""")

        # 2. PDB结构详情（含文献）
        if pdb_data and pdb_data.get('structures'):
            structures = pdb_data['structures']
            pdb_list = []
            total_citations = 0

            for struct in structures:
                pdb_id = struct.get('pdb_id', 'N/A')
                basic = struct.get('basic_info', {})
                citations = struct.get('citations', [])
                total_citations += len(citations)

                resolution = basic.get('resolution')
                resolution_str = f"{resolution:.2f} Å" if resolution else 'N/A'

                pdb_info = f"""
### 📊 {pdb_id}

| 属性 | 值 |
|------|-----|
| 实验方法 | {basic.get('experimental_method', 'N/A')} |
| 分辨率 | {resolution_str} |
| 沉积日期 | {basic.get('deposition_date', 'N/A')} |
| 标题 | {basic.get('title', 'N/A')[:150]} |
"""
                # 添加文献信息
                if citations:
                    pdb_info += "\n**相关文献**:\n"
                    for i, cit in enumerate(citations[:3], 1):
                        authors = ', '.join(cit.get('authors', [])[:3]) if cit.get('authors') else 'Unknown'
                        year = cit.get('year', 'N/A')
                        journal = cit.get('journal', 'N/A')
                        title = cit.get('title', 'N/A')[:80]
                        doi = cit.get('doi', '')
                        pubmed_id = cit.get('pubmed_id', '')
                        pmid_link = f" [PMID: {pubmed_id}]" if pubmed_id else ""
                        doi_link = f" [DOI: {doi}]" if doi else ""
                        pdb_info += f"{i}. {authors} ({year}). {title}... - {journal}{pmid_link}{doi_link}\n"

                pdb_list.append(pdb_info)

            # 统计实验方法
            methods = {}
            resolutions = []
            for struct in structures:
                method = struct.get('basic_info', {}).get('experimental_method', 'Unknown')
                methods[method] = methods.get(method, 0) + 1
                res = struct.get('basic_info', {}).get('resolution')
                if res:
                    resolutions.append(res)

            method_stats = "\n".join([f"- {method}: {count}个" for method, count in methods.items()])
            res_range = f"{min(resolutions):.2f} - {max(resolutions):.2f} Å" if resolutions else "N/A"
            res_avg = f"{sum(resolutions)/len(resolutions):.2f} Å" if resolutions else "N/A"

            parts.append(f"""
# PDB结构详情

共检索到 **{len(structures)}** 个PDB结构，关联 **{total_citations}** 篇文献。

## 结构统计

{method_stats}
- 分辨率范围: {res_range}
- 平均分辨率: {res_avg}

## 详细结构信息
{chr(10).join(pdb_list)}
""")

        # 3. 相似蛋白（BLAST结果）
        if blast_results and blast_results.get('results'):
            blast_list = []
            for result in blast_results['results'][:10]:
                blast_list.append(f"| {result.get('uniprot_id')} | {result.get('protein_name', 'N/A')} | {result.get('organism', 'N/A')} |")

            parts.append(f"""
# 同源蛋白分析 (BLAST搜索)

共找到 **{len(blast_results['results'])}** 个相似蛋白：

| UniProt ID | 蛋白质名称 | 物种 |
|------------|------------|------|
{chr(10).join(blast_list)}

请分析这些相似蛋白与目标蛋白的关系，讨论序列相似度和功能保守性。
""")
        else:
            parts.append("""
# 同源蛋白分析

未找到显著相似的蛋白，或BLAST搜索未返回结果。
""")

        # 添加详细分析要求
        parts.append("""
## 4. 深入分析要求

请对以下每个方面进行**详细深入**的分析（每个部分至少500字）：

### 4.1 蛋白质功能与生物学意义
- 详细解读蛋白质功能
- 在细胞中的作用通路
- 与疾病的关系（如果有）

### 4.2 结构特征与功能关联
- 分析PDB结构的域分布
- 活性位点/结合位点分析
- 结构与功能的关系

### 4.3 实验方法与数据质量评估
- 分析不同实验方法的优缺点
- 分辨率对结构解析的影响
- 哪些结构适合用于具体研究目的

### 4.4 文献分析与发展历程
- 主要文献的研究发现
- 结构解析的历史进展
- 当前研究热点

### 4.5 与同源蛋白的比较
- 序列和结构保守性分析
- 功能差异讨论
- 进化关系

### 4.6 研究建议与应用前景
- 推荐研究的结构
- 潜在的研究方向
- 药物设计相关建议

请生成一份**4000字以上**的全面分析报告。
""")

        return "\n".join(parts)

    def _generate_report(self, uniprot_data: Dict, pdb_data: Dict, blast_results: Dict, ai_analysis: Dict) -> str:
        """生成评估报告"""
        sections = []

        sections.append("# 蛋白质评估报告\n")

        # 基本信息
        sections.append("## 1. 基本信息\n")
        if uniprot_data:
            sections.append(f"**UniProt ID**: {uniprot_data.get('uniprot_id', 'N/A')}\n")
            sections.append(f"**蛋白质名称**: {uniprot_data.get('protein_name', 'N/A')}\n")
            sections.append(f"**基因名**: {', '.join(uniprot_data.get('gene_names', []))}\n")
            sections.append(f"**物种**: {uniprot_data.get('organism', 'N/A')}\n")
            sections.append(f"**序列长度**: {uniprot_data.get('sequence', 'N/A')} aa\n")
            if uniprot_data.get('function'):
                sections.append(f"**功能描述**: {uniprot_data.get('function')}\n")
        else:
            sections.append("未获取到UniProt数据\n")

        # 结构信息
        sections.append("\n## 2. 结构信息\n")
        if pdb_data and pdb_data.get('structures'):
            for struct in pdb_data['structures']:
                pdb_id = struct.get('pdb_id', 'N/A')
                basic = struct.get('basic_info', {})
                sections.append(f"### {pdb_id}\n")
                sections.append(f"- 实验方法: {basic.get('experimental_method', 'N/A')}\n")
                sections.append(f"- 分辨率: {basic.get('resolution', 'N/A')} Å\n")
                sections.append(f"- 沉积日期: {basic.get('deposition_date', 'N/A')}\n")
        else:
            sections.append("未获取到PDB结构数据\n")

        # 相似蛋白
        sections.append("\n## 3. 相似蛋白 (BLAST)\n")
        if blast_results and blast_results.get('results'):
            sections.append("| UniProt ID | 蛋白质名称 | 物种 |\n")
            sections.append("|------------|------------|------|\n")
            for result in blast_results['results'][:10]:
                sections.append(f"| {result.get('uniprot_id')} | {result.get('protein_name', 'N/A')} | {result.get('organism', 'N/A')} |\n")
        else:
            sections.append("未获取到相似蛋白数据\n")

        # AI分析
        sections.append("\n## 4. AI分析\n")
        if ai_analysis and ai_analysis.get('analysis'):
            sections.append(ai_analysis['analysis'])
        elif ai_analysis and ai_analysis.get('error'):
            sections.append(f"AI分析失败: {ai_analysis['error']}")
        else:
            sections.append("未进行AI分析\n")

        return "".join(sections)

    def _save_to_rag(self, evaluation_id: int, uniprot_data: Dict, pdb_data: Dict, blast_results: Dict, ai_analysis: Dict, report: str):
        """保存到RAG系统（包含所有评估数据）"""
        if not HAS_RAG:
            logger.info("RAG模块未启用，跳过向量存储")
            return

        try:
            rag = get_unified_rag()
            if not uniprot_data:
                return

            # 构建完整的文档内容用于搜索
            content_parts = []

            # 基本信息
            content_parts.append(f"UniProt ID: {uniprot_data.get('uniprot_id', '')}")
            content_parts.append(f"蛋白质名称: {uniprot_data.get('protein_name', '')}")
            content_parts.append(f"基因名: {', '.join(uniprot_data.get('gene_names', []))}")
            content_parts.append(f"物种: {uniprot_data.get('organism', '')}")
            content_parts.append(f"功能: {uniprot_data.get('function', '')}")
            content_parts.append(f"序列长度: {uniprot_data.get('sequence', '')} aa")

            # PDB结构信息
            if pdb_data and pdb_data.get('structures'):
                content_parts.append(f"\nPDB结构数量: {len(pdb_data['structures'])}")
                for struct in pdb_data['structures'][:10]:  # 取前10个
                    pdb_id = struct.get('pdb_id')
                    basic = struct.get('basic_info', {})
                    method = basic.get('experimental_method', '')
                    resolution = basic.get('resolution', '')
                    content_parts.append(f"  {pdb_id}: {method}, 分辨率 {resolution} Å" if resolution else f"  {pdb_id}: {method}")

                    # 添加文献信息（包含摘要）
                    for cit in struct.get('citations', [])[:3]:
                        title = cit.get('title', '')
                        abstract = cit.get('abstract', '')
                        if title:
                            content_parts.append(f"    文献: {title}")
                        if abstract:
                            # 截取摘要前500字符
                            content_parts.append(f"    摘要: {abstract[:500]}...")

            # 相似蛋白
            if blast_results and blast_results.get('results'):
                content_parts.append(f"\n相似蛋白: {len(blast_results['results'])}个")
                for r in blast_results['results'][:5]:
                    content_parts.append(f"  {r.get('uniprot_id')}: {r.get('protein_name', '')} ({r.get('organism', '')})")

            # AI分析
            if ai_analysis and ai_analysis.get('analysis'):
                content_parts.append(f"\nAI分析:\n{ai_analysis['analysis']}")

            # 完整报告
            if report:
                content_parts.append(f"\n完整报告:\n{report}")

            content = "\n".join(content_parts)

            # 创建评估文档
            doc = {
                'id': str(evaluation_id),
                'type': 'protein_evaluation',
                'entity_type': 'protein_evaluation',
                'uniprot_id': uniprot_data.get('uniprot_id', ''),
                'title': f"{uniprot_data.get('uniprot_id', '')} - {uniprot_data.get('protein_name', '')}",
                'text': content,
                'keywords': uniprot_data.get('keywords', [])[:20],
                'methods': ', '.join([s.get('basic_info', {}).get('experimental_method', '') for s in pdb_data.get('structures', [])[:5]]) if pdb_data else ''
            }

            # 存储到RAG（使用literature表）
            rag.add_literature([doc])
            logger.info(f"评估已保存到RAG: ID={evaluation_id}")

        except Exception as e:
            logger.warning(f"保存到RAG失败: {e}")

    def get_evaluation_status(self, evaluation_id: int) -> Dict[str, Any]:
        """获取评估状态"""
        evaluation = get_protein_evaluation(evaluation_id)
        if not evaluation:
            return {'success': False, 'error': '评估记录不存在'}

        return {
            'success': True,
            'evaluation': evaluation.to_dict()
        }

    def list_evaluations(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """列出所有评估"""
        evaluations = get_all_protein_evaluations(limit, offset)
        return {
            'success': True,
            'evaluations': [e.to_dict() for e in evaluations],
            'total': len(evaluations)
        }

    def delete_evaluation(self, evaluation_id: int) -> Dict[str, Any]:
        """删除评估"""
        success = delete_protein_evaluation(evaluation_id)
        return {'success': success}

    def search_evaluations(self, query: str) -> Dict[str, Any]:
        """搜索评估"""
        evaluations = search_protein_evaluations(query)
        return {
            'success': True,
            'evaluations': [e.to_dict() for e in evaluations]
        }


# 全局实例
_evaluation_service = None

def get_evaluation_service() -> ProteinEvaluationService:
    """获取评估服务实例"""
    global _evaluation_service
    if _evaluation_service is None:
        _evaluation_service = ProteinEvaluationService()
    return _evaluation_service


# ========== 测试函数 ==========
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    service = get_evaluation_service()

    # 测试：启动一个评估任务
    print("测试启动评估任务...")
    result = service.start_evaluation("P04637")  # p53
    print(f"结果: {result}")

    # 等待几秒后检查状态
    time.sleep(2)
    if result.get('success'):
        eval_id = result.get('evaluation_id')
        status = service.get_evaluation_status(eval_id)
        print(f"状态: {status}")
