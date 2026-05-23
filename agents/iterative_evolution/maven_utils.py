"""
Maven验证工具模块
"""
import re
import os
import subprocess
import time
from typing import Tuple

def run_maven_test(project_dir: str, test_class: str, profile: str = None) -> Tuple[str, bool]:
    """
    在指定项目目录执行特定的测试类
    
    Args:
        project_dir: Maven项目目录(包含pom.xml的目录)
        test_class: 要执行的测试类名
        profile: 可选，Maven profile名称
        
    Returns:
        (输出结果, 是否成功)
    """
    try:
        # 处理项目路径
        project_dir = os.path.abspath(project_dir)
        print(f"使用项目路径: {project_dir}")
        
        # 确保项目目录存在且包含pom.xml
        if not os.path.exists(project_dir):
            print(f"项目路径不存在: {project_dir}")
            return f"项目路径不存在: {project_dir}", False
            
        pom_path = os.path.join(project_dir, "pom.xml")
        if not os.path.exists(pom_path):
            print(f"pom.xml不存在: {pom_path}")
            return f"pom.xml不存在: {pom_path}", False
        
        # 切换到项目目录
        original_dir = os.getcwd()
        os.chdir(project_dir)
        
        # 构建Maven命令 - 执行测试并生成JaCoCo覆盖率报告
        cmd_str = f'mvn clean test "-Dtest={test_class}" "-Dmaven.test.failure.ignore=true" jacoco:report'
        if profile:
            cmd_str += f' "-P{profile}"'
        
        print(f"执行命令: {cmd_str} (在目录: {project_dir})")
        start_time = time.time()
        
        # 设置环境变量，确保Maven使用UTF-8编码
        env = os.environ.copy()
        env['JAVA_TOOL_OPTIONS'] = '-Dfile.encoding=UTF-8'
        
        # 使用subprocess.run直接执行命令，允许输出直接显示在终端
        try:
            # 直接使用subprocess.run，实时显示输出
            import tempfile
            with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as stdout_file, \
                 tempfile.TemporaryFile(mode='w+', encoding='utf-8') as stderr_file:
                
                # 创建进程，同时输出到终端和临时文件
                process = subprocess.Popen(
                    cmd_str,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    bufsize=1,  # 行缓冲
                    universal_newlines=True,  # 文本模式
                    encoding='utf-8',  # UTF-8编码
                    errors='replace'  # 替换无法解码的字符
                )
                
                # 实时读取并显示输出
                all_output = []
                for line in iter(process.stdout.readline, ''):
                    print(line, end='')  # 实时打印到终端
                    all_output.append(line)
                    stdout_file.write(line)
                
                # 读取错误输出
                for line in iter(process.stderr.readline, ''):
                    print(line, end='')  # 实时打印到终端
                    all_output.append(line)
                    stderr_file.write(line)
                
                # 等待进程完成
                process.stdout.close()
                process.stderr.close()
                return_code = process.wait()
                
                # 重置文件指针并读取所有输出
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout_content = stdout_file.read()
                stderr_content = stderr_file.read()
                
                # 合并输出
                output = ''.join(all_output)
                
        except Exception as e:
            print(f"执行命令时出错: {e}")
            import traceback
            print(traceback.format_exc())
            output = f"执行命令时出错: {e}"
            return_code = 1
        
        # 恢复原始目录
        os.chdir(original_dir)
        
        # 修改构建成功的判断逻辑
        # 只有在输出中包含"BUILD SUCCESS"且没有测试失败时才视为成功
        success = "BUILD SUCCESS" in output
        
        # 检查是否有测试失败
        if success and any(x in output for x in ["Tests run:", "Failures:", "Errors:"]):
            # 如果有测试运行信息，检查是否有失败或错误
            test_failure_pattern = r'Tests run: \d+, Failures: ([1-9]\d*), Errors: (\d+)'
            test_error_pattern = r'Tests run: \d+, Failures: (\d+), Errors: ([1-9]\d*)'
            
            failure_match = re.search(test_failure_pattern, output)
            error_match = re.search(test_error_pattern, output)
            
            if failure_match or error_match:
                # 有测试失败或错误，视为构建失败
                success = False
                print("BUILD SUCCESS但存在测试失败或错误，视为失败")
        
        # 记录命令输出，便于调试
        print(f"Maven命令输出 (前500字符): {output[:500]}")
        if not success:
            print(f"Maven命令失败，返回码: {return_code}")
        
        execution_time = time.time() - start_time
        print(f"命令执行完成，耗时 {execution_time:.2f}秒, 状态: {'成功' if success else '失败'}")
        
        return output, success
    except subprocess.TimeoutExpired:
        print("命令执行超时")
        return "命令执行超时", False
    except Exception as e:
        print(f"执行命令失败: {e}")
        import traceback
        print(traceback.format_exc())
        return str(e), False