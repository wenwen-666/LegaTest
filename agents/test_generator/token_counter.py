"""
Token计数工具模块

提供多种方式计算文本的token数量，主要用于统计LLM调用的token消耗
"""

import re
import logging
import tiktoken
from typing import Union, Dict, Any, Optional

logger = logging.getLogger(__name__)

# DeepSeek模型的分段校正因子（基于实际API测试）
DEEPSEEK_SHORT_CORRECTION = 1.95   # 短文本 (≤10 tokens)
DEEPSEEK_LONG_CORRECTION = 1.08    # 长文本 (>10 tokens)

class TokenCounter:
    """Token计数器类"""
    
    def __init__(self):
        # 尝试导入tiktoken库进行精确token计数
        self.tiktoken_available = False
        self.encoder = None
        
        try:
            # 使用GPT-3.5/GPT-4的编码器，这是最常见的
            self.encoder = tiktoken.get_encoding("cl100k_base")
            self.tiktoken_available = True
            logger.debug("成功加载tiktoken编码器")
        except Exception as e:
            logger.warning(f"tiktoken库初始化失败: {e}，将使用估算方法计算token数")
    
    def count_tokens(self, text: str, model_name: str = "gpt-3.5-turbo") -> int:
        """
        计算文本的准确token数量，针对不同模型优化
        """
        if not text:
            return 0
        
        try:
            # 使用tiktoken进行基础计算
            if model_name == "deepseek-chat":
                # DeepSeek使用cl100k_base编码器 + 分段校正因子
                base_tokens = len(self.encoder.encode(text))
                
                # 根据文本长度选择不同的校正因子
                if base_tokens <= 10:
                    correction_factor = DEEPSEEK_SHORT_CORRECTION
                else:
                    correction_factor = DEEPSEEK_LONG_CORRECTION
                
                corrected_tokens = int(base_tokens * correction_factor)
                return corrected_tokens
            else:
                # 其他模型使用标准tiktoken
                try:
                    encoding = tiktoken.encoding_for_model(model_name)
                    return len(encoding.encode(text))
                except Exception:
                    # 如果模型不支持，使用默认编码器
                    return len(self.encoder.encode(text))
                
        except Exception as e:
            # 如果模型不支持，使用默认编码器
            try:
                base_tokens = len(self.encoder.encode(text))
                
                # 如果是DeepSeek，应用分段校正
                if model_name == "deepseek-chat":
                    if base_tokens <= 10:
                        correction_factor = DEEPSEEK_SHORT_CORRECTION
                    else:
                        correction_factor = DEEPSEEK_LONG_CORRECTION
                    return int(base_tokens * correction_factor)
                else:
                    return base_tokens
            except Exception:
                # 最后的fallback，简单估算
                base_estimate = max(len(text.split()), len(text) // 4)
                if model_name == "deepseek-chat":
                    # 简单估算情况下使用平均校正因子
                    return int(base_estimate * 1.5)
                return base_estimate
    
    def _estimate_tokens(self, text: str, model_name: str = "gpt-3.5-turbo") -> int:
        """
        改进的token估算方法
        
        基于更准确的经验公式和不同文本类型的特征
        """
        if not text:
            return 0
        
        # 先基于单词数进行基础估算（对英文更准确）
        words = text.split()
        word_based_estimate = len(words) * 1.3  # 英文平均1.3 tokens per word
        
        # 基于字符数的估算（对混合文本更通用）
        total_chars = len(text)
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_chars = total_chars - chinese_chars
        
        # 更精确的token估算
        # 英文：约3.5个字符 = 1个token（考虑空格和标点）
        # 中文：约1.3个字符 = 1个token（中文token密度更高）
        chinese_tokens = chinese_chars / 1.3
        english_tokens = english_chars / 3.5
        
        char_based_estimate = chinese_tokens + english_tokens
        
        # 取两种方法的平均值，更准确
        estimated_tokens = (word_based_estimate + char_based_estimate) / 2
        
        # 根据文本类型调整
        if self._is_code_like(text):
            # 代码文本token密度更高（更多的符号和关键词）
            estimated_tokens *= 1.25
        elif self._is_prompt_like(text):
            # 提示词文本通常token密度略低
            estimated_tokens *= 0.95
        
        # 根据模型类型微调（注意：这里是fallback估算，主要计算已在count_tokens中处理）
        if "deepseek" in model_name.lower():
            # DeepSeek对中文支持更好，token效率略高
            estimated_tokens *= 0.92
        elif "gpt-4" in model_name.lower():
            # GPT-4的token计算略有不同
            estimated_tokens *= 1.02
        elif "claude" in model_name.lower():
            # Claude的token计算
            estimated_tokens *= 1.08
        
        # 考虑特殊字符和格式的影响
        special_chars = len(re.findall(r'[{}()\[\];,.:!?\'"]', text))
        if special_chars > len(text) * 0.1:  # 如果特殊字符超过10%
            estimated_tokens *= 1.1
        
        return max(1, int(estimated_tokens))  # 至少1个token
    
    def _is_code_like(self, text: str) -> bool:
        """判断文本是否像代码"""
        # 简单的代码特征检测
        code_indicators = [
            'import ', 'class ', 'def ', 'function ', 'public ', 'private ',
            '{', '}', '()', ';', '@Test', '@Override', 'package ', '/*', '*/',
            'if (', 'for (', 'while (', 'try {', 'catch ('
        ]
        
        code_score = 0
        for indicator in code_indicators:
            if indicator in text:
                code_score += 1
        
        # 如果包含3个或以上代码特征，认为是代码
        return code_score >= 3
    
    def _is_prompt_like(self, text: str) -> bool:
        """判断文本是否像提示词"""
        # 提示词特征检测
        prompt_indicators = [
            'Generate', 'Please', 'Create', 'Write', 'Implement', 'Test',
            'following', 'requirements', 'guidelines', 'instructions',
            '##', '###', 'Args:', 'Returns:', 'Note:', 'Example:',
            'TEST GENERATION', 'CLASS INFORMATION', 'METHODS SECTION'
        ]
        
        prompt_score = 0
        text_lower = text.lower()
        for indicator in prompt_indicators:
            if indicator.lower() in text_lower:
                prompt_score += 1
        
        # 检查是否有markdown格式
        if '##' in text or '```' in text or '***' in text:
            prompt_score += 2
        
        # 如果包含3个或以上提示词特征，认为是提示词
        return prompt_score >= 3
    
    def get_token_stats(self, text: str, model_name: str = "gpt-3.5-turbo") -> Dict[str, Any]:
        """
        获取详细的token统计信息
        
        Returns:
            包含各种统计信息的字典
        """
        if not text:
            return {
                "token_count": 0,
                "char_count": 0,
                "word_count": 0,
                "line_count": 0,
                "chinese_chars": 0,
                "english_chars": 0,
                "is_code_like": False
            }
        
        token_count = self.count_tokens(text, model_name)
        char_count = len(text)
        word_count = len(text.split())
        line_count = text.count('\n') + 1
        
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_chars = char_count - chinese_chars
        is_code_like = self._is_code_like(text)
        
        return {
            "token_count": token_count,
            "char_count": char_count,
            "word_count": word_count,
            "line_count": line_count,
            "chinese_chars": chinese_chars,
            "english_chars": english_chars,
            "is_code_like": is_code_like,
            "chars_per_token": char_count / token_count if token_count > 0 else 0
        }

# 全局token计数器实例
global_token_counter = TokenCounter()

def count_tokens(text: str, model_name: str = "gpt-3.5-turbo") -> int:
    """
    计算文本的准确token数量，针对不同模型优化
    """
    return global_token_counter.count_tokens(text, model_name)

def estimate_prompt_and_completion_tokens(prompt_text: str, completion_text: str, model_name: str = "gpt-3.5-turbo"):
    """
    分别计算提示词和完成文本的优化token数
    """
    prompt_tokens = count_tokens(prompt_text, model_name)
    completion_tokens = count_tokens(completion_text, model_name)
    
    return prompt_tokens, completion_tokens, prompt_tokens + completion_tokens

def get_token_stats(text: str, model_name: str = "gpt-3.5-turbo") -> Dict[str, Any]:
    """
    便捷的token统计函数
    
    Args:
        text: 要分析的文本
        model_name: 模型名称
        
    Returns:
        详细统计信息
    """
    return global_token_counter.get_token_stats(text, model_name)

def format_token_count(token_count: int) -> str:
    """
    格式化token数量显示
    
    Args:
        token_count: token数量
        
    Returns:
        格式化后的字符串
    """
    if token_count < 1000:
        return f"{token_count}"
    elif token_count < 1000000:
        return f"{token_count/1000:.1f}K"
    else:
        return f"{token_count/1000000:.1f}M"

# 一些常用的token计算函数

def estimate_cost(prompt_tokens: int, response_tokens: int, model_name: str = "gpt-3.5-turbo") -> float:
    """
    估算API调用成本（美元）
    
    基于2024年最新的模型定价信息
    """
    # 2024年最新模型定价（每1K tokens，美元）
    pricing = {
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "gpt-4": {"input": 0.01, "output": 0.03},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "deepseek-chat": {"input": 0.00014, "output": 0.00028},  # DeepSeek实际定价
        "deepseek-coder": {"input": 0.00014, "output": 0.00028},
        "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
        "claude-3-sonnet": {"input": 0.003, "output": 0.015},
        "claude-3-opus": {"input": 0.015, "output": 0.075},
    }
    
    # 找到最匹配的定价
    model_pricing = None
    model_lower = model_name.lower()
    
    # 精确匹配
    for model_key in pricing:
        if model_key in model_lower:
            model_pricing = pricing[model_key]
            break
    
    # 如果没有精确匹配，使用模糊匹配
    if not model_pricing:
        if "deepseek" in model_lower:
            model_pricing = pricing["deepseek-chat"]
        elif "gpt-4" in model_lower:
            model_pricing = pricing["gpt-4"]
        elif "gpt-3.5" in model_lower or "gpt" in model_lower:
            model_pricing = pricing["gpt-3.5-turbo"]
        elif "claude" in model_lower:
            model_pricing = pricing["claude-3-sonnet"]  # 默认使用sonnet
        else:
            # 使用DeepSeek作为默认（最便宜）
            model_pricing = pricing["deepseek-chat"]
    
    input_cost = (prompt_tokens / 1000) * model_pricing["input"]
    output_cost = (response_tokens / 1000) * model_pricing["output"]
    
    return input_cost + output_cost

def get_model_info():
    """
    返回支持的模型和校正信息
    """
    return {
        "supported_models": {
            "deepseek-chat": {
                "base_encoder": "cl100k_base",
                "correction_strategy": "分段校正",
                "short_correction": DEEPSEEK_SHORT_CORRECTION,
                "long_correction": DEEPSEEK_LONG_CORRECTION,
                "accuracy": "基于实际API测试的分段校正，平均误差 19.2%"
            },
            "gpt-3.5-turbo": {
                "base_encoder": "cl100k_base", 
                "correction_factor": 1.0,
                "accuracy": "官方tiktoken，100%准确"
            },
            "gpt-4": {
                "base_encoder": "cl100k_base",
                "correction_factor": 1.0,
                "accuracy": "官方tiktoken，100%准确"
            }
        },
        "deepseek_calibration": {
            "test_samples": 4,
            "strategy": "分段校正",
            "short_texts": f"≤10 tokens × {DEEPSEEK_SHORT_CORRECTION}",
            "long_texts": f">10 tokens × {DEEPSEEK_LONG_CORRECTION}",
            "average_error": "19.2%"
        }
    }