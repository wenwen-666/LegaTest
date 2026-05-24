"""
测试执行模块
负责运行Maven测试、生成JaCoCo和Surefire报告
"""

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
from typing import List, Optional, Tuple
from pathlib import Path

class TestExecutor:
    """测试执行器，负责运行单个测试类并生成基础报告"""
    
    def __init__(self, base_dir: str, project_name: str):
        """
        初始化测试执行器
        
        Args:
            base_dir: 项目基础目录（通常是包含dataset目录的父目录）
            project_name: 项目名称
        """
        self.base_dir = Path(base_dir).resolve()
        self.project_name = project_name
        self.dataset_dir = self.base_dir / "dataset"
        self.project_dir = self.dataset_dir / project_name
    
    def get_maven_command(self) -> str:
        """
        获取Maven命令路径
        优先使用环境变量 MAVEN_CMD，否则从 PATH 查找 Maven。
        """
        env_maven = os.environ.get("MAVEN_CMD")
        if env_maven:
            return env_maven

        path_maven = shutil.which("mvn.cmd" if os.name == 'nt' else "mvn")
        return path_maven or ("mvn.cmd" if os.name == 'nt' else "mvn")
    
    def execute_maven_command(self, command: List[str], description: str = "Maven命令") -> Optional[subprocess.CompletedProcess]:
        """执行Maven命令"""
        print(f"执行: {description}")
        
        mvn_cmd = self.get_maven_command()
        env = os.environ.copy()
        
        try:
            result = subprocess.run(
                [mvn_cmd] + command,
                cwd=str(self.project_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=300,  # 5分钟超时，可根据项目大小调整
                env=env
            )
            
            # 打印输出（可根据需要调整详细程度）
            if result.stdout:
                print(f"stdout: {result.stdout[:500]}...")  # 只打印前500字符
            if result.stderr:
                print(f"stderr: {result.stderr[:500]}...")
                
            return result
        except subprocess.TimeoutExpired:
            print(f"命令执行超时: {description}")
            return None
        except Exception as e:
            print(f"执行命令时出错: {e}")
            return None
    
    def extract_target_class_name(self, test_class_name: str) -> str:
        """
        从测试类名称中提取目标类名称
        支持多种命名格式
        """
        # 格式1: ClassNameTestVN -> ClassName
        match = re.match(r"(.+?)TestV\d+$", test_class_name)
        if match:
            return match.group(1)
        
        # 格式2: ClassNameTest_Crossover_GenXX -> ClassName
        if "Test_Crossover_Gen" in test_class_name:
            return test_class_name.split("Test_Crossover_Gen")[0]
        
        # 格式3: ClassNameTest_Mutation_GenXX -> ClassName
        if "Test_Mutation_Gen" in test_class_name:
            return test_class_name.split("Test_Mutation_Gen")[0]
        
        # 默认处理：移除Test后缀
        return test_class_name.replace("Test", "")
    
    def find_class_file(self, target_class: str) -> Tuple[Optional[str], Optional[str]]:
        """
        查找目标类文件及其包路径
        
        Returns:
            Tuple[class_path, package_path]: 类文件路径和包路径
        """
        main_src_root = self.project_dir / "src" / "main" / "java"
        
        if not main_src_root.exists():
            print(f"源代码目录不存在: {main_src_root}")
            return None, None
        
        # 递归查找目标类文件
        for java_file in main_src_root.rglob(f"{target_class}.java"):
            class_path = str(java_file)
            # 计算相对于src/main/java的包路径
            relative_path = java_file.relative_to(main_src_root)
            package_path = "/".join(relative_path.parent.parts)
            return class_path, package_path
        
        return None, None
    
    def filter_jacoco_report(self, src_xml: str, dst_xml: str, target_class: str, package_path: Optional[str] = None) -> bool:
        """
        过滤 JaCoCo XML 报告，仅包含目标类
        这样可以针对目标类进行覆盖率分析
        """
        try:
            src_path = Path(src_xml)
            if not src_path.exists():
                print(f"源 XML 文件未找到: {src_xml}")
                return False
            
            tree = ET.parse(str(src_path))
            root = tree.getroot()
            
            # 创建新的报告根节点
            new_root = ET.Element("report", {"name": f"Coverage Report for {target_class}"})
            
            # 复制会话信息
            for session in root.findall("sessioninfo"):
                new_root.append(session)
            
            # 查找目标类
            target_class_found = False
            target_classes = []
            
            # 在所有包中搜索目标类及其内部类
            for package in root.findall("package"):
                for class_elem in package.findall("class"):
                    class_name = class_elem.get("name", "")
                    simple_name = class_name.split("/")[-1]
                    
                    # 匹配目标类或其内部类
                    if (simple_name == target_class or 
                        simple_name.startswith(f"{target_class}$") or 
                        class_name.endswith(f"/{target_class}")):
                        target_classes.append((package, class_elem))
                        target_class_found = True
            
            if not target_class_found:
                print(f"在JaCoCo报告中未找到目标类 {target_class}")
                return False
            
            # 处理每个包含目标类的包
            processed_packages = {}
            for package, class_elem in target_classes:
                package_name = package.get("name", "")
                
                if package_name not in processed_packages:
                    new_package = ET.SubElement(new_root, "package", {"name": package_name})
                    processed_packages[package_name] = new_package
                else:
                    new_package = processed_packages[package_name]
                
                # 添加类元素（深拷贝）
                new_package.append(class_elem)
                
                # 添加对应的源文件元素
                source_file = class_elem.get("sourcefilename")
                if source_file:
                    for sf in package.findall(f"sourcefile[@name='{source_file}']"):
                        # 检查是否已经添加了这个源文件
                        if not new_package.findall(f"sourcefile[@name='{source_file}']"):
                            new_package.append(sf)
            
            # 计算总体计数器（汇总所有目标类的指标）
            counter_types = ["INSTRUCTION", "BRANCH", "LINE", "COMPLEXITY", "METHOD", "CLASS"]
            for counter_type in counter_types:
                missed = 0
                covered = 0
                
                for _, class_elem in target_classes:
                    for counter in class_elem.findall(f"counter[@type='{counter_type}']"):
                        missed += int(counter.get("missed", "0"))
                        covered += int(counter.get("covered", "0"))
                
                # 添加总体计数器
                counter = ET.SubElement(new_root, "counter")
                counter.set("type", counter_type)
                counter.set("missed", str(missed))
                counter.set("covered", str(covered))
            
            # 保存格式化的XML文件
            self._save_pretty_xml(new_root, dst_xml)
            
            print(f"✅ 成功创建针对{target_class}类的过滤JaCoCo报告")
            return True
        
        except Exception as e:
            print(f"过滤JaCoCo报告时出错: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _save_pretty_xml(self, root_element: ET.Element, output_path: str):
        """保存格式化的XML文件"""
        xml_str = ET.tostring(root_element, encoding='utf-8')
        dom = minidom.parseString(xml_str)
        pretty_xml = dom.toprettyxml(indent="  ")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n')
            f.write('<!DOCTYPE report PUBLIC "-//JACOCO//DTD Report 1.1//EN" "report.dtd">\n')
            # 跳过minidom添加的XML声明行
            lines = pretty_xml.split('\n')[1:]
            f.write('\n'.join(lines))
    
    def run_test_and_generate_reports(self, test_class_name: str, generation: Optional[int] = None) -> bool:
        """
        运行单个测试类并生成基础报告
        
        Args:
            test_class_name: 测试类名称
            generation: 世代号（可选）
            
        Returns:
            bool: 是否成功生成报告
        """
        print(f"\\n处理测试类: {test_class_name}")
        
        # 提取目标类名
        target_class = self.extract_target_class_name(test_class_name)
        print(f"推断出的目标类名: {target_class}")
        
        # 查找目标类文件
        target_class_path, package_path = self.find_class_file(target_class)
        
        if not target_class_path:
            print(f"❌ 找不到目标类文件 {target_class}.java，跳过测试执行")
            return False
        
        print(f"✅ 找到目标类文件: {target_class_path}")
        print(f"目标类包路径: {package_path}")
        
        # 执行Maven命令序列
        success = self._execute_test_sequence(test_class_name)
        if not success:
            print(f"❌ Maven测试执行失败")
            return False
        
        # 收集和处理报告
        return self._collect_and_process_reports(test_class_name, target_class, package_path, generation)
    
    def _execute_test_sequence(self, test_class_name: str) -> bool:
        """执行Maven测试命令序列"""
        # 在一个命令中完成清理、测试和报告生成，避免中间步骤删除报告
        result = self.execute_maven_command(
            ["clean", "test", f"-Dtest={test_class_name}", "-Dmaven.test.failure.ignore=true", "jacoco:report"], 
            description=f"运行测试 {test_class_name} 并生成 JaCoCo 报告"
        )
        if result and result.returncode != 0:
            print("警告: 测试执行或报告生成可能失败，但继续处理")
        
        return True
    
    def _collect_and_process_reports(self, test_class_name: str, target_class: str, package_path: str, generation: Optional[int]) -> bool:
        """收集和处理测试报告"""
        # 确定报告存储目录
        if generation:
            test_report_dir = Path(self.base_dir) / "test_reports" / self.project_name / f"Gen{generation}" / test_class_name
        else:
            test_report_dir = Path(self.base_dir) / "test_reports" / self.project_name / "Gen1" / test_class_name
        
        # 清理并创建目录
        if test_report_dir.exists():
            shutil.rmtree(str(test_report_dir), ignore_errors=True)
        
        jacoco_dst = test_report_dir / "jacoco"
        surefire_dst = test_report_dir / "surefire"
        
        jacoco_dst.mkdir(parents=True, exist_ok=True)
        surefire_dst.mkdir(parents=True, exist_ok=True)
        
        # 处理JaCoCo报告
        jacoco_success = self._process_jacoco_reports(target_class, package_path, jacoco_dst)
        
        # 处理Surefire报告
        surefire_success = self._process_surefire_reports(test_class_name, surefire_dst)
        
        if jacoco_success:
            print(f"✅ 报告已收集到: {test_report_dir}")
        
        return jacoco_success
    
    def _process_jacoco_reports(self, target_class: str, package_path: str, jacoco_dst: Path) -> bool:
        """处理JaCoCo报告"""
        # 检查多个可能的JaCoCo报告位置
        possible_locations = [
            self.project_dir / "target" / "site" / "jacoco" / "jacoco.xml",
            self.project_dir / "target" / "jacoco" / "jacoco.xml", 
            self.project_dir / "target" / "site" / "jacoco-ut" / "jacoco.xml"
        ]
        
        jacoco_xml_src = None
        jacoco_src = None
        
        for location in possible_locations:
            if location.exists():
                jacoco_xml_src = location
                jacoco_src = location.parent
                print(f"✅ 找到JaCoCo XML报告: {jacoco_xml_src}")
                break
        
        if not jacoco_xml_src:
            print(f"❌ 未找到JaCoCo XML报告，检查了以下位置:")
            for location in possible_locations:
                print(f"   - {location}")
            return False
        
        jacoco_xml_dst = jacoco_dst / "jacoco.xml"
        
        # 过滤XML报告，只保留目标类
        jacoco_filtered = self.filter_jacoco_report(
            str(jacoco_xml_src), str(jacoco_xml_dst), target_class, package_path
        )
        
        if not jacoco_filtered:
            return False
        
        print(f"✅ 已过滤JaCoCo报告，只保留{target_class}类的数据")
        
        # 复制JaCoCo资源文件
        self._copy_jacoco_resources(jacoco_src, jacoco_dst)
        
        # 复制目标类的HTML报告
        self._copy_target_class_html(jacoco_src, jacoco_dst, target_class, package_path)
        
        return True
    
    def _copy_jacoco_resources(self, jacoco_src: Path, jacoco_dst: Path):
        """复制JaCoCo资源文件"""
        resources_src = jacoco_src / "jacoco-resources"
        resources_dst = jacoco_dst / "jacoco-resources"
        
        if resources_src.exists():
            if resources_dst.exists():
                shutil.rmtree(str(resources_dst))
            shutil.copytree(str(resources_src), str(resources_dst))
    
    def _copy_target_class_html(self, jacoco_src: Path, jacoco_dst: Path, target_class: str, package_path: str):
        """复制目标类的HTML报告"""
        if not package_path:
            return
        
        pkg_dir = package_path.replace("/", ".")
        src_pkg_dir = jacoco_src / pkg_dir
        dst_pkg_dir = jacoco_dst / pkg_dir
        
        if not src_pkg_dir.exists():
            print(f"包目录不存在: {src_pkg_dir}")
            return
        
        dst_pkg_dir.mkdir(parents=True, exist_ok=True)
        
        # 复制与目标类相关的HTML文件
        copied_files = 0
        for file_path in src_pkg_dir.iterdir():
            if file_path.is_file():
                file_name = file_path.name
                if (file_name.startswith(f"{target_class}.") or 
                    file_name.startswith(f"{target_class}$")):
                    shutil.copy2(str(file_path), str(dst_pkg_dir / file_name))
                    copied_files += 1
        
        if copied_files > 0:
            print(f"✅ 已复制 {copied_files} 个目标类HTML文件")
    
    def _process_surefire_reports(self, test_class_name: str, surefire_dst: Path) -> bool:
        """处理Surefire报告"""
        surefire_src = self.project_dir / "target" / "surefire-reports"
        
        if not surefire_src.exists():
            print(f"⚠️ Surefire报告目录不存在: {surefire_src}")
            return False
        
        copied_files = 0
        for file_path in surefire_src.iterdir():
            if test_class_name in file_path.name:
                dst_path = surefire_dst / file_path.name
                
                if file_path.is_dir():
                    if dst_path.exists():
                        shutil.rmtree(str(dst_path))
                    shutil.copytree(str(file_path), str(dst_path))
                else:
                    shutil.copy2(str(file_path), str(dst_path))
                copied_files += 1
        
        if copied_files > 0:
            print(f"✅ 已复制 {copied_files} 个Surefire测试报告文件")
            return True
        else:
            print(f"⚠️ 未找到与{test_class_name}相关的Surefire报告")
            return False
    
    def run_tests_and_generate_reports(self, test_classes: List[str], generation: Optional[int] = None) -> bool:
        """
        运行多个测试类并生成报告
        
        Args:
            test_classes: 测试类名称列表
            generation: 世代号（可选）
            
        Returns:
            bool: 是否成功生成所有报告
        """
        print(f"开始为{len(test_classes)}个测试类生成报告...")
        
        success_count = 0
        for test_class in test_classes:
            if self.run_test_and_generate_reports(test_class, generation):
                success_count += 1
            else:
                print(f"❌ 测试类 {test_class} 报告生成失败")
        
        print(f"报告生成完成: {success_count}/{len(test_classes)} 个测试类成功")
        return success_count == len(test_classes)
