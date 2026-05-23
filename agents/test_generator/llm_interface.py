"""
LLM接口模块，负责与大语言模型交互，生成测试代码
"""

import os
import re
import logging
import asyncio
import aiohttp
import time
from typing import Dict, Any

from . import config
from .statistics import global_stats_collector
from .token_counter import count_tokens, estimate_cost

logger = logging.getLogger(__name__)

# 跟踪已经输出过提示词的类，避免重复输出
_prompt_output_cache = set()

class LLMInterface:
    """LLM接口类，处理与大语言模型的交互"""
    
    def __init__(self):
        """初始化LLM接口"""
        self.config = config.config.get_api_config()
        self.primary_model = self.config["model"]
        self.fallback_models = [" "]  # 备用模型
        self.max_retries = 5  # 重试次数5次
        self.retry_delay = 5  # 初始延迟5秒
        
    async def generate_test_code(self, prompt: str, cls_info: Dict[str, Any]) -> str:
        """
        使用LLM生成测试代码
    
        Args:
            prompt: 提示词
            cls_info: 类信息
    
        Returns:
            生成的测试代码
        """
        # 检查是否需要输出提示词
        class_name = cls_info.get("className", "unknown")
        class_id = f"{cls_info.get('package', '')}.{class_name}"
        suite_index = cls_info.get('suite_index', 0)
        test_focus = cls_info.get('test_focus', '')
        
        # 直接显示提示词到终端
        print(f"\n{'=' * 80}")
        print(f"提示词 - {class_name} (Suite {suite_index})")
        print(f"{'=' * 80}")
        print(prompt)
        print(f"{'=' * 80}\n")
        
        # 第一次遇到这个类时，将完整的提示词写入统计文件
        if class_id not in _prompt_output_cache:
            _prompt_output_cache.add(class_id)
            logger.info(f"为类 '{class_name}' 生成测试")
            
            # 将提示词详情写入统计文件
            prompt_info = []
            prompt_info.append(f"\n{'=' * 80}")
            prompt_info.append(f"提示词 - {class_name}")
            prompt_info.append(f"{'=' * 80}")
            prompt_info.append(prompt)
            prompt_info.append(f"{'=' * 80}\n")
            global_stats_collector._write_to_stats_file("\n".join(prompt_info) + "\n")
        else:
            # 后续测试套件只将test focus写入文件
            if test_focus:
                focus_info = []
                focus_info.append(f"\n{'-' * 40}")
                focus_info.append(f"测试套件 V{suite_index} 的测试重点: {test_focus}")
                focus_info.append(f"{'-' * 40}\n")
                global_stats_collector._write_to_stats_file("\n".join(focus_info) + "\n")

        call_type = cls_info.get('call_type', 'generation')
        attempt_number = 1
        
        # 首先尝试主要模型
        try:
            start_time = time.time()
            response = await self._generate_with_model(self.primary_model, prompt, cls_info)
            duration = time.time() - start_time
            
            # 计算token数量和成本
            prompt_tokens = count_tokens(prompt, self.primary_model)
            response_tokens = count_tokens(response, self.primary_model)
            estimated_cost = estimate_cost(prompt_tokens, response_tokens, self.primary_model)
            
            # 记录统计信息
            global_stats_collector.record_llm_call(
                model_name=self.primary_model,
                prompt_length=len(prompt),
                response_length=len(response),
                duration=duration,
                success=True,
                call_type=call_type,
                attempt_number=attempt_number,
                prompt_tokens=prompt_tokens,
                response_tokens=response_tokens,
                estimated_cost=estimated_cost
            )
            
            # 简化的日志输出
            response_preview = response[:100].replace('\n', ' ')
            logger.debug(f"LLM响应前100字符: {response_preview}...")
            logger.debug(f"LLM响应总长度: {len(response)} 字符")
            logger.info(f"LLM调用完成: {duration:.1f}s, {prompt_tokens + response_tokens} tokens, ${estimated_cost:.4f}")
            return response
        except Exception as e:
            logger.warning(f"主要模型 {self.primary_model} 失败: {e}")
            
            # 尝试备用模型
            for model in self.fallback_models:
                try:
                    logger.info(f"尝试使用备用模型 {model}")
                    attempt_number += 1
                    start_time = time.time()
                    response = await self._generate_with_model(model, prompt, cls_info)
                    duration = time.time() - start_time
                    
                    # 计算token数量和成本
                    prompt_tokens = count_tokens(prompt, model)
                    response_tokens = count_tokens(response, model)
                    estimated_cost = estimate_cost(prompt_tokens, response_tokens, model)
                    
                    # 记录统计信息
                    global_stats_collector.record_llm_call(
                        model_name=model,
                        prompt_length=len(prompt),
                        response_length=len(response),
                        duration=duration,
                        success=True,
                        call_type=call_type,
                        attempt_number=attempt_number,
                        prompt_tokens=prompt_tokens,
                        response_tokens=response_tokens,
                        estimated_cost=estimated_cost
                    )
                    
                    logger.info(f"备用模型 {model} 调用完成: {duration:.1f}s, {prompt_tokens + response_tokens} tokens")
                    return response
                except Exception as e:
                    duration = time.time() - start_time
                    # 计算失败调用的提示词token（响应为0）
                    prompt_tokens = count_tokens(prompt, model)
                    # 记录失败的调用
                    global_stats_collector.record_llm_call(
                        model_name=model,
                        prompt_length=len(prompt),
                        response_length=0,
                        duration=duration,
                        success=False,
                        call_type=call_type,
                        error_message=str(e),
                        attempt_number=attempt_number,
                        prompt_tokens=prompt_tokens,
                        response_tokens=0,
                        estimated_cost=0.0
                    )
                    logger.warning(f"备用模型 {model} 失败: {e}")
                    
            # 所有模型都失败，抛出异常
            raise Exception("所有模型都生成失败")
            
    async def _generate_with_model(self, model: str, prompt: str, cls_info: Dict[str, Any]) -> str:
        """
        使用指定模型生成代码
        
        Args:
            model: 模型名称
            prompt: 提示词
            cls_info: 类信息
            
        Returns:
            生成的代码
        """
        for attempt in range(self.max_retries):
            try:
                return await self._make_api_request(model, prompt)
            except Exception as e:
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)  # 指数退避
                    logger.warning(f"第 {attempt + 1} 次尝试失败，{delay}秒后重试: {e}")
                    await asyncio.sleep(delay)
                else:
                    raise
                    
    async def _make_api_request(self, model: str, prompt: str) -> str:
        """
        发送API请求
        
        Args:
            model: 模型名称
            prompt: 提示词
            
        Returns:
            API响应文本
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['key']}"
        }
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": get_system_prompt()},
                {"role": "user", "content": prompt}
            ],
        }
        
        # 增加超时时间和错误处理
        timeout = aiohttp.ClientTimeout(total=self.config.get("timeout", 180))
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.config['base_url']}/v1/chat/completions",
                    headers=headers,
                    json=data
                ) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        return response_data["choices"][0]["message"]["content"]
                    else:
                        error_text = await response.text()
                        raise Exception(f"API请求失败 ({response.status}): {error_text}")
        except asyncio.TimeoutError:
            logger.error("API请求超时")
            raise Exception("API请求超时，请稍后重试")
        except aiohttp.ClientError as e:
            logger.error(f"API连接错误: {e}")
            raise Exception(f"API连接错误: {e}")
        except Exception as e:
            logger.error(f"API请求未知错误: {e}")
            raise
                    
    def extract_java_code(self, llm_response: str, cls_info: Dict[str, Any]) -> str:
        """
        从LLM响应中提取Java代码
    
        Args:
            llm_response: LLM的原始响应
            cls_info: 类信息
        
        Returns:
            提取的Java代码
        """
        if not llm_response:
            logger.error("LLM响应为空，无法提取代码")
            return ""
            
        # 尝试从Markdown代码块中提取代码
        code_blocks = re.findall(r'```(?:java)?\s*([\s\S]*?)```', llm_response)
        
        if code_blocks:
            # 使用最长的代码块
            code = max(code_blocks, key=len)
            logger.info(f"从Markdown代码块成功提取代码，长度: {len(code)} 字符")
        else:
            # 如果没有代码块，尝试直接使用整个响应
            code = llm_response
            logger.warning("未找到Markdown代码块，使用整个响应作为代码")
        
        return code

# 创建全局LLM接口实例
llm = LLMInterface()

# 为了保持API兼容性，提供与原版相同的函数接口
def generate_test_code(prompt: str, cls_info: Dict[str, Any]) -> str:
    """
    使用LLM生成测试代码的全局函数
    
    Args:
        prompt: 提示词
        cls_info: 类信息
        
    Returns:
        生成的测试代码
    """
    return asyncio.run(llm.generate_test_code(prompt, cls_info))

def extract_java_code(llm_response: str, cls_info: Dict[str, Any]) -> str:
    """
    从LLM响应中提取Java代码的全局函数
    
    Args:
        llm_response: LLM响应文本
        cls_info: 类信息，用于获取正确的包名
        
    Returns:
        提取的Java代码
    """
    return llm.extract_java_code(llm_response, cls_info)

def get_system_prompt() -> str:
    """
    获取系统提示词
    
    Returns:
        系统提示词文本
    """
    prompt_dir = config.config.get_paths()["prompt_dir"]
    system_prompt_file = os.path.join(prompt_dir, "enhanced_system_prompt.txt")
    
    try:
        with open(system_prompt_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception as e:
        logger.warning(f"无法读取系统提示词文件: {e}")
        # 返回默认的系统提示词
        return """You are a professional Java test engineer. Your task is to generate high-quality JUnit test cases for Java classes.

IMPORTANT: Output ONLY the complete Java test code without any conversation, explanation, or markdown formatting. 
Start your response with 'package' and provide a complete compilable Java test file.

Please follow these guidelines:
1. Focus on testing both normal and edge cases
2. Include appropriate assertions
3. Follow JUnit best practices
4. Add clear comments explaining test scenarios
5. Handle exceptions properly
6. Use meaningful variable names
7. Structure tests using the Arrange-Act-Assert pattern

The test class name should match the format: OriginalClassName + "TestV{N}"
Include all necessary imports for JUnit 5: org.junit.jupiter.api
Use proper package structure to match the original class."""

def test_api_connection() -> bool:
    """
    测试API连接是否正常
    
    Returns:
        如果API连接正常则返回True
    """
    try:
        # 发送一个简单的测试请求
        response = asyncio.run(llm._make_api_request(
            llm.primary_model,
            "Generate a simple test case for a Calculator class."
        ))
        return bool(response)
    except Exception as e:
        logger.error(f"API连接测试失败: {e}")
        return False 