"""
Java错误类别定义

只包含能够精确匹配和修复的错误类别
每个类别都经过验证，确保高成功率的自动修复
"""

# Java错误类别及对应的正则表达式匹配模式
# 只保留真正有效的错误类型
ERROR_CATEGORIES = {
  # 导入错误 - 处理方式：添加或移除导入
  # 这类错误最容易精确匹配和修复
  "IMPORT_ERRORS": [
    r"Unused\s+import:\s+([^\s;]+)",
    r"unused\s+import\s+([^\s;]+)",
    r"duplicate\s+import:\s+([^\s;]+)",
    r"repeated\s+import:\s+([^\s;]+)",
    # 中文错误消息
    r"未使用的导入:\s+([^\s;]+)",
    r"未使用的导入\s+([^\s;]+)",
    r"重复的导入:\s+([^\s;]+)",
    r"重复导入:\s+([^\s;]+)"
  ],
  
  # 重复定义错误 - 处理方式：移除重复的修饰符、注解、导入
  # 限制为真正能修复的重复问题
  "DUPLICATE_DEFINITION_ERRORS": [
    r"repeated\s+modifier\s+(\w+)",
    r"duplicate\s+modifier\s+(\w+)",
    r"repeated\s+annotation\s+(\w+)",
    r"duplicate\s+annotation\s+(\w+)",
    r"(\w+)\s+的\s+single-type-import\s+已定义具有相同简名的类型",
    # 中文错误消息
    r"重复的修饰符\s+(\w+)",
    r"重复的注释\s+(\w+)",
    r"重复的注解\s+(\w+)"
  ],
  
  # 访问修饰符错误 - 处理方式：移除重复的访问修饰符
  # 只处理明确的重复修饰符问题
  "ACCESS_MODIFIER_ERRORS": [
    r"repeated\s+modifier\s+(\w+)",
    r"duplicate\s+modifier\s+(\w+)",
    # 中文错误消息
    r"重复的修饰符\s+(\w+)"
  ],
  
  # API兼容性错误 - 处理方式：替换不兼容的API调用
  # 主要针对Java版本兼容性和库版本兼容性问题
  "API_COMPATIBILITY_ERRORS": [
    r"cannot find symbol:\s*variable\s+(\w+).*StandardCharsets",
    r"cannot find symbol:\s*method\s+([^(]+).*CSVFormat",
    r"cannot find symbol:\s*method\s+repeat\(",
    r"cannot find symbol:\s*method\s+([^(]+).*builder\(\)",
    r"cannot find symbol:\s*class\s+Path.*java\.nio\.file\.Path",
    r"cannot find symbol:\s*method\s+of\(",
    # 通用的API不存在错误模式
    r"cannot find symbol:\s*method\s+([^(]+)",
    r"cannot find symbol:\s*variable\s+([^\s,]+)",
    r"package\s+([^\s]+)\s+does not exist"
  ],
  
  # 私有访问错误 - 处理方式：移除私有方法调用或替换为公共方法
  # 这是编译错误修复失败的主要原因
  "PRIVATE_ACCESS_ERRORS": [
    r"(\w+)(?:\(\))? has private access in (\w+)",
    r"(\w+)(?:\(\))? has protected access in (\w+)",
    r"(\w+)(?:\(\))? is not public in (\w+)",
    # 中文错误消息
    r"(\w+) 在 (\w+) 中是私有访问",
    r"(\w+) 在 (\w+) 中具有受保护访问权限"
  ],
  
  # 构造器错误 - 处理方式：修复构造器调用或移除
  "CONSTRUCTOR_ERRORS": [
    r"no suitable constructor found for (\w+)",
    r"cannot find symbol:\s*constructor\s+(\w+)",
    r"constructor (\w+) cannot be applied to",
    r"(\w+)\(\) is undefined",
    r"The constructor (\w+)\(.*\) is undefined",
    # 新增：处理构造函数声明错误
    r"invalid method declaration[;,]?\s*return type required",
    r"constructor.*(?:name|return type)",
    r"(?:constructor|method)\s+(?:declaration|signature).*(?:invalid|incorrect)"
  ],
  
  # 资源管理错误 - 处理方式：修复try-with-resources语法
  "RESOURCE_MANAGEMENT_ERRORS": [
    r"try-with-resources not applicable to",
    r"try-with-resources.*not applicable",
    r"resource.*not applicable",
    r"auto-closeable resource.*not applicable"
  ]
} 