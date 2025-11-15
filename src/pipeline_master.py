#!/usr/bin/env python3
"""
AuViMa Pipeline Master Controller
主控制器 - 管理整个视频生成流程
"""

import os
import sys
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
import psutil


class PipelineMaster:
    def __init__(self, topic: str, project_name: str):
        self.topic = topic
        self.project_name = project_name
        self.base_dir = Path("/Users/chagee/Repos/AuViMa")
        self.project_dir = self.base_dir / "projects" / project_name
        self.chrome_process = None
        
        # 创建项目目录结构
        self.setup_project_dirs()
        
        # 标记文件定义
        self.markers = {
            "start": self.project_dir / "start.done",
            "storyboard": self.project_dir / "storyboard.done", 
            "generate": self.project_dir / "generate.done",
            "evaluate": self.project_dir / "evaluate.done",
            "merge": self.project_dir / "merge.done"
        }
        
        # 日志配置
        self.log_file = self.project_dir / "pipeline.log"
        self.start_time = datetime.now()
        
    def setup_project_dirs(self):
        """创建项目目录结构"""
        dirs_to_create = [
            self.project_dir / "research" / "screenshots",
            self.project_dir / "shots",
            self.project_dir / "clips",
            self.project_dir / "outputs",
            self.project_dir / "logs"
        ]
        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        self.log(f"项目目录已创建: {self.project_dir}")
    
    def log(self, message: str):
        """记录日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        print(log_message)
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_message + '\n')
    
    def start_chrome(self):
        """启动Chrome CDP"""
        self.log("启动Chrome CDP...")
        
        # 检查Chrome是否已经运行
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and '--remote-debugging-port=9222' in str(cmdline):
                    self.log("Chrome CDP已在运行")
                    return True
            except:
                pass
        
        # 启动Chrome
        chrome_script = self.base_dir / "src" / "chrome_cdp_launcher_v2.py"
        if chrome_script.exists():
            self.chrome_process = subprocess.Popen(
                [sys.executable, str(chrome_script)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(5)  # 等待Chrome启动
            self.log("Chrome CDP已启动")
            return True
        else:
            self.log("错误: 找不到Chrome启动脚本")
            return False
    
    def wait_for_done_file(self, marker_key: str, timeout: int = 600) -> bool:
        """等待.done文件出现"""
        marker_file = self.markers[marker_key]
        self.log(f"等待 {marker_key}.done...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            if marker_file.exists():
                self.log(f"✓ {marker_key} 完成")
                # 删除标记文件
                marker_file.unlink()
                return True
            time.sleep(2)
        
        self.log(f"✗ {marker_key} 超时")
        return False
    
    def execute_claude_command(self, command: str) -> bool:
        """执行Claude Code CLI命令"""
        self.log(f"执行: {command}")
        
        try:
            # 这里模拟Claude Code CLI调用
            # 实际实现时需要替换为真实的CLI命令
            cmd_parts = command.split()
            
            # 记录命令到日志
            log_file = self.project_dir / "logs" / f"{cmd_parts[0].replace('/', '')}.log"
            
            # 执行命令（这里需要实际的Claude Code CLI路径）
            # process = subprocess.run(
            #     ["claude-code", "--mode", "cli", "--command", command],
            #     capture_output=True,
            #     text=True
            # )
            
            # 临时：创建模拟的done文件用于测试
            if "start" in command:
                self.markers["start"].touch()
            elif "storyboard" in command:
                self.markers["storyboard"].touch()
            elif "evaluate" in command:
                self.markers["evaluate"].touch()
            elif "merge" in command:
                self.markers["merge"].touch()
            
            return True
            
        except Exception as e:
            self.log(f"命令执行失败: {e}")
            return False
    
    def phase_1_start(self) -> bool:
        """阶段1: 信息收集"""
        self.log("\n=== 阶段1: 信息收集 ===")
        
        # 执行信息收集命令
        command = f'/auvima.start "{self.topic}" {self.project_name}'
        if not self.execute_claude_command(command):
            return False
        
        # 等待完成
        return self.wait_for_done_file("start")
    
    def phase_2_storyboard(self) -> bool:
        """阶段2: 分镜规划"""
        self.log("\n=== 阶段2: 分镜规划 ===")
        
        # 执行分镜规划命令
        command = f'/auvima.storyboard {self.project_name}'
        if not self.execute_claude_command(command):
            return False
        
        # 等待完成
        return self.wait_for_done_file("storyboard")
    
    def phase_3_generate(self) -> bool:
        """阶段3: 循环生成视频片段"""
        self.log("\n=== 阶段3: 视频生成循环 ===")
        
        # 获取分镜文件列表
        shots_dir = self.project_dir / "shots"
        shot_files = sorted(shots_dir.glob("shot_*.json"))
        
        if not shot_files:
            self.log("错误: 未找到分镜文件")
            return False
        
        self.log(f"找到 {len(shot_files)} 个分镜")
        
        # 循环处理每个分镜
        for i, shot_file in enumerate(shot_files, 1):
            self.log(f"\n[{i}/{len(shot_files)}] 处理 {shot_file.name}")
            
            # 执行生成命令
            command = f'/auvima.generate {shot_file}'
            if not self.execute_claude_command(command):
                return False
            
            # 等待单个clip完成
            clip_marker = self.project_dir / "clips" / f"{shot_file.stem}.done"
            start_time = time.time()
            while time.time() - start_time < 300:  # 5分钟超时
                if clip_marker.exists():
                    self.log(f"✓ {shot_file.stem} 完成")
                    clip_marker.unlink()
                    break
                time.sleep(2)
            else:
                self.log(f"✗ {shot_file.stem} 生成超时")
                return False
        
        # 创建总完成标记
        self.markers["generate"].touch()
        return True
    
    def phase_4_evaluate(self) -> bool:
        """阶段4: 素材评估"""
        self.log("\n=== 阶段4: 素材评估 ===")
        
        # 执行评估命令
        command = f'/auvima.evaluate {self.project_name}'
        if not self.execute_claude_command(command):
            return False
        
        # 等待完成
        return self.wait_for_done_file("evaluate")
    
    def phase_5_merge(self) -> bool:
        """阶段5: 合成最终视频"""
        self.log("\n=== 阶段5: 视频合成 ===")
        
        # 执行合成命令
        command = f'/auvima.merge {self.project_name}'
        if not self.execute_claude_command(command):
            return False
        
        # 等待完成
        return self.wait_for_done_file("merge")
    
    def cleanup(self):
        """清理环境"""
        self.log("\n=== 清理环境 ===")
        
        # 关闭Chrome
        if self.chrome_process:
            self.log("关闭Chrome...")
            self.chrome_process.terminate()
            self.chrome_process.wait()
        
        # 清理临时文件
        for marker in self.markers.values():
            if marker.exists():
                marker.unlink()
        
        self.log("清理完成")
    
    def run(self) -> bool:
        """运行完整pipeline"""
        self.log(f"{'='*50}")
        self.log(f"AuViMa Pipeline 开始")
        self.log(f"主题: {self.topic}")
        self.log(f"项目: {self.project_name}")
        self.log(f"{'='*50}")
        
        try:
            # 启动Chrome
            if not self.start_chrome():
                self.log("Chrome启动失败")
                return False
            
            # 执行各阶段
            phases = [
                ("信息收集", self.phase_1_start),
                ("分镜规划", self.phase_2_storyboard),
                ("视频生成", self.phase_3_generate),
                ("素材评估", self.phase_4_evaluate),
                ("视频合成", self.phase_5_merge)
            ]
            
            for phase_name, phase_func in phases:
                if not phase_func():
                    self.log(f"✗ {phase_name}阶段失败")
                    return False
                self.log(f"✓ {phase_name}阶段完成")
            
            # 计算总耗时
            duration = (datetime.now() - self.start_time).total_seconds()
            self.log(f"\n{'='*50}")
            self.log(f"Pipeline成功完成!")
            self.log(f"总耗时: {duration:.1f}秒")
            self.log(f"输出视频: {self.project_dir}/outputs/final_output.mp4")
            self.log(f"{'='*50}")
            
            return True
            
        except KeyboardInterrupt:
            self.log("\n用户中断")
            return False
        
        except Exception as e:
            self.log(f"\n错误: {e}")
            return False
        
        finally:
            self.cleanup()


def main():
    """主入口"""
    if len(sys.argv) < 2:
        print("用法: python pipeline_master.py <topic> [project_name]")
        print('示例: python pipeline_master.py "分析github.com/langchain-ai/langchain" langchain_intro')
        sys.exit(1)
    
    topic = sys.argv[1]
    project_name = sys.argv[2] if len(sys.argv) > 2 else f"project_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # 运行pipeline
    pipeline = PipelineMaster(topic, project_name)
    success = pipeline.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()