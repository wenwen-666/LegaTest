"""
测试生成统计模块

负责收集和统计测试生成过程中的各种时间和调用数据
"""

import time
import json
import logging
import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class LLMCallStats:
    """单次LLM调用统计"""
    start_time: float
    end_time: float
    duration: float
    model_name: str
    prompt_length: int
    response_length: int
    success: bool
    error_message: Optional[str] = None
    attempt_number: int = 1
    call_type: str = "generation"  # generation, repair
    prompt_tokens: int = 0
    response_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

@dataclass
class TestFileStats:
    """单个测试文件的统计信息"""
    test_file_path: str
    class_name: str
    suite_index: int
    start_time: float
    end_time: Optional[float] = None
    
    # LLM调用统计
    llm_calls: List[LLMCallStats] = None
    total_llm_calls: int = 0
    generation_calls: int = 0
    repair_calls: int = 0
    
    # 时间分解统计
    total_duration: float = 0.0
    llm_response_time: float = 0.0
    file_write_time: float = 0.0
    maven_compile_time: float = 0.0
    repair_time: float = 0.0
    
    # Token统计
    total_prompt_tokens: int = 0
    total_response_tokens: int = 0
    total_tokens: int = 0
    estimated_total_cost: float = 0.0
    
    # 修复统计
    repair_attempts: int = 0
    rule_fixes_applied: int = 0
    llm_fixes_applied: int = 0
    final_success: bool = False
    
    def __post_init__(self):
        if self.llm_calls is None:
            self.llm_calls = []
    
    def add_llm_call(self, call_stats: LLMCallStats):
        """添加LLM调用统计"""
        self.llm_calls.append(call_stats)
        self.total_llm_calls += 1
        self.llm_response_time += call_stats.duration
        
        # 累加token统计
        self.total_prompt_tokens += call_stats.prompt_tokens
        self.total_response_tokens += call_stats.response_tokens
        self.total_tokens += call_stats.total_tokens
        self.estimated_total_cost += call_stats.estimated_cost
        
        if call_stats.call_type == "generation":
            self.generation_calls += 1
        elif call_stats.call_type == "repair":
            self.repair_calls += 1
    
    def finalize(self):
        """完成统计，计算总时间"""
        if self.end_time:
            self.total_duration = self.end_time - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        data['llm_calls'] = [call.to_dict() for call in self.llm_calls]
        return data

class StatisticsCollector:
    """统计收集器"""
    
    def __init__(self, output_to_file: bool = True, stats_file_path: str = None, project_path: str = None):
        self.current_test_stats: Optional[TestFileStats] = None
        self.all_test_stats: List[TestFileStats] = []
        self.session_start_time = time.time()
        self.output_to_file = output_to_file
        self.stats_file_path = stats_file_path or "test_generation_detailed_stats.txt"
        self.stats_file_handle = None
        
        # 新增：支持JSON输出的路径
        self.project_path = project_path or os.getcwd()
        self.stats_dir = os.path.join(self.project_path, "stats")
        self.class_stats = {}  # 按类名存储类级别统计
        
        # 确保stats目录存在
        if self.output_to_file:
            os.makedirs(self.stats_dir, exist_ok=True)
        
        # 如果需要输出到文件，打开文件句柄
        if self.output_to_file:
            try:
                self.stats_file_handle = open(self.stats_file_path, 'w', encoding='utf-8')
                self._write_to_stats_file(f"测试生成详细统计报告\n")
                self._write_to_stats_file(f"开始时间: {datetime.fromtimestamp(self.session_start_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
                self._write_to_stats_file("=" * 80 + "\n\n")
            except Exception as e:
                logger.error(f"无法创建统计文件 {self.stats_file_path}: {e}")
                self.output_to_file = False
    
    def _write_to_stats_file(self, content: str):
        """写入统计文件"""
        if self.output_to_file and self.stats_file_handle:
            try:
                self.stats_file_handle.write(content)
                self.stats_file_handle.flush()  # 立即刷新到文件
            except Exception as e:
                logger.error(f"写入统计文件失败: {e}")
    
    def _close_stats_file(self):
        """关闭统计文件"""
        if self.stats_file_handle:
            try:
                self.stats_file_handle.close()
            except Exception as e:
                logger.error(f"关闭统计文件失败: {e}")
        
    def start_test_generation(self, test_file_path: str, class_name: str, suite_index: int) -> TestFileStats:
        """开始测试生成统计"""
        self.current_test_stats = TestFileStats(
            test_file_path=test_file_path,
            class_name=class_name,
            suite_index=suite_index,
            start_time=time.time()
        )
        logger.info(f"开始统计测试生成: {class_name} Suite {suite_index}")
        return self.current_test_stats
    
    def record_llm_call(self, 
                       model_name: str,
                       prompt_length: int,
                       response_length: int,
                       duration: float,
                       success: bool,
                       call_type: str = "generation",
                       error_message: Optional[str] = None,
                       attempt_number: int = 1,
                       prompt_tokens: int = 0,
                       response_tokens: int = 0,
                       estimated_cost: float = 0.0) -> LLMCallStats:
        """记录LLM调用"""
        if not self.current_test_stats:
            logger.warning("没有当前测试统计，无法记录LLM调用")
            return None
            
        total_tokens = prompt_tokens + response_tokens
        call_stats = LLMCallStats(
            start_time=time.time() - duration,
            end_time=time.time(),
            duration=duration,
            model_name=model_name,
            prompt_length=prompt_length,
            response_length=response_length,
            success=success,
            error_message=error_message,
            attempt_number=attempt_number,
            call_type=call_type,
            prompt_tokens=prompt_tokens,
            response_tokens=response_tokens,
            total_tokens=total_tokens,
            estimated_cost=estimated_cost
        )
        
        self.current_test_stats.add_llm_call(call_stats)
        logger.debug(f"记录LLM调用: {call_type}, 耗时 {duration:.2f}s")
        return call_stats
    
    def record_file_write_time(self, duration: float):
        """记录文件写入时间"""
        if self.current_test_stats:
            self.current_test_stats.file_write_time += duration
    
    def record_maven_compile_time(self, duration: float):
        """记录Maven编译时间"""
        if self.current_test_stats:
            self.current_test_stats.maven_compile_time += duration
    
    def record_repair_attempt(self, repair_type: str):
        """记录修复尝试"""
        if self.current_test_stats:
            self.current_test_stats.repair_attempts += 1
            if repair_type == "rule":
                self.current_test_stats.rule_fixes_applied += 1
            elif repair_type == "llm":
                self.current_test_stats.llm_fixes_applied += 1
    
    def merge_repair_stats(self, repair_stats):
        """合并来自test_repair模块的统计信息"""
        if not self.current_test_stats:
            logger.warning("没有当前测试统计，无法合并修复统计")
            return
            
        if repair_stats:
            # 合并修复统计信息
            self.current_test_stats.repair_attempts += repair_stats.repair_attempts
            self.current_test_stats.rule_fixes_applied += repair_stats.rule_fixes_applied
            self.current_test_stats.llm_fixes_applied += repair_stats.llm_fixes_applied
            self.current_test_stats.repair_time += repair_stats.total_repair_time
            
            # 为修复LLM调用创建统计条目（仅当没有通过test_generator统计系统时）
            if repair_stats.llm_calls > 0:
                # 检查当前repair类型调用数量
                current_repair_calls = sum(1 for call in self.current_test_stats.llm_calls if call.call_type == "repair")
                expected_repair_calls = repair_stats.llm_calls
                
                logger.info(f"修复调用统计检查: 当前repair调用 {current_repair_calls}, 期望 {expected_repair_calls}")
                
                # 只有当repair调用数不匹配且确实缺少真实数据时才创建估算条目
                if current_repair_calls < expected_repair_calls:
                    missing_calls = expected_repair_calls - current_repair_calls
                    
                    # 检查最近的repair调用是否有真实API数据（非估算值）
                    recent_repair_calls = [call for call in self.current_test_stats.llm_calls if call.call_type == "repair"]
                    has_real_api_data = any(
                        call.prompt_tokens != 500 or call.response_tokens != 300 
                        for call in recent_repair_calls[-missing_calls:]
                    ) if recent_repair_calls else False
                    
                    if has_real_api_data:
                        logger.info(f"检测到真实API数据，跳过创建估算条目")
                    else:
                        # 只有在没有真实API数据时才创建估算条目
                        if repair_stats.llm_repair_time > 0:
                            avg_duration_per_call = repair_stats.llm_repair_time / repair_stats.llm_calls
                        else:
                            avg_duration_per_call = 30.0  # 默认30秒
                        
                        current_time = time.time()
                        
                        logger.info(f"未检测到真实API数据，创建 {missing_calls} 个估算修复LLM调用条目，平均耗时 {avg_duration_per_call:.2f}s")
                        
                        for i in range(missing_calls):
                            # 创建修复LLM调用统计（估算值）
                            call_stats = LLMCallStats(
                                start_time=current_time - avg_duration_per_call,
                                end_time=current_time,
                                duration=avg_duration_per_call,
                                model_name="deepseek-chat",
                                prompt_length=2000,  # 修复提示通常更长
                                response_length=800,  # 修复响应也更长
                                success=True,
                                call_type="repair",
                                prompt_tokens=500,  # 修复token数估算（标记为估算值）
                                response_tokens=300,
                                total_tokens=800,
                                estimated_cost=0.00016  # 修复成本估算
                            )
                            self.current_test_stats.add_llm_call(call_stats)
                            current_time += avg_duration_per_call
                else:
                    logger.info(f"修复LLM调用已通过test_generator统计系统记录，无需创建估算条目")
            
            logger.debug(f"合并修复统计: 修复尝试 {repair_stats.repair_attempts}, "
                        f"规则修复 {repair_stats.rule_fixes_applied}, "
                        f"LLM修复 {repair_stats.llm_fixes_applied}, "
                        f"LLM修复时间 {repair_stats.llm_repair_time:.2f}s")
    
    def finish_test_generation(self, success: bool) -> TestFileStats:
        """完成测试生成统计"""
        if not self.current_test_stats:
            logger.warning("没有当前测试统计")
            return None
            
        self.current_test_stats.end_time = time.time()
        self.current_test_stats.final_success = success
        self.current_test_stats.finalize()
        
        # 计算修复时间（除去初始生成的LLM时间）
        repair_llm_time = sum(call.duration for call in self.current_test_stats.llm_calls 
                             if call.call_type == "repair")
        self.current_test_stats.repair_time = repair_llm_time
        
        # 保存到历史记录
        self.all_test_stats.append(self.current_test_stats)
        
        logger.info(f"完成测试统计: {self.current_test_stats.class_name} Suite {self.current_test_stats.suite_index}, "
                   f"总耗时 {self.current_test_stats.total_duration:.2f}s")
        
        completed_stats = self.current_test_stats
        self.current_test_stats = None
        
        # 新增：保存套件级别统计
        self._save_suite_stats(completed_stats)
        
        return completed_stats
    
    def _save_suite_stats(self, test_stats: TestFileStats):
        """保存套件级别统计到独立JSON文件"""
        if not self.output_to_file or not test_stats:
            return
            
        try:
            # 构建套件文件名：ClassName + V + suite_index + .json
            suite_filename = f"{test_stats.class_name}V{test_stats.suite_index}.json"
            suite_path = os.path.join(self.stats_dir, suite_filename)
            
            # 构建套件级别统计数据
            suite_data = {
                "suite_info": {
                    "class_name": test_stats.class_name,
                    "suite_index": test_stats.suite_index,
                    "test_file_path": test_stats.test_file_path,
                    "generation_time": datetime.fromtimestamp(test_stats.start_time).strftime("%Y-%m-%d %H:%M:%S"),
                    "success": test_stats.final_success,
                    "duration": {
                        "total_seconds": round(test_stats.total_duration, 2),
                        "llm_response_seconds": round(test_stats.llm_response_time, 2),
                        "maven_compile_seconds": round(test_stats.maven_compile_time, 2),
                        "repair_seconds": round(test_stats.repair_time, 2),
                        "file_write_seconds": round(test_stats.file_write_time, 2)
                    }
                },
                "llm_statistics": {
                    "total_calls": test_stats.total_llm_calls,
                    "generation_calls": test_stats.generation_calls,
                    "repair_calls": test_stats.repair_calls,
                    "tokens": {
                        "prompt_tokens": test_stats.total_prompt_tokens,
                        "response_tokens": test_stats.total_response_tokens,
                        "total_tokens": test_stats.total_tokens,
                        "estimated_cost": round(test_stats.estimated_total_cost, 6)
                    }
                },
                "repair_statistics": {
                    "repair_attempts": test_stats.repair_attempts,
                    "rule_fixes_applied": test_stats.rule_fixes_applied,
                    "llm_fixes_applied": test_stats.llm_fixes_applied
                },
                "llm_call_details": [call.to_dict() for call in test_stats.llm_calls]
            }
            
            # 保存到文件
            with open(suite_path, 'w', encoding='utf-8') as f:
                json.dump(suite_data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"套件统计已保存: {suite_path}")
            
            # 更新类级别统计
            self._update_class_stats(test_stats)
            
        except Exception as e:
            logger.error(f"保存套件统计失败: {e}")
    
    def _update_class_stats(self, test_stats: TestFileStats):
        """更新类级别统计"""
        class_name = test_stats.class_name
        
        if class_name not in self.class_stats:
            self.class_stats[class_name] = {
                "class_name": class_name,
                "suites": [],
                "total_suites": 0,
                "successful_suites": 0,
                "total_duration": 0.0,
                "total_llm_calls": 0,
                "total_tokens": 0,
                "total_cost": 0.0
            }
        
        class_stat = self.class_stats[class_name]
        class_stat["suites"].append({
            "suite_index": test_stats.suite_index,
            "success": test_stats.final_success,
            "duration": test_stats.total_duration,
            "llm_calls": test_stats.total_llm_calls,
            "tokens": test_stats.total_tokens,
            "cost": test_stats.estimated_total_cost
        })
        
        class_stat["total_suites"] += 1
        if test_stats.final_success:
            class_stat["successful_suites"] += 1
        class_stat["total_duration"] += test_stats.total_duration
        class_stat["total_llm_calls"] += test_stats.total_llm_calls
        class_stat["total_tokens"] += test_stats.total_tokens
        class_stat["total_cost"] += test_stats.estimated_total_cost
    
    def save_class_summary(self, class_name: str):
        """保存类级别统计汇总"""
        if not self.output_to_file or class_name not in self.class_stats:
            return
            
        try:
            class_stat = self.class_stats[class_name]
            
            # JSON格式汇总
            json_summary = {
                "class_info": {
                    "class_name": class_name,
                    "total_suites": class_stat["total_suites"],
                    "successful_suites": class_stat["successful_suites"],
                    "success_rate": round(class_stat["successful_suites"] / class_stat["total_suites"] * 100, 1) if class_stat["total_suites"] > 0 else 0,
                    "generation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                },
                "performance_summary": {
                    "total_duration_seconds": round(class_stat["total_duration"], 2),
                    "avg_duration_per_suite": round(class_stat["total_duration"] / class_stat["total_suites"], 2) if class_stat["total_suites"] > 0 else 0,
                    "total_llm_calls": class_stat["total_llm_calls"],
                    "avg_llm_calls_per_suite": round(class_stat["total_llm_calls"] / class_stat["total_suites"], 1) if class_stat["total_suites"] > 0 else 0
                },
                "cost_summary": {
                    "total_tokens": class_stat["total_tokens"],
                    "avg_tokens_per_suite": round(class_stat["total_tokens"] / class_stat["total_suites"]) if class_stat["total_suites"] > 0 else 0,
                    "total_estimated_cost": round(class_stat["total_cost"], 6),
                    "avg_cost_per_suite": round(class_stat["total_cost"] / class_stat["total_suites"], 6) if class_stat["total_suites"] > 0 else 0
                },
                "suite_details": class_stat["suites"]
            }
            
            # 保存JSON汇总
            json_path = os.path.join(self.stats_dir, f"{class_name}_class_summary.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_summary, f, indent=2, ensure_ascii=False)
            
            # 保存可读格式汇总
            txt_path = os.path.join(self.stats_dir, f"{class_name}_class_summary_summary.txt")
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(f"类 {class_name} 测试生成汇总报告\n")
                f.write("=" * 60 + "\n\n")
                f.write(f"生成时间: {json_summary['class_info']['generation_time']}\n")
                f.write(f"总套件数: {json_summary['class_info']['total_suites']}\n")
                f.write(f"成功套件数: {json_summary['class_info']['successful_suites']}\n")
                f.write(f"成功率: {json_summary['class_info']['success_rate']}%\n\n")
                
                f.write("性能统计:\n")
                f.write(f"  总耗时: {json_summary['performance_summary']['total_duration_seconds']}秒\n")
                f.write(f"  平均每套件耗时: {json_summary['performance_summary']['avg_duration_per_suite']}秒\n")
                f.write(f"  总LLM调用次数: {json_summary['performance_summary']['total_llm_calls']}\n")
                f.write(f"  平均每套件LLM调用: {json_summary['performance_summary']['avg_llm_calls_per_suite']}次\n\n")
                
                f.write("费用统计:\n")
                f.write(f"  总Token数: {json_summary['cost_summary']['total_tokens']}\n")
                f.write(f"  平均每套件Token数: {json_summary['cost_summary']['avg_tokens_per_suite']}\n")
                f.write(f"  总估算费用: ${json_summary['cost_summary']['total_estimated_cost']}\n")
                f.write(f"  平均每套件费用: ${json_summary['cost_summary']['avg_cost_per_suite']}\n\n")
                
                f.write("各套件详情:\n")
                for suite in json_summary['suite_details']:
                    status = "成功" if suite['success'] else "失败"
                    f.write(f"  Suite {suite['suite_index']}: {status} - {suite['duration']:.1f}s - {suite['llm_calls']}次调用 - {suite['tokens']}tokens - ${suite['cost']:.4f}\n")
            
            logger.info(f"类级别统计已保存: {json_path}")
            
        except Exception as e:
            logger.error(f"保存类级别统计失败: {e}")
    
    def save_project_summary(self):
        """保存项目级别统计汇总"""
        if not self.output_to_file:
            return
            
        try:
            session_summary = self.get_session_summary()
            if "message" in session_summary:
                return
            
            # 构建项目级别统计
            project_summary = {
                "project_info": {
                    "generation_time": session_summary["session_start_time"],
                    "completion_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "total_tests_generated": session_summary["total_tests_generated"],
                    "successful_tests": session_summary["successful_tests"],
                    "success_rate": session_summary["success_rate"]
                },
                "llm_statistics": {
                    "total_llm_calls": session_summary["total_llm_calls"],
                    "generation_calls": session_summary["generation_calls"],
                    "repair_calls": session_summary["repair_calls"],
                    "token_statistics": session_summary["token_statistics"]
                },
                "time_breakdown": session_summary["time_breakdown"],
                "averages": session_summary["averages"],
                "class_summaries": {}
            }
            
            # 添加各类的统计汇总
            for class_name, class_stat in self.class_stats.items():
                project_summary["class_summaries"][class_name] = {
                    "total_suites": class_stat["total_suites"],
                    "successful_suites": class_stat["successful_suites"],
                    "success_rate": round(class_stat["successful_suites"] / class_stat["total_suites"] * 100, 1) if class_stat["total_suites"] > 0 else 0,
                    "total_duration": round(class_stat["total_duration"], 2),
                    "total_tokens": class_stat["total_tokens"],
                    "total_cost": round(class_stat["total_cost"], 6)
                }
            
            # 保存项目级别JSON统计
            project_json_path = os.path.join(self.stats_dir, "project_final.json")
            with open(project_json_path, 'w', encoding='utf-8') as f:
                json.dump(project_summary, f, indent=2, ensure_ascii=False)
            
            # 保存兼容格式的统计文件
            detailed_stats_path = os.path.join(self.project_path, "detailed_statistics.json")
            with open(detailed_stats_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "session_summary": session_summary,
                    "test_details": [stats.to_dict() for stats in self.all_test_stats]
                }, f, indent=2, ensure_ascii=False)
            
            logger.info(f"项目级别统计已保存: {project_json_path}")
            
        except Exception as e:
            logger.error(f"保存项目级别统计失败: {e}")
    
    def get_session_summary(self) -> Dict[str, Any]:
        """获取会话统计汇总"""
        if not self.all_test_stats:
            return {"message": "暂无测试统计数据"}
        
        total_tests = len(self.all_test_stats)
        successful_tests = sum(1 for stats in self.all_test_stats if stats.final_success)
        total_llm_calls = sum(stats.total_llm_calls for stats in self.all_test_stats)
        total_generation_calls = sum(stats.generation_calls for stats in self.all_test_stats)
        total_repair_calls = sum(stats.repair_calls for stats in self.all_test_stats)
        
        total_time = sum(stats.total_duration for stats in self.all_test_stats)
        total_llm_time = sum(stats.llm_response_time for stats in self.all_test_stats)
        total_maven_time = sum(stats.maven_compile_time for stats in self.all_test_stats)
        total_repair_time = sum(stats.repair_time for stats in self.all_test_stats)
        
        # Token统计
        total_prompt_tokens = sum(stats.total_prompt_tokens for stats in self.all_test_stats)
        total_response_tokens = sum(stats.total_response_tokens for stats in self.all_test_stats)
        total_tokens = sum(stats.total_tokens for stats in self.all_test_stats)
        total_estimated_cost = sum(stats.estimated_total_cost for stats in self.all_test_stats)
        
        avg_time_per_test = total_time / total_tests if total_tests > 0 else 0
        avg_llm_time_per_test = total_llm_time / total_tests if total_tests > 0 else 0
        avg_tokens_per_test = total_tokens / total_tests if total_tests > 0 else 0
        
        # 导入token格式化函数
        from .token_counter import format_token_count
        
        return {
            "session_start_time": datetime.fromtimestamp(self.session_start_time).strftime("%Y-%m-%d %H:%M:%S"),
            "total_tests_generated": total_tests,
            "successful_tests": successful_tests,
            "success_rate": f"{(successful_tests/total_tests*100):.1f}%" if total_tests > 0 else "0%",
            "total_llm_calls": total_llm_calls,
            "generation_calls": total_generation_calls,
            "repair_calls": total_repair_calls,
            "token_statistics": {
                "total_prompt_tokens": format_token_count(total_prompt_tokens),
                "total_response_tokens": format_token_count(total_response_tokens),
                "total_tokens": format_token_count(total_tokens),
                "estimated_total_cost": f"${total_estimated_cost:.4f}",
                "avg_tokens_per_test": format_token_count(int(avg_tokens_per_test))
            },
            "time_breakdown": {
                "total_time": f"{total_time:.2f}s",
                "llm_response_time": f"{total_llm_time:.2f}s ({total_llm_time/total_time*100:.1f}%)" if total_time > 0 else "0s",
                "maven_compile_time": f"{total_maven_time:.2f}s ({total_maven_time/total_time*100:.1f}%)" if total_time > 0 else "0s",
                "repair_time": f"{total_repair_time:.2f}s ({total_repair_time/total_time*100:.1f}%)" if total_time > 0 else "0s",
                "other_time": f"{total_time-total_llm_time-total_maven_time:.2f}s"
            },
            "averages": {
                "avg_time_per_test": f"{avg_time_per_test:.2f}s",
                "avg_llm_time_per_test": f"{avg_llm_time_per_test:.2f}s",
                "avg_llm_calls_per_test": f"{total_llm_calls/total_tests:.1f}" if total_tests > 0 else "0",
                "avg_tokens_per_test": format_token_count(int(avg_tokens_per_test))
            }
        }
    
    def print_test_summary(self, test_stats: TestFileStats):
        """将单个测试的详细统计写入文件"""
        if not self.output_to_file:
            return
            
        # 导入token格式化函数
        from .token_counter import format_token_count
        
        summary = []
        summary.append(f"\n{'='*60}")
        summary.append(f"测试文件统计: {test_stats.class_name} Suite {test_stats.suite_index}")
        summary.append(f"{'='*60}")
        summary.append(f"文件路径: {test_stats.test_file_path}")
        summary.append(f"生成状态: {'成功' if test_stats.final_success else '失败'}")
        summary.append(f"总耗时: {test_stats.total_duration:.2f}s")
        summary.append(f"\n时间分解:")
        summary.append(f"  - LLM响应时间: {test_stats.llm_response_time:.2f}s ({test_stats.llm_response_time/test_stats.total_duration*100:.1f}%)")
        summary.append(f"  - Maven编译时间: {test_stats.maven_compile_time:.2f}s ({test_stats.maven_compile_time/test_stats.total_duration*100:.1f}%)")
        summary.append(f"  - 修复时间: {test_stats.repair_time:.2f}s ({test_stats.repair_time/test_stats.total_duration*100:.1f}%)")
        summary.append(f"  - 其他时间: {test_stats.total_duration-test_stats.llm_response_time-test_stats.maven_compile_time:.2f}s")
        
        summary.append(f"\nLLM调用统计:")
        summary.append(f"  - 总调用次数: {test_stats.total_llm_calls}")
        summary.append(f"  - 生成调用: {test_stats.generation_calls}")
        summary.append(f"  - 修复调用: {test_stats.repair_calls}")
        
        summary.append(f"\nToken使用统计:")
        summary.append(f"  - 提示词tokens: {format_token_count(test_stats.total_prompt_tokens)}")
        summary.append(f"  - 响应tokens: {format_token_count(test_stats.total_response_tokens)}")
        summary.append(f"  - 总tokens: {format_token_count(test_stats.total_tokens)}")
        summary.append(f"  - 估算费用: ${test_stats.estimated_total_cost:.4f}")
        
        summary.append(f"\n修复统计:")
        summary.append(f"  - 修复尝试次数: {test_stats.repair_attempts}")
        summary.append(f"  - 规则修复次数: {test_stats.rule_fixes_applied}")
        summary.append(f"  - LLM修复次数: {test_stats.llm_fixes_applied}")
        
        if test_stats.llm_calls:
            summary.append(f"\nLLM调用详情:")
            for i, call in enumerate(test_stats.llm_calls, 1):
                status = "成功" if call.success else f"失败({call.error_message})"
                token_info = f"{format_token_count(call.total_tokens)}tokens"
                summary.append(f"  {i}. {call.call_type} - {call.model_name} - {call.duration:.2f}s - {token_info} - {status}")
        
        summary.append(f"{'='*60}\n")
        
        # 写入文件
        self._write_to_stats_file("\n".join(summary) + "\n")
        
        # 在终端只显示简化信息
        logger.info(f"测试 {test_stats.class_name} Suite {test_stats.suite_index} 完成: "
                   f"{'成功' if test_stats.final_success else '失败'}, "
                   f"耗时 {test_stats.total_duration:.1f}s, "
                   f"LLM调用 {test_stats.total_llm_calls} 次, "
                   f"Token {format_token_count(test_stats.total_tokens)}")
    
    def print_session_summary(self):
        """将会话统计汇总写入文件"""
        summary = self.get_session_summary()
        
        if "message" in summary:
            if self.output_to_file:
                self._write_to_stats_file(f"\n{summary['message']}\n")
            logger.info(summary["message"])
            return
        
        # 写入详细汇总到文件
        if self.output_to_file:
            summary_lines = []
            summary_lines.append(f"\n{'='*80}")
            summary_lines.append(f"测试生成会话统计汇总")
            summary_lines.append(f"{'='*80}")
            summary_lines.append(f"会话开始时间: {summary['session_start_time']}")
            summary_lines.append(f"总测试数: {summary['total_tests_generated']}")
            summary_lines.append(f"成功测试数: {summary['successful_tests']}")
            summary_lines.append(f"成功率: {summary['success_rate']}")
            summary_lines.append(f"总LLM调用次数: {summary['total_llm_calls']}")
            summary_lines.append(f"  - 生成调用: {summary['generation_calls']}")
            summary_lines.append(f"  - 修复调用: {summary['repair_calls']}")
            
            summary_lines.append(f"\nToken使用统计:")
            for key, value in summary['token_statistics'].items():
                summary_lines.append(f"  - {key}: {value}")
            
            summary_lines.append(f"\n时间分解:")
            for key, value in summary['time_breakdown'].items():
                summary_lines.append(f"  - {key}: {value}")
            
            summary_lines.append(f"\n平均值:")
            for key, value in summary['averages'].items():
                summary_lines.append(f"  - {key}: {value}")
            
            summary_lines.append(f"{'='*80}")
            summary_lines.append(f"\n结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            self._write_to_stats_file("\n".join(summary_lines) + "\n")
            self._close_stats_file()
        
        # 在终端显示简化的会话汇总
        logger.info(f"测试生成会话完成: "
                   f"总测试 {summary['total_tests_generated']}, "
                   f"成功 {summary['successful_tests']}, "
                   f"成功率 {summary['success_rate']}, "
                   f"总Token {summary['token_statistics']['total_tokens']}, "
                   f"费用 {summary['token_statistics']['estimated_total_cost']}")
        
        if self.output_to_file:
            logger.info(f"详细统计已保存到: {self.stats_file_path}")
        
        # 保存项目级别统计
        self.save_project_summary()
    
    def save_statistics(self, output_path: str):
        """保存统计数据到JSON文件"""
        try:
            data = {
                "session_summary": self.get_session_summary(),
                "test_details": [stats.to_dict() for stats in self.all_test_stats]
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"统计数据已保存到: {output_path}")
        except Exception as e:
            logger.error(f"保存统计数据失败: {e}")

# 全局统计收集器实例 - 延迟初始化
global_stats_collector = None

def get_global_stats_collector():
    """获取全局统计收集器实例"""
    global global_stats_collector
    if global_stats_collector is None:
        # 导入配置
        from .config import config
        stats_config = config.get_statistics_config()
        
        global_stats_collector = StatisticsCollector(
            output_to_file=stats_config.get("output_to_file", True),
            stats_file_path=stats_config.get("detailed_stats_file", "test_generation_detailed_stats.txt")
        )
    return global_stats_collector

# 为了保持兼容性，设置全局变量
global_stats_collector = get_global_stats_collector()

# 装饰器用于自动统计LLM调用时间
def track_llm_call(call_type: str = "generation"):
    """装饰器：自动跟踪LLM调用时间"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                # 尝试从参数中提取信息
                prompt_length = 0
                response_length = 0
                if args:
                    if isinstance(args[0], str):  # 第一个参数是prompt
                        prompt_length = len(args[0])
                if isinstance(result, str):
                    response_length = len(result)
                
                global_stats_collector.record_llm_call(
                    model_name="unknown",
                    prompt_length=prompt_length,
                    response_length=response_length,
                    duration=duration,
                    success=True,
                    call_type=call_type
                )
                return result
            except Exception as e:
                duration = time.time() - start_time
                global_stats_collector.record_llm_call(
                    model_name="unknown",
                    prompt_length=0,
                    response_length=0,
                    duration=duration,
                    success=False,
                    call_type=call_type,
                    error_message=str(e)
                )
                raise
        return wrapper
    return decorator