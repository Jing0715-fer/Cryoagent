"""
预设 Skills - 专业应用场景
"""
import logging
from typing import Dict, List
from .skill import Skill, SkillStep

logger = logging.getLogger(__name__)


def get_default_skills() -> List[Skill]:
    """获取所有预设 Skills"""

    skills = [
        # 1. 结构比较专家
        Skill(
            id="structure_compare",
            name="结构比较专家",
            description="比较两个蛋白质结构的异同，分析结构差异和相似性",
            category="structure",
            trigger_keywords=["比较", "对比", "差异", "compare", "对比分析", "结构差异"],
            system_prompt="""你是一个专业的蛋白质结构分析专家。你的任务是：
1. 获取两个蛋白质结构的详细信息
2. 分析它们的结构差异，包括：
   - 二级结构元素（α螺旋、β折叠）的分布
   - 活性位点或结合口袋的位置
   - 结构域组成
3. 提供专业的结构比较分析报告

请用中文回答，确保分析准确且易于理解。""",
            tools=["get_structure_details", "search_structures", "get_kg_neighbors"],
            steps=[
                SkillStep(
                    id="step1",
                    name="获取第一个结构信息",
                    tool="get_structure_details",
                    condition="has_structure_id"
                ),
                SkillStep(
                    id="step2",
                    name="获取第二个结构信息",
                    tool="get_structure_details",
                    condition="has_structure_id"
                )
            ],
            examples=[
                "比较 6M0J 和 7A5I 的结构",
                "这两个蛋白质有什么差异？",
                "分析PDB结构 4O8F 和 5T3R 的区别"
            ],
            parameters={"comparison_type": "detailed"}
        ),

        # 2. 文献综述专家
        Skill(
            id="literature_review",
            name="文献综述专家",
            description="根据主题搜索和总结相关文献，生成文献综述",
            category="literature",
            trigger_keywords=["综述", "总结", "overview", "review", "研究进展", "研究现状"],
            system_prompt="""你是一个专业的文献综述专家。你的任务是：
1. 根据用户给定的主题搜索相关文献
2. 整理和归纳文献的核心发现
3. 按主题分类总结当前研究进展
4. 指出研究热点和未来方向

请用中文撰写综述，确保：
- 结构清晰，分点论述
- 引用重要文献
- 总结研究趋势""",
            tools=["search_literature", "get_publication_info"],
            steps=[
                SkillStep(
                    id="step1",
                    name="搜索主题文献",
                    tool="search_literature"
                )
            ],
            examples=[
                "总结 CRISPR-Cas9 最新的研究进展",
                "综述蛋白质折叠的最新研究",
                "关于 AlphaFold 的研究进展如何？"
            ],
            parameters={"max_literature": 20}
        ),

        # 3. 序列分析专家
        Skill(
            id="sequence_analysis",
            name="序列分析专家",
            description="蛋白质序列分析，包括比对、相似性搜索、功能预测",
            category="sequence",
            trigger_keywords=["序列", "比对", "相似", "sequence", "alignment", "分析"],
            system_prompt="""你是一个专业的蛋白质序列分析专家。你的任务是：
1. 进行蛋白质序列比对
2. 查找相似序列
3. 分析序列特征和功能域
4. 预测蛋白质功能

请提供详细的分析报告，包括：
- 序列相似度
- 保守区域
- 可能的功能域""",
            tools=["run_sequence_alignment", "find_similar_sequences", "fetch_uniprot"],
            steps=[
                SkillStep(
                    id="step1",
                    name="获取序列信息",
                    tool="fetch_uniprot",
                    condition="has_sequence"
                ),
                SkillStep(
                    id="step2",
                    name="查找相似序列",
                    tool="find_similar_sequences",
                    condition="has_sequence"
                )
            ],
            examples=[
                "帮我分析这段序列",
                "这段序列和 P0A8V2 相似吗？",
                "查找与这个序列相似的蛋白质"
            ],
            parameters={"search_database": "uniprot"}
        ),

        # 4. 实验方法指南
        Skill(
            id="methodology_guide",
            name="实验方法指南",
            description="提供蛋白质相关实验方法的详细指导和建议",
            category="methodology",
            trigger_keywords=["方法", "protocol", "步骤", "如何做", "实验", "技术"],
            system_prompt="""你是一个专业的生物实验方法专家。你的任务是：
1. 详细解释特定实验技术的原理
2. 提供标准化的实验步骤（protocol）
3. 指出常见问题和注意事项
4. 推荐合适的实验方案

请提供详细、可操作的实验指南。""",
            tools=["search_literature", "get_publication_info"],
            steps=[
                SkillStep(
                    id="step1",
                    name="搜索相关方法文献",
                    tool="search_literature"
                )
            ],
            examples=[
                "如何纯化膜蛋白？",
                "蛋白质结晶的最佳条件是什么？",
                "CRISPR 实验的一般步骤"
            ]
        ),

        # 5. 蛋白质设计顾问
        Skill(
            id="protein_design",
            name="蛋白质设计顾问",
            description="提供蛋白质设计建议，包括定点突变、稳定性优化等",
            category="design",
            trigger_keywords=["设计", "改造", "优化", "突变", "构建", "工程化"],
            system_prompt="""你是一个专业的蛋白质设计顾问。你的任务是：
1. 分析蛋白质结构特点
2. 提供突变位点建议
3. 预测突变对蛋白质的可能影响
4. 给出合理的蛋白质改造方案

请从专业角度分析，提供有依据的设计建议。""",
            tools=["get_structure_details", "search_structures", "analyze_resolution"],
            steps=[
                SkillStep(
                    id="step1",
                    name="获取结构信息",
                    tool="get_structure_details",
                    condition="has_structure_id"
                ),
                SkillStep(
                    id="step2",
                    name="分析结构特性",
                    tool="analyze_resolution",
                    condition="has_structure_id"
                )
            ],
            examples=[
                "如何提高这个蛋白的热稳定性？",
                "建议对蛋白质进行哪些突变？",
                "帮我设计一个酶活性位点突变"
            ]
        ),

        # 6. 数据可视化专家
        Skill(
            id="data_visualization",
            name="数据可视化专家",
            description="提供数据可视化和图表生成的建议",
            category="visualization",
            trigger_keywords=["可视化", "绘图", "图表", "展示", "visualization", "plot", "figure"],
            system_prompt="""你是一个数据可视化专家。你的任务是：
1. 分析数据结构
2. 推荐合适的可视化方案
3. 提供图表生成的代码或建议

请根据数据特点推荐最佳可视化方式。""",
            tools=["search_literature"],
            steps=[],
            examples=[
                "如何展示蛋白质相互作用网络？",
                "帮我生成一个序列比对图",
                "如何可视化分子动力学轨迹？"
            ]
        ),

        # 7. 靶点分析专家
        Skill(
            id="target_analysis",
            name="靶点分析专家",
            description="分析药物靶点的结构特点、结合位点等信息",
            category="target",
            trigger_keywords=["靶点", "结合位点", "口袋", "binding", "target", "药物设计"],
            system_prompt="""你是一个专业的药物靶点分析专家。你的任务是：
1. 分析靶点蛋白的结构特点
2. 识别潜在的结合口袋
3. 分析保守性和可药性
4. 提供药物设计建议

请从药物研发角度提供专业分析。""",
            tools=["get_structure_details", "get_kg_neighbors", "analyze_resolution"],
            steps=[
                SkillStep(
                    id="step1",
                    name="获取靶点结构",
                    tool="get_structure_details",
                    condition="has_structure_id"
                ),
                SkillStep(
                    id="step2",
                    name="分析结合位点",
                    tool="get_structure_details",
                    condition="has_structure_id"
                )
            ],
            examples=[
                "分析这个靶点的结合口袋",
                "找出 5HT1A 受体的药物结合位点",
                "这个蛋白质的可药性如何？"
            ],
            parameters={"analysis_type": "druggability"}
        ),

        # 8. 突变分析专家
        Skill(
            id="mutation_analysis",
            name="突变分析专家",
            description="分析蛋白质突变的影响，包括致病性、功能影响等",
            category="mutation",
            trigger_keywords=["突变", "变异", "SNP", "mutation", "variant", "致病"],
            system_prompt="""你是一个专业的突变分析专家。你的任务是：
1. 分析给定突变对蛋白质结构的影响
2. 预测突变的致病性
3. 分析突变在物种间的保守性
4. 提供功能影响分析

请从计算生物学角度提供专业分析。""",
            tools=["fetch_uniprot", "get_structure_details", "find_similar_sequences"],
            steps=[
                SkillStep(
                    id="step1",
                    name="获取蛋白质信息",
                    tool="fetch_uniprot"
                ),
                SkillStep(
                    id="step2",
                    name="分析序列保守性",
                    tool="find_similar_sequences"
                )
            ],
            examples=[
                "这个突变会有什么影响？",
                "分析 BRCA1 的致病突变",
                "p53 R273H 突变有什么后果？"
            ],
            parameters={"analysis_level": "comprehensive"}
        ),

        # 9. PyMOL 结构分析专家
        Skill(
            id="pymol_structure_analysis",
            name="PyMOL结构分析专家",
            description="使用 PyMOL 进行蛋白质3D结构深度分析，生成结构图像和session文件",
            category="structure",
            trigger_keywords=["pymol", "结构分析", "3D结构", "生成图像", "cartoon", "二级结构", "结构图像"],
            system_prompt="""你是一个专业的 PyMOL 结构分析专家。你的任务是：
1. 使用 PyMOL 进行蛋白质3D结构深度分析
2. 分析结构特征：二级结构、分子表面、接触分析
3. 生成高质量结构图像（cartoon、sticks、surface 等样式）
4. 保存 PyMOL session 文件供后续交互式分析

请提供详细的分析结果，包括结构特征描述和生成的图像信息。
注意：PyMOL 需要安装 pymol-open-source 包才能使用。""",
            tools=["pymol_analyze", "pymol_image", "pymol_session", "pymol_ss"],
            steps=[
                SkillStep(
                    id="step1",
                    name="获取结构信息",
                    tool="pymol_analyze",
                    params={"analysis_type": "info"}
                ),
                SkillStep(
                    id="step2",
                    name="生成结构图像",
                    tool="pymol_image"
                )
            ],
            examples=[
                "使用 PyMOL 分析 1ABC 的结构",
                "生成 5T3R 的 3D 结构图像",
                "分析这个蛋白质的二级结构"
            ],
            parameters={"default_style": "cartoon", "default_color": "rainbow"}
        ),

        # 10. PyMOL 结构比对专家
        Skill(
            id="pymol_structure_compare",
            name="PyMOL结构比对专家",
            description="使用 PyMOL 进行蛋白质结构比对，计算 RMSD 并生成叠加图像",
            category="structure",
            trigger_keywords=["比对", "叠加", "RMSD", "align", "super", "结构比较", "rmsd"],
            system_prompt="""你是一个专业的 PyMOL 结构比对专家。你的任务是：
1. 使用 PyMOL 进行蛋白质结构比对（align/super 命令）
2. 计算结构间的 RMSD（均方根偏差）
3. 生成叠加图像展示结构差异
4. 提供专业的结构比对分析报告

请用中文回答，确保分析准确且易于理解。""",
            tools=["pymol_align", "pymol_rmsd", "pymol_image"],
            steps=[
                SkillStep(
                    id="step1",
                    name="计算 RMSD",
                    tool="pymol_rmsd"
                ),
                SkillStep(
                    id="step2",
                    name="执行结构对齐",
                    tool="pymol_align"
                )
            ],
            examples=[
                "比较 6M0J 和 7A5I 的结构差异",
                "计算这两个蛋白质的 RMSD",
                "生成结构叠加图像"
            ],
            parameters={"comparison_type": "structural"}
        ),

        # 11. PyMOL 口袋识别专家
        Skill(
            id="pymol_pocket_finder",
            name="PyMOL口袋识别专家",
            description="使用 PyMOL 识别蛋白质结合口袋和潜在药物靶点",
            category="structure",
            trigger_keywords=["口袋", "结合位点", "pocket", "binding", "药物设计", "靶点"],
            system_prompt="""你是一个专业的药物靶点口袋识别专家。你的任务是：
1. 使用 PyMOL 分析蛋白质结构
2. 识别潜在的结合口袋
3. 分析口袋的理化性质
4. 提供药物设计建议

请从药物研发角度提供专业分析。""",
            tools=["pymol_analyze", "pymol_surface", "pymol_image"],
            steps=[
                SkillStep(
                    id="step1",
                    name="分析分子表面",
                    tool="pymol_analyze",
                    params={"analysis_type": "surface"}
                ),
                SkillStep(
                    id="step2",
                    name="生成表面图像",
                    tool="pymol_image",
                    params={"style": "surface"}
                )
            ],
            examples=[
                "找出 5HT1A 受体的结合口袋",
                "分析这个蛋白质的药物结合位点",
                "识别结构中的空腔"
            ],
            parameters={"analysis_type": "druggability"}
        ),
    ]

    return skills


def initialize_skills(registry):
    """初始化并注册所有预设 Skills"""
    skills = get_default_skills()

    for skill in skills:
        if registry.validate_skill(skill):
            registry.register(skill)
        else:
            logger.warning(f"Skill {skill.id} validation failed, skipping")

    logger.info(f"Initialized {len(skills)} skills")
    return registry
