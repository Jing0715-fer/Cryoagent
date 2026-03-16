# monitor.py - 在线监控
"""
RAG 检索在线监控模块

提供实时监控功能：
- 搜索日志记录
- 性能指标跟踪
- 异常检测
- 统计报表
"""

import time
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import threading

from .storage import EvaluationStorage

logger = logging.getLogger(__name__)


@dataclass
class SearchLog:
    """搜索日志条目"""

    query_text: str
    num_results: int
    latency_ms: float
    search_type: str = "vector"
    session_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # 可选的详细信息
    top_results: Optional[List[str]] = None
    error: Optional[str] = None


class SearchMonitor:
    """搜索监控器"""

    def __init__(
        self,
        storage: Optional[EvaluationStorage] = None,
        window_size: int = 1000,
    ):
        """
        初始化监控器

        Args:
            storage: 存储后端
            window_size: 内存中保留的日志数量
        """
        self.storage = storage
        self.window_size = window_size

        # 内存中的日志队列
        self._logs: deque = deque(maxlen=window_size)
        self._lock = threading.Lock()

        # 统计缓存
        self._stats_cache: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=5)

    def log_search(
        self,
        query_text: str,
        num_results: int,
        latency_ms: float,
        search_type: str = "vector",
        session_id: Optional[str] = None,
        top_results: Optional[List[str]] = None,
        error: Optional[str] = None,
    ) -> SearchLog:
        """
        记录搜索日志

        Args:
            query_text: 查询文本
            num_results: 返回结果数量
            latency_ms: 延迟（毫秒）
            search_type: 搜索类型
            session_id: 会话 ID
            top_results: 前 N 个结果的 ID
            error: 错误信息（如果有）

        Returns:
            SearchLog 对象
        """
        log = SearchLog(
            query_text=query_text,
            num_results=num_results,
            latency_ms=latency_ms,
            search_type=search_type,
            session_id=session_id,
            top_results=top_results,
            error=error,
        )

        with self._lock:
            self._logs.append(log)

        # 持久化存储
        if self.storage and not error:
            self.storage.log_search(
                query_text=query_text,
                num_results=num_results,
                latency_ms=latency_ms,
                search_type=search_type,
                session_id=session_id,
            )

        return log

    def get_recent_logs(self, limit: int = 100) -> List[SearchLog]:
        """获取最近的日志"""
        with self._lock:
            return list(self._logs)[-limit:]

    def get_stats(self, use_cache: bool = True) -> Dict[str, Any]:
        """
        获取统计数据

        Args:
            use_cache: 是否使用缓存

        Returns:
            统计数据字典
        """
        # 检查缓存
        if use_cache and self._cache_time:
            if datetime.now() - self._cache_time < self._cache_ttl:
                return self._stats_cache

        with self._lock:
            logs = list(self._logs)

        if not logs:
            return {
                'total_searches': 0,
                'avg_latency_ms': 0,
                'avg_results': 0,
                'error_rate': 0,
            }

        # 计算统计
        total = len(logs)
        latencies = [l.latency_ms for l in logs if l.error is None]
        result_counts = [l.num_results for l in logs]
        error_count = sum(1 for l in logs if l.error)

        # 按搜索类型统计
        by_type: Dict[str, int] = {}
        for log in logs:
            by_type[log.search_type] = by_type.get(log.search_type, 0) + 1

        # P50, P95, P99 延迟
        sorted_latencies = sorted(latencies)
        p50 = self._percentile(sorted_latencies, 50)
        p95 = self._percentile(sorted_latencies, 95)
        p99 = self._percentile(sorted_latencies, 99)

        stats = {
            'total_searches': total,
            'avg_latency_ms': sum(latencies) / len(latencies) if latencies else 0,
            'avg_results': sum(result_counts) / total if total else 0,
            'error_rate': error_count / total if total else 0,
            'latency_p50_ms': p50,
            'latency_p95_ms': p95,
            'latency_p99_ms': p99,
            'by_type': by_type,
            'window_size': self.window_size,
        }

        # 更新缓存
        self._stats_cache = stats
        self._cache_time = datetime.now()

        return stats

    def _percentile(self, sorted_data: List[float], p: int) -> float:
        """计算百分位数"""
        if not sorted_data:
            return 0.0

        k = (len(sorted_data) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_data) else f

        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])

    def get_hourly_stats(self, hours: int = 24) -> List[Dict[str, Any]]:
        """获取每小时统计"""
        with self._lock:
            logs = list(self._logs)

        # 按小时分组
        now = datetime.now()
        hourly_data: Dict[str, List[SearchLog]] = {}

        for h in range(hours):
            hour_start = now - timedelta(hours=h + 1)
            hour_key = hour_start.strftime('%Y-%m-%d %H:00')
            hourly_data[hour_key] = []

        for log in logs:
            try:
                log_time = datetime.fromisoformat(log.timestamp)
                hour_key = log_time.strftime('%Y-%m-%d %H:00')
                if hour_key in hourly_data:
                    hourly_data[hour_key].append(log)
            except:
                continue

        # 计算每小时统计
        result = []
        for hour_key, hour_logs in sorted(hourly.items(), reverse=True):
            if not hour_logs:
                continue

            latencies = [l.latency_ms for l in hour_logs if l.error is None]
            result.append({
                'hour': hour_key,
                'count': len(hour_logs),
                'avg_latency_ms': sum(latencies) / len(latencies) if latencies else 0,
                'errors': sum(1 for l in hour_logs if l.error),
            })

        return result

    def detect_anomalies(self) -> List[Dict[str, Any]]:
        """
        检测异常

        检测类型：
        1. 延迟异常（超过 P99 的 2 倍）
        2. 无结果异常（连续多个查询无结果）
        3. 错误率异常

        Returns:
            异常列表
        """
        anomalies = []
        stats = self.get_stats(use_cache=False)

        # 检查错误率
        if stats['error_rate'] > 0.1:  # 10% 错误率
            anomalies.append({
                'type': 'high_error_rate',
                'value': stats['error_rate'],
                'threshold': 0.1,
                'message': f"错误率过高: {stats['error_rate']:.1%}",
            })

        # 检查延迟
        if stats['latency_p99_ms'] > 5000:  # 5 秒
            anomalies.append({
                'type': 'high_latency',
                'value': stats['latency_p99_ms'],
                'threshold': 5000,
                'message': f"P99 延迟过高: {stats['latency_p99_ms']:.0f}ms",
            })

        # 检查无结果查询
        with self._lock:
            recent = list(self._logs)[-10:]

        zero_result_count = sum(1 for l in recent if l.num_results == 0 and l.error is None)
        if zero_result_count >= 5:
            anomalies.append({
                'type': 'zero_results',
                'value': zero_result_count,
                'threshold': 5,
                'message': f"连续 {zero_result_count} 个查询无结果",
            })

        return anomalies

    def get_popular_queries(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取热门查询"""
        with self._lock:
            logs = list(self._logs)

        # 统计查询频率
        query_counts: Dict[str, int] = {}
        for log in logs:
            # 简化查询（去除空格，转小写）
            simplified = log.query_text.strip().lower()[:100]
            query_counts[simplified] = query_counts.get(simplified, 0) + 1

        # 排序
        popular = sorted(query_counts.items(), key=lambda x: x[1], reverse=True)[:limit]

        return [
            {'query': q, 'count': c}
            for q, c in popular
        ]

    def clear_logs(self):
        """清空日志"""
        with self._lock:
            self._logs.clear()
        self._stats_cache = {}
        self._cache_time = None


# 全局监控实例
_monitor_instance: Optional[SearchMonitor] = None


def get_search_monitor(storage: Optional[EvaluationStorage] = None) -> SearchMonitor:
    """获取全局监控实例"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = SearchMonitor(storage=storage)
    return _monitor_instance


def reset_search_monitor():
    """重置监控实例"""
    global _monitor_instance
    _monitor_instance = None