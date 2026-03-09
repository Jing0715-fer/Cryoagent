"""
PyMOL Wrapper - 无头模式蛋白质结构分析
使用开源版 PyMOL (pymol-open-source) 进行后台结构分析
"""
import os
import sys
import json
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)

# PyMOL 尝试导入
try:
    import pymol
    from pymol import cmd
    PYMOL_AVAILABLE = True
except ImportError:
    logger.warning("PyMOL not available. Install with: pip install pymol-open-source")
    PYMOL_AVAILABLE = False


# 分析命令模板
ANALYSIS_COMMANDS = {
    "info": ["fetch {pdb_id}", "describe {pdb_id}"],
    "rmsd": ["fetch {pdb1}, async=0", "fetch {pdb2}, async=0",
              "align {pdb1}, {pdb2}", "rms_cur {pdb1}, {pdb2}"],
    "align": ["fetch {pdb1}, async=0", "fetch {pdb2}, async=0",
              "align {pdb1}, {pdb2}", "super {pdb1}, {pdb2}"],
    "secondary_structure": ["fetch {pdb_id}, async=0", "dss {pdb_id}",
                            "iterate (name n,c,ca), print(resi, name, ss)"],
    "contacts": ["fetch {pdb_id}", "intra_fit {pdb_id}", "dist"],
    "surface": ["fetch {pdb_id}", "show surface"],
    "electrostatics": ["fetch {pdb_id}", "set grid_mode, 1", "calculate potential"],
    "validate": ["fetch {pdb_id}", "validate_service {pdb_id}"],
}

# 可视化样式
VISUALIZATION_STYLES = {
    "cartoon": ["cartoon"],
    "sticks": ["sticks", "radius=0.15"],
    "spheres": ["spheres", "radius=0.5"],
    "surface": ["surface"],
    "ribbon": ["ribbon"],
    "line": ["lines"],
}

# 颜色方案
COLOR_SCHEMES = {
    "rainbow": "spectrum ss, rainbow",
    "chain": "util.cbc",
    "structure": "util.cbss",
    "charge": "set charge_color, magenta",
    "hydrophobicity": "spectrum b, cyan_white_magenta",
}


class PyMOLWrapper:
    """PyMOL 封装类 - 无头模式运行"""

    def __init__(self, workspace_dir: str = "pymol_sessions"):
        """
        初始化 PyMOL 封装

        Args:
            workspace_dir: 工作目录，用于保存 session 和图像文件
        """
        self.workspace_dir = workspace_dir
        self.pymol_instance = None
        self.cmd = None
        self._initialized = False

        # 创建工作目录
        os.makedirs(self.workspace_dir, exist_ok=True)

        # 如果 PyMOL 可用，初始化
        if PYMOL_AVAILABLE:
            self._initialize_pymol()

    def _initialize_pymol(self):
        """初始化 PyMOL 实例"""
        try:
            # 无头模式启动 PyMOL
            pymol.finish_launching(['pymol', '-qc'])
            self.cmd = cmd
            self._initialized = True
            logger.info("PyMOL initialized in headless mode")
        except Exception as e:
            logger.error(f"Failed to initialize PyMOL: {e}")
            self._initialized = False

    def is_available(self) -> bool:
        """检查 PyMOL 是否可用"""
        return PYMOL_AVAILABLE and self._initialized

    def _run_command(self, cmd_str: str) -> str:
        """
        执行单条 PyMOL 命令

        Args:
            cmd_str: PyMOL 命令

        Returns:
            命令执行结果
        """
        if not self.is_available():
            return "PyMOL not available"

        try:
            result = self.cmd.get_str(cmd_str)
            self.cmd.do(cmd_str)
            return result
        except Exception as e:
            logger.error(f"Error running command '{cmd_str}': {e}")
            return str(e)

    def _execute_commands(self, commands: List[str]) -> List[str]:
        """
        执行多条 PyMOL 命令

        Args:
            commands: PyMOL 命令列表

        Returns:
            所有命令的执行结果
        """
        results = []
        for cmd_str in commands:
            result = self._run_command(cmd_str)
            results.append(result)
        return results

    def fetch_structure(self, pdb_id: str) -> bool:
        """
        下载 PDB 结构

        Args:
            pdb_id: PDB ID

        Returns:
            是否成功
        """
        if not self.is_available():
            logger.warning("PyMOL not available, cannot fetch structure")
            return False

        try:
            # 清理已有对象
            self.cmd.delete(pdb_id)

            # 获取结构 - 使用 type=pdb 确保下载 PDB 格式而不是 mmCIF
            self.cmd.fetch(pdb_id, async_=0, type='pdb')
            logger.info(f"Fetched structure: {pdb_id}")
            return True
        except Exception as e:
            logger.error(f"Error fetching {pdb_id}: {e}")
            return False

    def get_structure_info(self, pdb_id: str) -> Dict:
        """
        获取结构详细信息

        Args:
            pdb_id: PDB ID

        Returns:
            结构信息字典
        """
        if not self.is_available():
            return {"error": "PyMOL not available"}

        try:
            # 确保结构已加载
            if not self.fetch_structure(pdb_id):
                return {"error": f"Failed to fetch {pdb_id}"}

            # 获取原子数量
            atom_count = self.cmd.count_atoms(pdb_id)

            # 获取残基数量 - 使用 iterate 替代 count_resi
            resi_count = 0
            try:
                self.cmd.iterate(f"({pdb_id} and name CA)", "resi_count += 1", space={'resi_count': 0})
            except:
                resi_count = atom_count // 3  # 估算

            # 获取链信息
            chains = list(self.cmd.get_chains(pdb_id))

            return {
                "pdb_id": pdb_id,
                "atom_count": atom_count,
                "residue_count": resi_count,
                "chains": chains
            }
        except Exception as e:
            logger.error(f"Error getting structure info for {pdb_id}: {e}")
            return {"error": str(e)}

    def calculate_rmsd(self, pdb_id1: str, pdb_id2: str) -> Dict:
        """
        计算两个结构的 RMSD

        Args:
            pdb_id1: 第一个 PDB ID
            pdb_id2: 第二个 PDB ID

        Returns:
            RMSD 计算结果
        """
        if not self.is_available():
            return {"error": "PyMOL not available"}

        try:
            # 清理已有对象
            self.cmd.delete(pdb_id1)
            self.cmd.delete(pdb_id2)

            # 获取两个结构 - 使用 type=pdb 确保下载 PDB 格式
            self.cmd.fetch(pdb_id1, async_=0, type='pdb')
            self.cmd.fetch(pdb_id2, async_=0, type='pdb')

            # 执行 align
            align_result = self.cmd.align(f"{pdb_id1} and name ca", f"{pdb_id2} and name ca")

            # 执行 RMS 计算
            rms_result = self.cmd.rms_cur(f"{pdb_id1} and name ca", f"{pdb_id2} and name ca")

            return {
                "pdb_id1": pdb_id1,
                "pdb_id2": pdb_id2,
                "rmsd": align_result[0] if align_result else rms_result,
                "align_rms": align_result[0] if align_result else None,
                "raw_alignment": align_result[1] if align_result else None,
                "num_aligned": align_result[2] if align_result else None
            }
        except Exception as e:
            logger.error(f"Error calculating RMSD: {e}")
            return {"error": str(e)}

    def analyze_secondary_structure(self, pdb_id: str) -> Dict:
        """
        分析二级结构

        Args:
            pdb_id: PDB ID

        Returns:
            二级结构分析结果
        """
        if not self.is_available():
            return {"error": "PyMOL not available"}

        try:
            # 确保结构已加载
            if not self.fetch_structure(pdb_id):
                return {"error": f"Failed to fetch {pdb_id}"}

            # 运行 dssp
            self.cmd.dssp(pdb_id)

            # 获取二级结构分配
            ss_data = []
            self.cmd.iterate(f"({pdb_id} and name ca)",
                            "ss_data.append({'resi': resi, 'chain': chain, 'ss': ss})",
                            space=locals())

            # 统计各类结构
            helix_count = sum(1 for s in ss_data if s['ss'] == 'H')
            sheet_count = sum(1 for s in ss_data if s['ss'] == 'S')
            loop_count = sum(1 for s in ss_data if s['ss'] == 'L' or s['ss'] == '')

            return {
                "pdb_id": pdb_id,
                "total_residues": len(ss_data),
                "helix_count": helix_count,
                "sheet_count": sheet_count,
                "loop_count": loop_count,
                "secondary_structure": ss_data[:50]  # 限制返回数量
            }
        except Exception as e:
            logger.error(f"Error analyzing secondary structure: {e}")
            return {"error": str(e)}

    def analyze_structure(self, pdb_id: str, analysis_type: str = "info") -> Dict:
        """
        执行通用结构分析

        Args:
            pdb_id: PDB ID
            analysis_type: 分析类型 (info/rmsd/secondary_structure/surface/contacts)

        Returns:
            分析结果
        """
        if analysis_type == "info":
            return self.get_structure_info(pdb_id)
        elif analysis_type == "secondary_structure":
            return self.analyze_secondary_structure(pdb_id)
        elif analysis_type == "surface":
            return self.show_surface(pdb_id)
        elif analysis_type == "contacts":
            return self.analyze_contacts(pdb_id)
        else:
            return {"error": f"Unknown analysis type: {analysis_type}"}

    def show_surface(self, pdb_id: str) -> Dict:
        """
        显示分子表面

        Args:
            pdb_id: PDB ID

        Returns:
            分析结果
        """
        if not self.is_available():
            return {"error": "PyMOL not available"}

        try:
            if not self.fetch_structure(pdb_id):
                return {"error": f"Failed to fetch {pdb_id}"}

            # 显示表面
            self.cmd.show("surface", pdb_id)
            self.cmd.color("gray", pdb_id)

            return {
                "pdb_id": pdb_id,
                "message": "Surface representation enabled"
            }
        except Exception as e:
            logger.error(f"Error showing surface: {e}")
            return {"error": str(e)}

    def analyze_contacts(self, pdb_id: str) -> Dict:
        """
        分析分子内接触

        Args:
            pdb_id: PDB ID

        Returns:
            接触分析结果
        """
        if not self.is_available():
            return {"error": "PyMOL not available"}

        try:
            if not self.fetch_structure(pdb_id):
                return {"error": f"Failed to fetch {pdb_id}"}

            # 计算接触
            self.cmd.intra_fit(pdb_id)
            self.cmd.dist(pdb_id, pdb_id, cutoff=4.0)

            # 获取接触信息
            contacts = []
            self.cmd.iterate(f"({pdb_id} and not hydro)",
                           "contacts.append({'resi': resi, 'chain': chain, 'name': name})",
                           space=locals())

            return {
                "pdb_id": pdb_id,
                "contact_count": len(contacts),
                "note": "Contact analysis completed"
            }
        except Exception as e:
            logger.error(f"Error analyzing contacts: {e}")
            return {"error": str(e)}

    def generate_image(self, pdb_id: str, style: str = "cartoon",
                      color: str = "rainbow", width: int = 800,
                      height: int = 600, format: str = "png") -> Optional[str]:
        """
        生成结构图像

        Args:
            pdb_id: PDB ID
            style: 可视化风格
            color: 颜色方案
            width: 图像宽度
            height: 图像高度
            format: 输出格式

        Returns:
            图像文件路径
        """
        if not self.is_available():
            logger.warning("PyMOL not available, cannot generate image")
            return None

        try:
            # 确保结构已加载
            if not self.fetch_structure(pdb_id):
                return None

            # 应用样式
            if style in VISUALIZATION_STYLES:
                for viz_cmd in VISUALIZATION_STYLES[style]:
                    if "=" in viz_cmd:
                        cmd_name, val = viz_cmd.split("=")
                        self.cmd.show(cmd_name, pdb_id)
                        self.cmd.set(cmd_name, val)
                    else:
                        self.cmd.show(viz_cmd, pdb_id)
            else:
                self.cmd.show("cartoon", pdb_id)

            # 应用颜色
            if color in COLOR_SCHEMES:
                self.cmd.do(COLOR_SCHEMES[color])

            # 调整视角
            self.cmd.zoom(pdb_id)
            self.cmd.center(pdb_id)

            # 生成图像路径
            output_path = os.path.join(
                self.workspace_dir,
                f"{pdb_id}_{style}_{color}.{format}"
            )

            # 渲染图像 - 禁用 ray  tracing 以提高速度
            # ray=0 使用 OpenGL 快速渲染，ray=1 使用光线追踪（慢但质量高）
            self.cmd.png(output_path, width=width, height=height, dpi=300, ray=0)

            logger.info(f"Generated image: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error generating image: {e}")
            return None

    def save_session(self, pdb_id: str, session_name: str = None) -> Optional[str]:
        """
        保存 PyMOL session 文件

        Args:
            pdb_id: PDB ID
            session_name: session 文件名（不含扩展名）

        Returns:
            session 文件路径
        """
        if not self.is_available():
            logger.warning("PyMOL not available, cannot save session")
            return None

        try:
            # 确保结构已加载
            if not self.fetch_structure(pdb_id):
                return None

            # 生成 session 文件名
            if not session_name:
                session_name = pdb_id

            session_path = os.path.join(
                self.workspace_dir,
                f"{session_name}.pse"
            )

            # 保存 session
            self.cmd.save(session_path)

            logger.info(f"Saved session: {session_path}")
            return session_path

        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return None

    def align_structures(self, pdb_id1: str, pdb_id2: str) -> Dict:
        """
        对齐两个结构

        Args:
            pdb_id1: 第一个 PDB ID
            pdb_id2: 第二个 PDB ID

        Returns:
            对齐结果
        """
        if not self.is_available():
            return {"error": "PyMOL not available"}

        try:
            # 清理已有对象
            self.cmd.delete(pdb_id1)
            self.cmd.delete(pdb_id2)

            # 获取结构 - 使用 type=pdb
            self.cmd.fetch(pdb_id1, async_=0, type='pdb')
            self.cmd.fetch(pdb_id2, async_=0, type='pdb')

            # 执行 super 对齐
            super_result = self.cmd.super(f"{pdb_id1} and name ca",
                                         f"{pdb_id2} and name ca")

            # 执行 align
            align_result = self.cmd.align(f"{pdb_id1} and name ca",
                                          f"{pdb_id2} and name ca")

            return {
                "pdb_id1": pdb_id1,
                "pdb_id2": pdb_id2,
                "super_rms": super_result[0] if super_result else None,
                "align_rms": align_result[0] if align_result else None,
                "num_aligned": align_result[2] if align_result else None
            }
        except Exception as e:
            logger.error(f"Error aligning structures: {e}")
            return {"error": str(e)}

    def cleanup(self):
        """清理 PyMOL 会话"""
        if self.is_available():
            try:
                self.cmd.reinitialize()
                logger.info("PyMOL session cleaned up")
            except Exception as e:
                logger.error(f"Error cleaning up PyMOL: {e}")

    def __del__(self):
        """析构函数"""
        self.cleanup()


# 全局 PyMOL 实例
_pymol_wrapper: Optional[PyMOLWrapper] = None


def get_pymol_wrapper() -> PyMOLWrapper:
    """获取全局 PyMOL 封装实例"""
    global _pymol_wrapper
    if _pymol_wrapper is None:
        _pymol_wrapper = PyMOLWrapper()
    return _pymol_wrapper


def check_pymol_availability() -> Dict:
    """检查 PyMOL 可用性"""
    wrapper = get_pymol_wrapper()
    return {
        "available": wrapper.is_available(),
        "pymol_installed": PYMOL_AVAILABLE,
        "workspace_dir": wrapper.workspace_dir if wrapper.is_available() else None
    }
