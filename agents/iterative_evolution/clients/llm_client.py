"""
DeepSeek API调用模块，处理与DeepSeek API的交互
"""

import os
import re
import json
import time
import requests
from typing import Dict, Optional

class LLMClient:
    def __init__(self, base_dir: str):
        """初始化LLM客户端（支持DeepSeek等）
        
        Args:
            base_dir: 项目基础目录，用于查找配置文件
        """
        self.base_dir = base_dir
        self.api = self._init_api_config()
    
    def _init_api_config(self) -> Dict:
        """初始化API配置"""
        api_key = os.getenv("DEEPSEEK_API_KEY", "your api key")
        print(f"🔑 API密钥状态: {'已设置' if api_key else '未设置'} ({'内置' if api_key.startswith('sk-72a0562c') else '环境变量'})")
        return {
            "key": api_key,
            "base_url": os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
            "model": os.getenv("API_MODEL", "deepseek-chat"),
            "timeout": int(os.getenv("API_REQUEST_TIMEOUT", "180"))
        }
    
    def generate_code(self, prompt: str, max_tokens: int = None) -> str:
        """调用DeepSeek API生成代码
        
        Args:
            prompt: 提示词
            max_tokens: 最大生成的token数量，None表示不限制
            
        Returns:
            生成的代码，如果调用失败则返回空字符串
        """
        if not self.api["key"]:
            print("错误: 未设置API密钥，无法调用DeepSeek API")
            return ""
        
        # 调用DeepSeek API
        url = f"{self.api['base_url']}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api['key']}"
        }
        
        data = {
            "model": self.api["model"],
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional Java test generation expert. MANDATORY requirements: 1) The generated code must compile successfully, ensuring all imports, types, and method calls are correct. 2) Every test method MUST contain actual assertions (assertEquals, assertTrue, assertFalse, assertNull, assertNotNull, etc.) - never use placeholder comments like '// Test implementation' or '// TODO'. 3) Generate complete test methods with real testing logic, not empty methods or comments. 4) Avoid using non-existent methods or incorrect parameter types. 5) Generate test code that can be executed directly and passes. 6) FORBIDDEN: Never generate methods with only comments as body - all test methods must have actual executable code with assertions."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }
        
        # 设置max_tokens以避免长代码被截断
        if max_tokens is not None:
            data["max_tokens"] = max_tokens
        else:
            # 默认设置较大的token限制，确保长代码不被截断
            # DeepSeek API最大支持8192 tokens，设置8000作为安全值
            data["max_tokens"] = 8000
        
        # 添加重试逻辑
        max_retries = 5  # 增加重试次数到5次
        retry_delay = 5  # 增加初始延迟到5秒
        
        for attempt in range(max_retries):
            try:
                print(f"LLM API调用 (尝试 {attempt + 1}/{max_retries})...")
                response = requests.post(url, headers=headers, json=data, timeout=self.api["timeout"])
                
                if response.status_code == 200:
                    response_data = response.json()
                    generated_text = response_data["choices"][0]["message"]["content"]
                    
                    # 提取代码块
                    code_pattern = r"```java\s*([\s\S]*?)\s*```"
                    code_matches = re.findall(code_pattern, generated_text)
                    
                    # 成功后等待较短时间，避免频率限制
                    print("✅ LLM API调用成功")
                    time.sleep(3)  # 减少到3秒
                    
                    if code_matches:
                        # 返回第一个代码块
                        return code_matches[0].strip()
                    else:
                        # 如果没有找到代码块，返回原始文本
                        return generated_text.strip()
                else:
                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_detail = response.json().get('error', {}).get('message', response.text)
                        error_msg += f": {error_detail}"
                    except:
                        error_msg += f": {response.text[:200]}"
                    
                    print(f"LLM API调用失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")
                    
                    # 如果是速率限制错误或服务器错误，重试；其他错误直接返回
                    if response.status_code in [429, 500, 502, 503, 504]:
                        if attempt < max_retries - 1:  # 不是最后一次尝试
                            wait_time = retry_delay * (2 ** attempt)  # 指数退避
                            print(f"等待 {wait_time} 秒后重试...")
                            time.sleep(wait_time)
                            continue
                    else:
                        # 客户端错误，不重试
                        return ""
                    
            except requests.exceptions.Timeout:
                print(f"LLM API调用失败 (尝试 {attempt + 1}/{max_retries}): 请求超时 ({self.api['timeout']}秒)")
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
            except requests.exceptions.ConnectionError as e:
                print(f"LLM API调用失败 (尝试 {attempt + 1}/{max_retries}): 连接错误 - {str(e)[:100]}")
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
            except Exception as e:
                print(f"LLM API调用失败 (尝试 {attempt + 1}/{max_retries}): 未知错误 - {str(e)[:100]}")
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
        
        print(f"达到最大重试次数 {max_retries}，API调用失败")
        return "" 