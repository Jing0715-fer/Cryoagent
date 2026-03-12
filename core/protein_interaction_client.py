# protein_interaction_client.py - String Database API 客户端
"""
蛋白相互作用数据获取 - 使用 String Database API
功能：
1. 获取蛋白质相互作用网络
2. 查询蛋白质的已知相互作用
"""

import logging
import requests
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class StringDBClient:
    """String Database API 客户端"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.base_url = "https://string-db.org/api/json"
        # 创建不使用代理的session
        self.session = requests.Session()
        self.session.trust_env = False

    def get_interactions(self, uniprot_ids: List[str], species: int = 9606, limit: int = 10) -> Dict[str, Any]:
        """
        获取蛋白质相互作用数据

        参数:
            uniprot_ids: UniProt ID 列表
            species: 物种ID (9606 = human)
            limit: 每个蛋白返回的最大相互作用数

        返回:
            相互作用数据字典
        """
        all_interactions = []

        try:
            # 首先尝试批量查询
            params = {
                'species': species,
                'limit': limit,
                'proteins': ','.join(uniprot_ids)
            }

            response = self.session.get(
                f"{self.base_url}/interaction_partners",
                params=params,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                all_interactions = self._parse_interactions(data, uniprot_ids)
            else:
                logger.warning(f"String API 批量查询失败 (HTTP {response.status_code}), 尝试单独查询")

                # 单独查询每个蛋白
                all_interactions = self._fetch_individual_interactions(uniprot_ids, species, limit)

            return {
                'interactions': all_interactions,
                'source': 'string_db'
            }

        except Exception as e:
            logger.error(f"获取蛋白相互作用数据失败: {e}")
            return {'interactions': [], 'source': 'string_db', 'error': str(e)}

    def _parse_interactions(self, data: List[Dict], target_uniprot_ids: List[str]) -> List[Dict]:
        """解析相互作用数据"""
        interactions = []
        target_set = set(u.upper() for u in target_uniprot_ids)

        for item in data:
            protein_b_id = item.get('stringdb_B', '')
            if protein_b_id.upper() in target_set:
                interaction = {
                    'protein_a': item.get('stringdb_A', ''),
                    'protein_b': protein_b_id,
                    'protein_b_name': item.get('preferredName_B', {}).get('geneName', ''),
                    'protein_b_full_name': item.get('preferredName_B', {}).get('proteinName', ''),
                    'score': item.get('score', 0),
                    'type': item.get('interaction_type', 'unknown')
                }
                interactions.append(interaction)

        return interactions

    def _fetch_individual_interactions(self, uniprot_ids: List[str], species: int, limit: int) -> List[Dict]:
        """单独查询每个蛋白的相互作用"""
        all_interactions = []

        for uniprot_id in uniprot_ids:
            try:
                # 先通过UniProt获取基因名
                uniprot_data = self._get_gene_name_from_uniprot(uniprot_id)
                if not uniprot_data:
                    continue

                gene_name = uniprot_data.get('gene_name')
                if not gene_name:
                    continue

                # 使用基因名查询String
                params = {
                    'species': species,
                    'limit': limit,
                    'proteins': gene_name
                }

                response = self.session.get(
                    f"{self.base_url}/interaction_partners",
                    params=params,
                    timeout=self.timeout
                )

                if response.status_code == 200:
                    data = response.json()
                    interactions = self._parse_single_protein_interactions(data, uniprot_id, uniprot_ids)
                    all_interactions.extend(interactions)

            except Exception as e:
                logger.warning(f"查询蛋白 {uniprot_id} 相互作用失败: {e}")
                continue

        return all_interactions

    def _parse_single_protein_interactions(self, data: List[Dict], query_uniprot_id: str,
                                          target_uniprot_ids: List[str]) -> List[Dict]:
        """解析单个蛋白的相互作用数据"""
        interactions = []
        target_set = set(u.upper() for u in target_uniprot_ids)

        for item in data:
            protein_b_id = item.get('stringdb_B', '')
            if protein_b_id.upper() in target_set:
                interaction = {
                    'protein_a': query_uniprot_id,
                    'protein_b': protein_b_id,
                    'protein_b_name': item.get('preferredName_B', {}).get('geneName', ''),
                    'protein_b_full_name': item.get('preferredName_B', {}).get('proteinName', ''),
                    'score': item.get('score', 0),
                    'type': item.get('interaction_type', 'unknown')
                }
                interactions.append(interaction)

        return interactions

    def _get_gene_name_from_uniprot(self, uniprot_id: str) -> Optional[Dict]:
        """从UniProt获取基因名"""
        try:
            url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}"
            response = self.session.get(url, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                genes = data.get('genes', [])
                if genes:
                    gene_name = genes[0].get('geneName', {}).get('value', '')
                    return {'gene_name': gene_name}
            return None
        except Exception as e:
            logger.warning(f"从UniProt获取基因名失败 {uniprot_id}: {e}")
            return None

    def get_protein_network(self, uniprot_id: str, species: int = 9606) -> Dict[str, Any]:
        """
        获取单个蛋白的完整相互作用网络

        参数:
            uniprot_id: UniProt ID
            species: 物种ID

        返回:
            相互作用网络数据
        """
        try:
            uniprot_data = self._get_gene_name_from_uniprot(uniprot_id)
            if not uniprot_data:
                return {'success': False, 'error': '无法获取基因名'}

            gene_name = uniprot_data['gene_name']

            params = {
                'species': species,
                'proteins': gene_name
            }

            response = self.session.get(
                f"{self.base_url}/interaction_partners",
                params=params,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'query_protein': uniprot_id,
                    'gene_name': gene_name,
                    'interactions': data
                }
            else:
                return {'success': False, 'error': f'HTTP {response.status_code}'}

        except Exception as e:
            logger.error(f"获取蛋白网络失败: {e}")
            return {'success': False, 'error': str(e)}

    def get_functional_enrichment(self, uniprot_ids: List[str], species: int = 9606) -> Dict[str, Any]:
        """
        获取蛋白质组的功能富集分析

        参数:
            uniprot_ids: UniProt ID 列表
            species: 物种ID

        返回:
            功能富集数据
        """
        try:
            # 首先获取所有基因名
            gene_names = []
            for uniprot_id in uniprot_ids:
                uniprot_data = self._get_gene_name_from_uniprot(uniprot_id)
                if uniprot_data and uniprot_data.get('gene_name'):
                    gene_names.append(uniprot_data['gene_name'])

            if not gene_names:
                return {'success': False, 'error': '无法获取基因名'}

            params = {
                'species': species,
                'proteins': ','.join(gene_names)
            }

            response = self.session.get(
                f"{self.base_url}/enrichment",
                params=params,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'enrichment': data
                }
            else:
                return {'success': False, 'error': f'HTTP {response.status_code}'}

        except Exception as e:
            logger.error(f"获取功能富集失败: {e}")
            return {'success': False, 'error': str(e)}


# 便捷函数
def get_protein_interactions(uniprot_ids: List[str], species: int = 9606) -> Dict[str, Any]:
    """获取蛋白质相互作用（便捷函数）"""
    client = StringDBClient()
    return client.get_interactions(uniprot_ids, species)


def get_protein_network(uniprot_id: str, species: int = 9606) -> Dict[str, Any]:
    """获取蛋白质网络（便捷函数）"""
    client = StringDBClient()
    return client.get_protein_network(uniprot_id, species)