"""
类型分析模块，负责Java类型分析和推断
"""

import re
import logging
from typing import Dict, Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

class TypeAnalyzer:
    """Java类型分析器"""
    
    def __init__(self):
        """初始化类型分析器"""
        # 基本类型映射
        self.primitive_types = {
            "byte": "Byte",
            "short": "Short",
            "int": "Integer",
            "long": "Long",
            "float": "Float",
            "double": "Double",
            "boolean": "Boolean",
            "char": "Character",
            "void": "Void"
        }
        
        # 常用集合类型
        self.collection_types = {
            "List": "ArrayList",
            "Set": "HashSet",
            "Map": "HashMap",
            "Queue": "LinkedList",
            "Deque": "ArrayDeque"
        }
        
        # 常见测试数据类型
        self.test_data_types = {
            "String": ['""', '"test"', '"hello world"', "null", '"特殊字符!@#$%"'],
            "Integer": ["0", "1", "-1", "Integer.MAX_VALUE", "Integer.MIN_VALUE"],
            "Long": ["0L", "1L", "-1L", "Long.MAX_VALUE", "Long.MIN_VALUE"],
            "Double": ["0.0", "1.0", "-1.0", "Double.MAX_VALUE", "Double.MIN_VALUE", "Double.POSITIVE_INFINITY"],
            "Boolean": ["true", "false"],
            "Character": ["'a'", "'Z'", "'0'", "' '", "'\\n'"],
            "byte[]": ["new byte[0]", "new byte[]{1, 2, 3}"],
            "Object": ["null", "new Object()"],
            "Class": ["Object.class", "String.class"]
        }
        
    def analyze_type(self, type_str: str) -> Dict[str, Any]:
        """
        分析Java类型
        
        Args:
            type_str: 类型字符串
            
        Returns:
            类型信息字典
        """
        # 移除泛型中的空格
        type_str = re.sub(r'\s*([<,>])\s*', r'\1', type_str)
        
        # 基本分析结果
        result = {
            "original": type_str,
            "is_primitive": False,
            "is_array": False,
            "is_collection": False,
            "has_generics": False,
            "wrapper_type": None,
            "component_type": None,
            "generic_types": [],
            "dimension": 0
        }
        
        # 处理数组
        if '[]' in type_str:
            result["is_array"] = True
            result["dimension"] = type_str.count('[]')
            base_type = type_str.replace('[]', '')
            result["component_type"] = base_type
            type_str = base_type
            
        # 处理泛型
        if '<' in type_str:
            result["has_generics"] = True
            base_type, generic_types = self._parse_generics(type_str)
            result["generic_types"] = generic_types
            type_str = base_type
            
        # 处理基本类型
        if type_str.lower() in self.primitive_types:
            result["is_primitive"] = True
            result["wrapper_type"] = self.primitive_types[type_str.lower()]
            
        # 处理集合类型
        if type_str in self.collection_types:
            result["is_collection"] = True
            result["implementation"] = self.collection_types[type_str]
            
        return result
        
    def _parse_generics(self, type_str: str) -> Tuple[str, List[str]]:
        """
        解析泛型类型
        
        Args:
            type_str: 带泛型的类型字符串
            
        Returns:
            基本类型和泛型类型列表的元组
        """
        # 提取基本类型
        base_type = type_str[:type_str.index('<')]
        
        # 提取泛型参数
        generic_part = type_str[type_str.index('<')+1:type_str.rindex('>')]
        
        # 处理嵌套泛型
        generic_types = []
        current = ""
        nested = 0
        
        for char in generic_part:
            if char == '<':
                nested += 1
                current += char
            elif char == '>':
                nested -= 1
                current += char
            elif char == ',' and nested == 0:
                generic_types.append(current.strip())
                current = ""
            else:
                current += char
                
        if current:
            generic_types.append(current.strip())
            
        return base_type, generic_types
        
    def suggest_test_values(self, type_info: Dict[str, Any]) -> List[str]:
        """
        为给定类型建议测试值
        
        Args:
            type_info: 类型信息
            
        Returns:
            建议的测试值列表
        """
        values = []
        
        # 处理基本类型
        if type_info["is_primitive"]:
            wrapper = type_info["wrapper_type"]
            if wrapper in self.test_data_types:
                values.extend([str(v) for v in self.test_data_types[wrapper]])
                
        # 处理数组
        elif type_info["is_array"]:
            component = type_info["component_type"]
            values.extend([
                "null",
                f"new {component}[0]",
                f"new {component}[1]",
                f"new {component}[]{{{self._get_default_value(component)}}}"
            ])
            
        # 处理集合
        elif type_info["is_collection"]:
            impl = type_info["implementation"]
            if type_info["has_generics"]:
                generic = type_info["generic_types"][0]
                values.extend([
                    "null",
                    f"new {impl}<{generic}>()",
                    f"new {impl}<{generic}>(Arrays.asList({self._get_default_value(generic)}))"
                ])
            else:
                values.extend([
                    "null",
                    f"new {impl}()",
                    f"new {impl}(Collections.emptyList())"
                ])
                
        # 处理其他对象类型
        else:
            values.extend([
                "null",
                f"new {type_info['original']}()"
            ])
            
        return values
        
    def _get_default_value(self, type_str: str) -> str:
        """获取类型的默认值"""
        if type_str in self.primitive_types:
            if type_str == "boolean":
                return "false"
            elif type_str in ["char"]:
                return "'\\0'"
            elif type_str in ["float", "double"]:
                return "0.0"
            else:
                return "0"
        return "null"
        
    def is_testable_type(self, type_str: str) -> bool:
        """
        判断类型是否可测试
        
        Args:
            type_str: 类型字符串
            
        Returns:
            如果类型可测试则返回True
        """
        # 分析类型
        type_info = self.analyze_type(type_str)
        
        # 基本类型和包装类型总是可测试的
        if type_info["is_primitive"] or type_str in self.primitive_types.values():
            return True
            
        # 数组类型，如果其组件类型可测试则可测试
        if type_info["is_array"]:
            return self.is_testable_type(type_info["component_type"])
            
        # 集合类型，如果其泛型参数可测试则可测试
        if type_info["is_collection"] and type_info["has_generics"]:
            return all(self.is_testable_type(t) for t in type_info["generic_types"])
            
        # 其他类型需要有公共构造函数或工厂方法
        # TODO: 实现更复杂的类型可测试性分析
        return True
        
    def get_assertion_method(self, type_str: str) -> str:
        """
        获取适合该类型的断言方法
        
        Args:
            type_str: 类型字符串
            
        Returns:
            断言方法名
        """
        type_info = self.analyze_type(type_str)
        
        if type_info["is_primitive"]:
            if type_str == "float" or type_str == "double":
                return "assertEquals"  # 需要delta参数
            return "assertEquals"
        elif type_info["is_array"]:
            return "assertArrayEquals"
        elif type_str == "String":
            return "assertEquals"
        elif type_info["is_collection"]:
            return "assertEquals"  # 可能需要自定义比较器
        else:
            return "assertEquals"  # 可能需要重写equals方法
            
    def get_mock_strategy(self, type_str: str) -> Dict[str, Any]:
        """
        获取类型的Mock策略
        
        Args:
            type_str: 类型字符串
            
        Returns:
            Mock策略信息
        """
        type_info = self.analyze_type(type_str)
        
        strategy = {
            "can_mock": True,
            "mock_framework": "Mockito",
            "mock_method": "mock",
            "verification_needed": False
        }
        
        # 基本类型不能直接mock
        if type_info["is_primitive"]:
            strategy["can_mock"] = False
            strategy["alternative"] = "Use actual values"
            
        # 数组使用spy
        elif type_info["is_array"]:
            strategy["mock_method"] = "spy"
            strategy["mock_code"] = f"{type_str} spy = spy(new {type_str}())"
            
        # 接口和抽象类
        elif type_str.startswith("I") or "Abstract" in type_str:
            strategy["verification_needed"] = True
            strategy["mock_code"] = f"{type_str} mock = mock({type_str}.class)"
            
        # 集合类型
        elif type_info["is_collection"]:
            strategy["mock_method"] = "spy"
            strategy["mock_code"] = f"{type_str} spy = spy(new {type_info['implementation']}())"
            
        return strategy

# 创建全局类型分析器实例
type_analyzer = TypeAnalyzer()

# 为了保持API兼容性，提供与原版相同的函数接口
def analyze_type(type_str: str) -> Dict[str, Any]:
    """分析类型的全局函数"""
    return type_analyzer.analyze_type(type_str)
    
def suggest_test_values(type_info: Dict[str, Any]) -> List[str]:
    """建议测试值的全局函数"""
    return type_analyzer.suggest_test_values(type_info)
    
def is_testable_type(type_str: str) -> bool:
    """判断类型是否可测试的全局函数"""
    return type_analyzer.is_testable_type(type_str)
    
def get_assertion_method(type_str: str) -> str:
    """获取断言方法的全局函数"""
    return type_analyzer.get_assertion_method(type_str)
    
def get_mock_strategy(type_str: str) -> Dict[str, Any]:
    """获取Mock策略的全局函数"""
    return type_analyzer.get_mock_strategy(type_str) 