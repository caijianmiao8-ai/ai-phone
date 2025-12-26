"""
任务执行分析器
分析任务执行历史，生成总结报告和改进建议
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from openai import OpenAI

from core.task_history import TaskHistoryManager, TaskExecutionRecord, TaskStatistics


@dataclass
class AnalysisResult:
    """分析结果"""
    summary: str                                    # 总结概述
    success_rate: float                             # 成功率
    average_duration: float                         # 平均耗时
    total_tasks: int                                # 总任务数
    common_issues: List[Dict[str, Any]] = field(default_factory=list)  # 常见问题
    recommendations: List[str] = field(default_factory=list)           # 改进建议
    insights: List[str] = field(default_factory=list)                  # 洞察
    device_performance: Dict[str, Dict] = field(default_factory=dict)  # 设备表现
    time_analysis: Dict[str, Any] = field(default_factory=dict)        # 时间分析

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "success_rate": self.success_rate,
            "average_duration": self.average_duration,
            "total_tasks": self.total_tasks,
            "common_issues": self.common_issues,
            "recommendations": self.recommendations,
            "insights": self.insights,
            "device_performance": self.device_performance,
            "time_analysis": self.time_analysis,
        }

    def to_markdown(self) -> str:
        """转换为Markdown格式"""
        lines = [
            "## 任务执行分析报告",
            "",
            f"**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "### 概述",
            self.summary,
            "",
            "### 统计数据",
            f"- 总任务数: {self.total_tasks}",
            f"- 成功率: {self.success_rate:.1%}",
            f"- 平均耗时: {self.average_duration:.1f} 秒",
            "",
        ]

        if self.common_issues:
            lines.append("### 常见问题")
            for issue in self.common_issues:
                lines.append(f"- **{issue.get('issue', '未知')}** (出现 {issue.get('count', 0)} 次)")
                if issue.get('suggestion'):
                    lines.append(f"  - 建议: {issue['suggestion']}")
            lines.append("")

        if self.recommendations:
            lines.append("### 改进建议")
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        if self.insights:
            lines.append("### 洞察")
            for insight in self.insights:
                lines.append(f"- {insight}")
            lines.append("")

        if self.device_performance:
            lines.append("### 设备表现")
            lines.append("| 设备 | 任务数 | 成功率 | 平均耗时 |")
            lines.append("| --- | --- | --- | --- |")
            for device_id, perf in self.device_performance.items():
                lines.append(
                    f"| {device_id} | {perf.get('count', 0)} | "
                    f"{perf.get('success_rate', 0):.1%} | "
                    f"{perf.get('avg_duration', 0):.1f}s |"
                )
            lines.append("")

        return "\n".join(lines)


class TaskAnalyzer:
    """任务分析器"""

    def __init__(
        self,
        history_manager: TaskHistoryManager,
        api_base: str = None,
        api_key: str = None,
        model: str = "gpt-4o-mini",
    ):
        self.history_manager = history_manager
        self.api_base = api_base
        self.api_key = api_key
        self.model = model

    def update_config(self, api_base: str, api_key: str, model: str):
        """更新API配置"""
        self.api_base = api_base
        self.api_key = api_key
        self.model = model

    def _get_client(self) -> Optional[OpenAI]:
        """获取OpenAI客户端"""
        if not self.api_key:
            return None
        return OpenAI(
            base_url=self.api_base,
            api_key=self.api_key,
        )

    def analyze_basic(
        self,
        device_id: Optional[str] = None,
        time_range_hours: Optional[int] = 24,
    ) -> AnalysisResult:
        """基础分析（不使用AI）"""
        stats = self.history_manager.get_statistics(
            device_id=device_id,
            time_range_hours=time_range_hours,
        )

        records = self.history_manager.get_recent_records(
            limit=100,
            device_id=device_id,
            time_range_hours=time_range_hours,
        )

        # 分析常见问题
        error_analysis = self._analyze_errors(records)

        # 分析设备表现
        device_perf = self._analyze_device_performance(records)

        # 分析时间分布
        time_analysis = self._analyze_time_distribution(records)

        # 生成基础洞察
        insights = self._generate_basic_insights(stats, records)

        # 生成基础建议
        recommendations = self._generate_basic_recommendations(stats, error_analysis)

        # 生成摘要
        summary = self._generate_basic_summary(stats, time_range_hours)

        return AnalysisResult(
            summary=summary,
            success_rate=stats.success_rate,
            average_duration=stats.average_duration,
            total_tasks=stats.total_tasks,
            common_issues=error_analysis,
            recommendations=recommendations,
            insights=insights,
            device_performance=device_perf,
            time_analysis=time_analysis,
        )

    def analyze_with_ai(
        self,
        device_id: Optional[str] = None,
        time_range_hours: Optional[int] = 24,
        task_pattern: Optional[str] = None,
    ) -> AnalysisResult:
        """使用AI进行深度分析"""
        # 先获取基础分析
        basic_result = self.analyze_basic(device_id, time_range_hours)

        client = self._get_client()
        if not client:
            # 无法使用AI，返回基础分析
            basic_result.summary = "[基础分析] " + basic_result.summary
            return basic_result

        # 获取详细记录用于AI分析
        records = self.history_manager.get_recent_records(
            limit=50,
            device_id=device_id,
            time_range_hours=time_range_hours,
        )

        if task_pattern:
            records = [r for r in records if task_pattern.lower() in r.task_description.lower()]

        if not records:
            return basic_result

        # 准备AI分析数据
        analysis_data = self._prepare_analysis_data(records, basic_result)

        # 调用AI生成分析
        try:
            ai_analysis = self._call_ai_analysis(client, analysis_data)
            return self._merge_analysis(basic_result, ai_analysis)
        except Exception as e:
            basic_result.summary = f"[基础分析] {basic_result.summary} (AI分析失败: {str(e)})"
            return basic_result

    def _analyze_errors(self, records: List[TaskExecutionRecord]) -> List[Dict[str, Any]]:
        """分析错误模式"""
        error_counts: Dict[str, int] = {}
        error_examples: Dict[str, str] = {}

        for record in records:
            if not record.success and record.error_message:
                # 简化错误消息
                error_key = self._normalize_error(record.error_message)
                error_counts[error_key] = error_counts.get(error_key, 0) + 1
                if error_key not in error_examples:
                    error_examples[error_key] = record.error_message

        # 按频率排序
        sorted_errors = sorted(error_counts.items(), key=lambda x: -x[1])[:5]

        return [
            {
                "issue": error,
                "count": count,
                "example": error_examples.get(error, ""),
                "suggestion": self._get_error_suggestion(error),
            }
            for error, count in sorted_errors
        ]

    def _normalize_error(self, error: str) -> str:
        """标准化错误消息"""
        # 移除具体数值、ID等，保留错误模式
        error = error[:100]  # 截断

        # 常见模式替换
        patterns = [
            ("timeout", "超时"),
            ("connection", "连接问题"),
            ("device", "设备问题"),
            ("api", "API错误"),
            ("screenshot", "截图失败"),
            ("element not found", "元素未找到"),
        ]

        error_lower = error.lower()
        for pattern, label in patterns:
            if pattern in error_lower:
                return label

        return error[:50]

    def _get_error_suggestion(self, error: str) -> str:
        """获取错误建议"""
        suggestions = {
            "超时": "考虑增加超时时间，或检查设备响应速度",
            "连接问题": "检查设备连接状态，确保ADB连接稳定",
            "设备问题": "重新连接设备，或检查设备是否正常工作",
            "API错误": "检查API配置和网络连接",
            "截图失败": "检查设备屏幕状态，确保屏幕未锁定",
            "元素未找到": "可能需要更新知识库中的操作步骤",
        }
        return suggestions.get(error, "检查任务配置和设备状态")

    def _analyze_device_performance(self, records: List[TaskExecutionRecord]) -> Dict[str, Dict]:
        """分析设备表现"""
        device_stats: Dict[str, Dict] = {}

        for record in records:
            device_id = record.device_id
            if device_id not in device_stats:
                device_stats[device_id] = {
                    "count": 0,
                    "success": 0,
                    "total_duration": 0,
                    "durations": [],
                }

            stats = device_stats[device_id]
            stats["count"] += 1
            if record.success:
                stats["success"] += 1
            if record.duration_seconds > 0:
                stats["total_duration"] += record.duration_seconds
                stats["durations"].append(record.duration_seconds)

        # 计算汇总指标
        result = {}
        for device_id, stats in device_stats.items():
            count = stats["count"]
            result[device_id] = {
                "count": count,
                "success_rate": stats["success"] / count if count > 0 else 0,
                "avg_duration": stats["total_duration"] / len(stats["durations"]) if stats["durations"] else 0,
            }

        return result

    def _analyze_time_distribution(self, records: List[TaskExecutionRecord]) -> Dict[str, Any]:
        """分析时间分布"""
        hourly_counts: Dict[int, int] = {h: 0 for h in range(24)}
        daily_counts: Dict[str, int] = {}

        for record in records:
            try:
                dt = datetime.fromisoformat(record.started_at)
                hourly_counts[dt.hour] += 1
                day = dt.strftime("%Y-%m-%d")
                daily_counts[day] = daily_counts.get(day, 0) + 1
            except Exception:
                pass

        # 找出高峰时段
        peak_hour = max(hourly_counts.items(), key=lambda x: x[1])[0] if hourly_counts else 0

        return {
            "hourly_distribution": hourly_counts,
            "daily_distribution": daily_counts,
            "peak_hour": peak_hour,
            "total_days": len(daily_counts),
        }

    def _generate_basic_insights(
        self,
        stats: TaskStatistics,
        records: List[TaskExecutionRecord],
    ) -> List[str]:
        """生成基础洞察"""
        insights = []

        if stats.success_rate >= 0.9:
            insights.append("任务执行成功率优秀 (≥90%)")
        elif stats.success_rate >= 0.7:
            insights.append("任务执行成功率良好 (70%-90%)")
        elif stats.success_rate >= 0.5:
            insights.append("任务执行成功率一般 (50%-70%)，建议检查常见错误")
        else:
            insights.append("任务执行成功率较低 (<50%)，需要重点关注")

        if stats.average_duration > 120:
            insights.append(f"平均任务耗时较长 ({stats.average_duration:.0f}秒)，可能需要优化")

        if stats.average_steps > 30:
            insights.append("平均执行步数较多，考虑简化任务描述")

        return insights

    def _generate_basic_recommendations(
        self,
        stats: TaskStatistics,
        error_analysis: List[Dict[str, Any]],
    ) -> List[str]:
        """生成基础建议"""
        recommendations = []

        if stats.success_rate < 0.8:
            recommendations.append("建议检查和更新知识库中的操作指南")

        if error_analysis:
            top_error = error_analysis[0]
            if top_error["count"] >= 3:
                recommendations.append(
                    f"重点解决「{top_error['issue']}」问题 (出现{top_error['count']}次)"
                )

        if stats.average_duration > 180:
            recommendations.append("考虑将复杂任务拆分为多个简单步骤")

        if not recommendations:
            recommendations.append("当前执行情况良好，继续保持")

        return recommendations

    def _generate_basic_summary(self, stats: TaskStatistics, time_range_hours: int) -> str:
        """生成基础摘要"""
        period = f"过去{time_range_hours}小时" if time_range_hours else "全部时间"

        if stats.total_tasks == 0:
            return f"{period}内暂无任务执行记录"

        success_desc = "优秀" if stats.success_rate >= 0.9 else "良好" if stats.success_rate >= 0.7 else "一般"

        return (
            f"{period}共执行 {stats.total_tasks} 个任务，"
            f"成功 {stats.successful_tasks} 个，失败 {stats.failed_tasks} 个。"
            f"整体表现{success_desc}，成功率 {stats.success_rate:.1%}，"
            f"平均耗时 {stats.average_duration:.1f} 秒。"
        )

    def _prepare_analysis_data(
        self,
        records: List[TaskExecutionRecord],
        basic_result: AnalysisResult,
    ) -> str:
        """准备AI分析数据"""
        # 选择代表性记录
        sample_records = []
        for record in records[:20]:
            sample_records.append({
                "task": record.task_description[:100],
                "success": record.success,
                "duration": record.duration_seconds,
                "steps": record.steps_executed,
                "error": record.error_message[:100] if record.error_message else None,
                "device": record.device_id,
            })

        return json.dumps({
            "statistics": {
                "total": basic_result.total_tasks,
                "success_rate": basic_result.success_rate,
                "avg_duration": basic_result.average_duration,
            },
            "common_issues": basic_result.common_issues,
            "device_performance": basic_result.device_performance,
            "sample_records": sample_records,
        }, ensure_ascii=False, indent=2)

    def _call_ai_analysis(self, client: OpenAI, analysis_data: str) -> Dict[str, Any]:
        """调用AI进行分析"""
        prompt = f"""你是一个任务执行分析专家。请分析以下任务执行数据，并提供深度分析报告。

## 执行数据
{analysis_data}

请以JSON格式返回分析结果，包含以下字段：
- summary: 一段简洁的总结（50-100字）
- insights: 3-5条关键洞察（数组）
- recommendations: 3-5条具体可行的改进建议（数组）
- risk_areas: 需要关注的风险点（数组）

请基于数据给出客观分析，不要编造不存在的问题。"""

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是任务执行分析专家，擅长从数据中发现问题和机会。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )

        content = response.choices[0].message.content or ""

        # 尝试解析JSON
        try:
            # 处理可能的markdown代码块
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content)
        except json.JSONDecodeError:
            return {
                "summary": content[:200],
                "insights": [],
                "recommendations": [],
                "risk_areas": [],
            }

    def _merge_analysis(
        self,
        basic_result: AnalysisResult,
        ai_analysis: Dict[str, Any],
    ) -> AnalysisResult:
        """合并基础分析和AI分析"""
        # 使用AI摘要替换基础摘要
        if ai_analysis.get("summary"):
            basic_result.summary = ai_analysis["summary"]

        # 合并洞察
        ai_insights = ai_analysis.get("insights", [])
        if ai_insights:
            basic_result.insights = ai_insights + basic_result.insights

        # 合并建议
        ai_recommendations = ai_analysis.get("recommendations", [])
        if ai_recommendations:
            basic_result.recommendations = ai_recommendations

        # 添加风险点到问题列表
        risk_areas = ai_analysis.get("risk_areas", [])
        for risk in risk_areas:
            basic_result.common_issues.append({
                "issue": risk,
                "count": 0,
                "suggestion": "需要关注",
            })

        return basic_result

    def get_task_summary(
        self,
        task_pattern: str,
        device_id: Optional[str] = None,
    ) -> str:
        """获取特定类型任务的简要总结"""
        records = self.history_manager.search_records(task_pattern, limit=20)

        if device_id:
            records = [r for r in records if r.device_id == device_id]

        if not records:
            return f"未找到与「{task_pattern}」相关的执行记录"

        success_count = sum(1 for r in records if r.success)
        total = len(records)
        avg_duration = sum(r.duration_seconds for r in records) / total if total > 0 else 0

        return (
            f"「{task_pattern}」相关任务: "
            f"共 {total} 次，成功 {success_count} 次 ({success_count/total:.0%})，"
            f"平均耗时 {avg_duration:.1f} 秒"
        )

    def get_device_summary(self, device_id: str) -> str:
        """获取设备执行总结"""
        records = self.history_manager.get_records_by_device(device_id, limit=50)

        if not records:
            return f"设备 {device_id} 暂无执行记录"

        success_count = sum(1 for r in records if r.success)
        total = len(records)
        recent_success = sum(1 for r in records[-10:] if r.success)

        return (
            f"设备 {device_id}: "
            f"历史 {total} 次任务，成功率 {success_count/total:.0%}；"
            f"最近10次成功 {recent_success} 次"
        )
