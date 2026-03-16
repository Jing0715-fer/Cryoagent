# bm25.py - BM25 全文索引
"""
BM25 全文索引模块

支持中文分词和 BM25 评分计算
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import math
from collections import Counter, defaultdict
import re

logger = logging.getLogger(__name__)

# 尝试导入 jieba 用于中文分词
try:
    import jieba
    jieba.setLogLevel(jieba.logging.INFO)
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False
    logger.warning("jieba 未安装，中文分词将不可用")


# ============= BM25 参数配置 =============

@dataclass
class BM25Config:
    """BM25 配置参数"""
    k1: float = 1.5  # 词频饱和参数
    b: float = 0.75  # 文档长度归一化参数
    delta: float = 1.0  # 文档加分项
    min_term_length: int = 2  # 最小词长度
    stopwords: Optional[set] = None  # 停用词集合
    boosted_terms: Optional[Dict[str, float]] = None  # 加权关键词 {term: weight}


# 默认停用词
DEFAULT_STOPWORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
    'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'or', 'that',
    'the', 'to', 'was', 'were', 'will', 'with', 'the', 'this', 'these',
    'those', 'but', 'not', 'no', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did',
    'doing', 'would', 'should', 'could', 'may', 'might', 'must',
    # 中文停用词
    '的', '了', '和', '是', '在', '有', '我', '你', '他', '她', '它',
    '们', '这', '那', '都', '也', '就', '要', '会', '可以', '能',
}

# 方法关键词加权配置
METHOD_KEYWORD_WEIGHTS = {
    # 英文方法关键词
    'purification': 2.5,
    'purified': 2.5,
    'expression': 2.5,
    'expressed': 2.5,
    'protocol': 2.0,
    'procedure': 2.0,
    'buffer': 2.0,
    'detergent': 2.5,
    'chromatography': 2.5,
    'column': 2.0,
    'resin': 2.0,
    'elution': 2.0,
    'solubilization': 2.5,
    'solubilized': 2.5,
    'reconstitution': 2.0,
    'reconstituted': 2.0,
    'concentration': 1.8,
    'concentrated': 1.8,
    'dilution': 1.5,
    'diluted': 1.5,
    'incubation': 1.8,
    'incubated': 1.8,
    'centrifugation': 2.0,
    'centrifuged': 2.0,
    'extraction': 2.0,
    'extracted': 2.0,
    'isolation': 2.0,
    'isolated': 2.0,
    'preparation': 2.0,
    'prepared': 2.0,
    'step': 1.5,
    'steps': 1.5,
    'method': 2.0,
    'methods': 2.0,
    'technique': 1.8,
    'condition': 1.5,
    'conditions': 1.5,
    'temperature': 1.8,
    'ph': 2.0,
    'tris': 2.0,
    'hepes': 2.0,
    'pbs': 2.0,
    'nacl': 1.8,
    'kcl': 1.8,
    'mgcl2': 1.8,
    'cacl2': 1.8,
    'edta': 1.8,
    'dtt': 1.8,
    'glycerol': 1.8,
    'dm': 2.0,  # dodecyl maltoside
    'ddm': 2.0,
    'lmng': 2.0,
    'chaps': 2.0,
    'digitonin': 2.0,
    'og': 2.0,  # octyl glucoside
    'hr': 1.5,  # hours
    'min': 1.5,  # minutes
    'sec': 1.5,  # seconds
    'nm': 1.5,  # nanometer
    'mm': 1.5,  # millimolar
    'μm': 1.5,  # micromolar
    'ml': 1.5,
    'μl': 1.5,
    # 中文方法关键词
    '纯化': 2.5,
    '表达': 2.5,
    '缓冲液': 2.0,
    '去垢剂': 2.5,
    '层析': 2.5,
    '色谱': 2.5,
    '柱子': 2.0,
    '树脂': 2.0,
    '洗脱': 2.0,
    '增溶': 2.5,
    '复溶': 2.0,
    '浓缩': 1.8,
    '稀释': 1.5,
    '孵育': 1.8,
    '离心': 2.0,
    '提取': 2.0,
    '分离': 2.0,
    '制备': 2.0,
    '步骤': 1.5,
    '方法': 2.0,
    '技术': 1.8,
    '条件': 1.5,
    '温度': 1.8,
}


def get_method_boosted_config() -> BM25Config:
    """获取方法查询的BM25配置（带关键词加权）"""
    return BM25Config(
        stopwords=DEFAULT_STOPWORDS.copy(),
        boosted_terms=METHOD_KEYWORD_WEIGHTS.copy()
    )


class BM25Index:
    """
    BM25 全文索引

    实现 BM25 算法用于文档检索
    支持中文分词和多种配置选项
    """

    def __init__(
        self,
        config: Optional[BM25Config] = None,
        language: str = "en",
        tokenize: bool = True,
    ):
        """
        初始化 BM25 索引

        Args:
            config: BM25 配置参数
            language: 语言 (en, zh, mixed)
            tokenize: 是否进行分词
        """
        self.config = config or BM25Config(
            stopwords=DEFAULT_STOPWORDS.copy()
        )
        self.language = language
        self.tokenize = tokenize

        # 索引数据
        self.doc_count = 0
        self.avgdl = 0  # 平均文档长度
        self.doc_lengths: Dict[int, int] = {}  # doc_id -> 文档长度
        self.doc_freqs: Dict[str, int] = {}  # term -> 文档频率
        self.idf: Dict[str, float] = {}  # term -> IDF 分数
        self.doc_term_freqs: Dict[int, Dict[str, int]] = {}  # doc_id -> {term: freq}
        self.documents: Dict[int, str] = {}  # doc_id -> 原始文档

    def tokenize_text(
        self,
        text: str,
        language: Optional[str] = None
    ) -> List[str]:
        """
        分词

        Args:
            text: 文本
            language: 语言 (覆盖实例语言)

        Returns:
            分词列表
        """
        if not text:
            return []

        language = language or self.language

        # 转小写
        text = text.lower()

        # 移除特殊字符
        text = re.sub(r'[^\w\s]', ' ', text)

        # 分词
        if language == "zh" or (language == "mixed" and self._contains_chinese(text)):
            if JIEBA_AVAILABLE:
                tokens = list(jieba.cut(text))
            else:
                tokens = text.split()
        else:
            tokens = text.split()

        # 过滤停用词和短词
        tokens = [
            t for t in tokens
            if len(t) >= self.config.min_term_length
            and (not self.config.stopwords or t not in self.config.stopwords)
        ]

        return tokens

    @staticmethod
    def _contains_chinese(text: str) -> bool:
        """检查是否包含中文"""
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    def index_documents(
        self,
        documents: List[Dict[str, Any]],
        text_field: str = "text",
        id_field: str = "id"
    ) -> "BM25Index":
        """
        索引文档

        Args:
            documents: 文档列表
            text_field: 文本字段名
            id_field: ID 字段名

        Returns:
            self
        """
        if not documents:
            return self

        # 重置索引
        self.doc_count = 0
        self.doc_lengths = {}
        self.doc_freqs = defaultdict(int)
        self.doc_term_freqs = {}
        self.documents = {}

        # 统计信息
        total_length = 0

        for doc in documents:
            doc_id = self.doc_count

            # 获取文本
            text = doc.get(text_field, "")
            self.documents[doc_id] = text

            # 分词
            tokens = self.tokenize_text(text)

            # 文档长度
            doc_length = len(tokens)
            self.doc_lengths[doc_id] = doc_length
            total_length += doc_length

            # 词频
            term_freqs = Counter(tokens)
            self.doc_term_freqs[doc_id] = dict(term_freqs)

            # 文档频率
            for term in term_freqs:
                self.doc_freqs[term] += 1

            self.doc_count += 1

        # 计算平均文档长度
        self.avgdl = total_length / self.doc_count if self.doc_count > 0 else 0

        # 计算 IDF
        self._compute_idf()

        logger.info(f"已索引 {self.doc_count} 个文档，平均长度: {self.avgdl:.2f}")

        return self

    def _compute_idf(self):
        """计算 IDF 值"""
        self.idf = {}
        for term, df in self.doc_freqs.items():
            # BM25 IDF 公式
            self.idf[term] = math.log(
                (self.doc_count - df + 0.5) / (df + 0.5) + 1
            )

    def get_scores(self, query: str, boosted_terms: Optional[Dict[str, float]] = None) -> List[float]:
        """
        获取查询对所有文档的 BM25 分数

        Args:
            query: 查询文本
            boosted_terms: 可选的加权词字典 {term: weight}

        Returns:
            每个文档的分数列表
        """
        if self.doc_count == 0:
            return []

        query_terms = self.tokenize_text(query)
        if not query_terms:
            return [0.0] * self.doc_count

        scores = [0.0] * self.doc_count

        # 合并配置中的加权词和传入的加权词
        term_boosts = {}
        if self.config.boosted_terms:
            term_boosts.update(self.config.boosted_terms)
        if boosted_terms:
            term_boosts.update(boosted_terms)

        for doc_id in range(self.doc_count):
            score = 0.0
            doc_len = self.doc_lengths.get(doc_id, 0)
            term_freqs = self.doc_term_freqs.get(doc_id, {})

            for term in query_terms:
                if term not in term_freqs:
                    continue

                tf = term_freqs[term]
                idf = self.idf.get(term, 0)

                # BM25 评分公式
                numerator = tf * (self.config.k1 + 1)
                denominator = tf + self.config.k1 * (
                    1 - self.config.b + self.config.b * doc_len / self.avgdl
                )

                term_score = idf * numerator / denominator

                # 应用加权
                boost = term_boosts.get(term, 1.0)
                score += term_score * boost

            scores[doc_id] = score

        return scores

    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
        boosted_terms: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索文档

        Args:
            query: 查询文本
            top_k: 返回结果数量
            min_score: 最小分数阈值
            boosted_terms: 可选的加权词字典

        Returns:
            搜索结果列表
        """
        if self.doc_count == 0:
            return []

        scores = self.get_scores(query, boosted_terms=boosted_terms)

        # 排序
        results = [
            {"doc_id": i, "score": score}
            for i, score in enumerate(scores)
            if score > min_score
        ]
        results.sort(key=lambda x: x["score"], reverse=True)

        # 返回 top_k
        return results[:top_k]

    def search_with_documents(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        text_field: str = "text",
        id_field: str = "id",
        top_k: int = 10,
        min_score: float = 0.0,
        boosted_terms: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索文档（带文档内容）

        Args:
            query: 查询文本
            documents: 文档列表
            text_field: 文本字段名
            id_field: ID 字段名
            top_k: 返回结果数量
            min_score: 最小分数阈值
            boosted_terms: 可选的加权词字典

        Returns:
            带文档内容的搜索结果
        """
        if not documents:
            return []

        # 确保索引是最新的
        if self.doc_count != len(documents):
            self.index_documents(documents, text_field, id_field)

        scores = self.get_scores(query, boosted_terms=boosted_terms)

        # 构建结果
        results = []
        for i, score in enumerate(scores):
            if score > min_score:
                doc = documents[i].copy()
                doc["bm25_score"] = score
                doc["doc_id"] = i
                results.append(doc)

        # 排序
        results.sort(key=lambda x: x["bm25_score"], reverse=True)

        return results[:top_k]

    def get_doc_terms(self, doc_id: int) -> Dict[str, int]:
        """获取文档的词频"""
        return self.doc_term_freqs.get(doc_id, {})

    def get_term_idf(self, term: str) -> float:
        """获取词的 IDF 值"""
        return self.idf.get(term, 0.0)

    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        return {
            "doc_count": self.doc_count,
            "avgdl": self.avgdl,
            "vocab_size": len(self.doc_freqs),
            "total_terms": sum(self.doc_lengths.values()),
        }


# ============= BM25 融合器 =============

class BM25Fusion:
    """
    BM25 融合器

    用于将多个 BM25 索引的结果进行融合
    """

    @staticmethod
    def reciprocal_rank_fusion(
        results_list: List[List[Dict[str, Any]]],
        k: int = 60
    ) -> List[Dict[str, Any]]:
        """
        倒数排名融合 (RRF)

        Args:
            results_list: 多个搜索结果列表
            k: RRF 参数

        Returns:
            融合后的结果
        """
        scores = defaultdict(float)
        doc_map: Dict[int, Any] = {}

        for results in results_list:
            for rank, result in enumerate(results):
                doc_id = result.get("doc_id")
                if doc_id is None:
                    continue

                # 累加 RRF 分数
                scores[doc_id] += 1.0 / (k + rank + 1)

                # 保存文档映射
                if doc_id not in doc_map:
                    doc_map[doc_id] = result

        # 排序
        fused = [
            {**doc_map[doc_id], "rrf_score": score}
            for doc_id, score in scores.items()
        ]
        fused.sort(key=lambda x: x["rrf_score"], reverse=True)

        return fused

    @staticmethod
    def weighted_fusion(
        results_list: List[List[Dict[str, Any]]],
        weights: Optional[List[float]] = None,
        score_field: str = "score"
    ) -> List[Dict[str, Any]]:
        """
        加权融合

        Args:
            results_list: 多个搜索结果列表
            weights: 权重列表
            score_field: 分数字段名

        Returns:
            融合后的结果
        """
        if weights is None:
            weights = [1.0] * len(results_list)

        # 归一化权重
        total_weight = sum(weights)
        weights = [w / total_weight for w in weights]

        scores = defaultdict(float)
        doc_map: Dict[int, Any] = {}

        for results, weight in zip(results_list, weights):
            for result in results:
                doc_id = result.get("doc_id")
                if doc_id is None:
                    continue

                # 归一化分数
                score = result.get(score_field, 0)

                # 找到每个列表的最大分数用于归一化
                max_score = max(r.get(score_field, 0) for r in results) or 1

                # 累加加权分数
                normalized = score / max_score if max_score > 0 else 0
                scores[doc_id] += normalized * weight

                # 保存文档映射
                if doc_id not in doc_map:
                    doc_map[doc_id] = result

        # 排序
        fused = [
            {**doc_map[doc_id], "weighted_score": score}
            for doc_id, score in scores.items()
        ]
        fused.sort(key=lambda x: x["weighted_score"], reverse=True)

        return fused


# ============= 便捷函数 =============

def create_bm25_index(
    documents: List[Dict[str, Any]],
    text_field: str = "text",
    id_field: str = "id",
    language: str = "mixed",
    **kwargs
) -> BM25Index:
    """
    创建 BM25 索引的便捷函数

    Args:
        documents: 文档列表
        text_field: 文本字段名
        id_field: ID 字段名
        language: 语言
        **kwargs: 其他 BM25Config 参数

    Returns:
        BM25Index 实例
    """
    config = BM25Config(**kwargs)
    index = BM25Index(config=config, language=language)
    index.index_documents(documents, text_field, id_field)
    return index
