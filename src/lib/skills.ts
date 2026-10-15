/**
 * CryoAgent Pro - Skills 预设技能库
 * 保留原版全部 11 个技能 + 新增 3 个 (序列理化分析 / 知识图谱导航 / 文献快读)
 */

export interface SkillStep {
  id: string;
  name: string;
  tool: string;
  condition?: string;
  params?: Record<string, unknown>;
}

export interface SkillDef {
  id: string;
  name: string;
  description: string;
  category: string;
  triggerKeywords: string[];
  systemPrompt: string;
  tools: string[];
  steps: SkillStep[];
  examples: string[];
  parameters: Record<string, unknown>;
}

export const DEFAULT_SKILLS: SkillDef[] = [
  {
    id: 'structure_compare',
    name: '结构比较专家',
    description: '比较两个蛋白质结构的异同，分析结构差异和相似性',
    category: 'structure',
    triggerKeywords: ['比较', '对比', '差异', 'compare', '对比分析', '结构差异'],
    systemPrompt: `你是一个专业的蛋白质结构分析专家。你的任务是：
1. 获取两个蛋白质结构的详细信息
2. 分析它们的结构差异，包括：二级结构元素（α螺旋、β折叠）的分布、活性位点或结合口袋的位置、结构域组成
3. 提供专业的结构比较分析报告

请用中文回答，确保分析准确且易于理解。`,
    tools: ['get_structure_details', 'search_structures', 'get_kg_neighbors'],
    steps: [
      { id: 'step1', name: '获取第一个结构信息', tool: 'get_structure_details', condition: 'has_structure_id' },
      { id: 'step2', name: '获取第二个结构信息', tool: 'get_structure_details', condition: 'has_structure_id' },
    ],
    examples: ['比较 6M0J 和 7A5I 的结构', '这两个蛋白质有什么差异？', '分析PDB结构 4O8F 和 5T3R 的区别'],
    parameters: { comparison_type: 'detailed' },
  },
  {
    id: 'literature_review',
    name: '文献综述专家',
    description: '根据主题搜索和总结相关文献，生成文献综述',
    category: 'literature',
    triggerKeywords: ['综述', '总结', 'overview', 'review', '研究进展', '研究现状'],
    systemPrompt: `你是一个专业的文献综述专家。你的任务是：
1. 根据用户给定的主题搜索相关文献
2. 整理和归纳文献的核心发现
3. 按主题分类总结当前研究进展
4. 指出研究热点和未来方向

请用中文撰写综述，确保结构清晰、分点论述、引用重要文献、总结研究趋势。`,
    tools: ['search_literature', 'get_publication_info'],
    steps: [{ id: 'step1', name: '搜索主题文献', tool: 'search_literature' }],
    examples: ['总结 CRISPR-Cas9 最新的研究进展', '综述蛋白质折叠的最新研究', '关于 AlphaFold 的研究进展如何？'],
    parameters: { max_literature: 20 },
  },
  {
    id: 'sequence_analysis',
    name: '序列分析专家',
    description: '蛋白质序列分析，包括比对、相似性搜索、理化性质、功能预测',
    category: 'sequence',
    triggerKeywords: ['序列', '比对', '相似', 'sequence', 'alignment', '分析'],
    systemPrompt: `你是一个专业的蛋白质序列分析专家。你的任务是：
1. 进行蛋白质序列比对
2. 查找相似序列
3. 分析序列特征、理化性质和功能域
4. 预测蛋白质功能

请提供详细的分析报告，包括：序列相似度、保守区域、可能的功能域。`,
    tools: ['run_sequence_alignment', 'find_similar_sequences', 'fetch_uniprot', 'analyze_sequence'],
    steps: [
      { id: 'step1', name: '获取序列信息', tool: 'fetch_uniprot', condition: 'has_sequence' },
      { id: 'step2', name: '查找相似序列', tool: 'find_similar_sequences', condition: 'has_sequence' },
    ],
    examples: ['帮我分析这段序列', '这段序列和 P0A8V2 相似吗？', '查找与这个序列相似的蛋白质'],
    parameters: { search_database: 'uniprot' },
  },
  {
    id: 'methodology_guide',
    name: '实验方法指南',
    description: '提供蛋白质相关实验方法的详细指导和建议',
    category: 'methodology',
    triggerKeywords: ['方法', 'protocol', '步骤', '如何做', '实验', '技术'],
    systemPrompt: `你是一个专业的生物实验方法专家。你的任务是：
1. 详细解释特定实验技术的原理
2. 提供标准化的实验步骤（protocol）
3. 指出常见问题和注意事项
4. 推荐合适的实验方案

请提供详细、可操作的实验指南。`,
    tools: ['search_literature', 'get_publication_info'],
    steps: [{ id: 'step1', name: '搜索相关方法文献', tool: 'search_literature' }],
    examples: ['如何纯化膜蛋白？', '蛋白质结晶的最佳条件是什么？', 'CRISPR 实验的一般步骤'],
    parameters: {},
  },
  {
    id: 'protein_design',
    name: '蛋白质设计顾问',
    description: '提供蛋白质设计建议，包括定点突变、稳定性优化等',
    category: 'design',
    triggerKeywords: ['设计', '改造', '优化', '突变', '构建', '工程化'],
    systemPrompt: `你是一个专业的蛋白质设计顾问。你的任务是：
1. 分析蛋白质结构特点
2. 提供突变位点建议
3. 预测突变对蛋白质的可能影响
4. 给出合理的蛋白质改造方案

请从专业角度分析，提供有依据的设计建议。`,
    tools: ['get_structure_details', 'search_structures', 'analyze_resolution'],
    steps: [
      { id: 'step1', name: '获取结构信息', tool: 'get_structure_details', condition: 'has_structure_id' },
      { id: 'step2', name: '分析结构特性', tool: 'analyze_resolution', condition: 'has_structure_id' },
    ],
    examples: ['如何提高这个蛋白的热稳定性？', '建议对蛋白质进行哪些突变？', '帮我设计一个酶活性位点突变'],
    parameters: {},
  },
  {
    id: 'data_visualization',
    name: '数据可视化专家',
    description: '提供数据可视化和图表生成的建议',
    category: 'visualization',
    triggerKeywords: ['可视化', '绘图', '图表', '展示', 'visualization', 'plot', 'figure'],
    systemPrompt: `你是一个数据可视化专家。你的任务是：
1. 分析数据结构
2. 推荐合适的可视化方案
3. 提供图表生成的代码或建议

请根据数据特点推荐最佳可视化方式。`,
    tools: ['search_literature'],
    steps: [],
    examples: ['如何展示蛋白质相互作用网络？', '帮我生成一个序列比对图', '如何可视化分子动力学轨迹？'],
    parameters: {},
  },
  {
    id: 'target_analysis',
    name: '靶点分析专家',
    description: '分析药物靶点的结构特点、结合位点等信息',
    category: 'target',
    triggerKeywords: ['靶点', '结合位点', '口袋', 'binding', 'target', '药物设计'],
    systemPrompt: `你是一个专业的药物靶点分析专家。你的任务是：
1. 分析靶点蛋白的结构特点
2. 识别潜在的结合口袋
3. 分析保守性和可药性
4. 提供药物设计建议

请从药物研发角度提供专业分析。`,
    tools: ['get_structure_details', 'get_kg_neighbors', 'analyze_resolution'],
    steps: [
      { id: 'step1', name: '获取靶点结构', tool: 'get_structure_details', condition: 'has_structure_id' },
      { id: 'step2', name: '分析结合位点', tool: 'get_structure_details', condition: 'has_structure_id' },
    ],
    examples: ['分析这个靶点的结合口袋', '找出 5HT1A 受体的药物结合位点', '这个蛋白质的可药性如何？'],
    parameters: { analysis_type: 'druggability' },
  },
  {
    id: 'mutation_analysis',
    name: '突变分析专家',
    description: '分析蛋白质突变的影响，包括致病性、功能影响等',
    category: 'mutation',
    triggerKeywords: ['突变', '变异', 'SNP', 'mutation', 'variant', '致病'],
    systemPrompt: `你是一个专业的突变分析专家。你的任务是：
1. 分析给定突变对蛋白质结构的影响
2. 预测突变的致病性
3. 分析突变在物种间的保守性
4. 提供功能影响分析

请从计算生物学角度提供专业分析。`,
    tools: ['fetch_uniprot', 'get_structure_details', 'find_similar_sequences'],
    steps: [
      { id: 'step1', name: '获取蛋白质信息', tool: 'fetch_uniprot' },
      { id: 'step2', name: '分析序列保守性', tool: 'find_similar_sequences' },
    ],
    examples: ['这个突变会有什么影响？', '分析 BRCA1 的致病突变', 'p53 R273H 突变有什么后果？'],
    parameters: { analysis_level: 'comprehensive' },
  },
  {
    id: 'structure_3d_analysis',
    name: '3D结构分析专家',
    description: '深度分析蛋白质3D结构：实体组成、配体、分辨率、实验方法',
    category: 'structure',
    triggerKeywords: ['pymol', '结构分析', '3d结构', '生成图像', 'cartoon', '二级结构', '结构图像'],
    systemPrompt: `你是一个专业的蛋白质 3D 结构分析专家。你的任务是：
1. 深度分析蛋白质 3D 结构元数据 (实验方法、分辨率、实体组成、配体)
2. 分析结构特征：二级结构倾向、疏水性、链组成
3. 建议可视化方案 (cartoon、sticks、surface 等样式)
4. 提供专业的结构解读

请提供详细的分析结果，包括结构特征描述。`,
    tools: ['get_structure_details', 'analyze_sequence', 'search_structures'],
    steps: [
      { id: 'step1', name: '获取结构信息', tool: 'get_structure_details', params: { analysis_type: 'info' } },
      { id: 'step2', name: '分析序列特征', tool: 'analyze_sequence' },
    ],
    examples: ['使用深度分析 6M0J 的结构', '分析 5T3R 的二级结构组成', '这个结构里有哪些配体？'],
    parameters: { default_style: 'cartoon', default_color: 'rainbow' },
  },
  {
    id: 'structure_alignment',
    name: '结构比对专家',
    description: '比较蛋白质序列/结构，计算相似性并生成比对结果',
    category: 'structure',
    triggerKeywords: ['比对', '叠加', 'rmsd', 'align', 'super', '结构比较'],
    systemPrompt: `你是一个专业的结构比对专家。你的任务是：
1. 执行蛋白质序列比对 (Needleman-Wunsch / Smith-Waterman)
2. 计算序列一致性与相似度
3. 解读比对结果 (保守残基、gap 分布)
4. 提供专业的结构比对分析报告

请用中文回答，确保分析准确且易于理解。`,
    tools: ['run_sequence_alignment', 'get_structure_details'],
    steps: [
      { id: 'step1', name: '获取两条序列', tool: 'get_structure_details' },
      { id: 'step2', name: '执行序列比对', tool: 'run_sequence_alignment' },
    ],
    examples: ['比较 6M0J 和 7A5I 的序列差异', '比对这两段序列', '计算这两个蛋白质的序列一致性'],
    parameters: { comparison_type: 'structural' },
  },
  {
    id: 'pocket_finder',
    name: '口袋识别专家',
    description: '识别蛋白质结合口袋和潜在药物靶点，分析表面性质',
    category: 'structure',
    triggerKeywords: ['口袋', '结合位点', 'pocket', 'binding', '药物设计', '靶点'],
    systemPrompt: `你是一个专业的药物靶点口袋识别专家。你的任务是：
1. 分析蛋白质结构与序列
2. 识别潜在的结合口袋 (基于疏水斑块与保守残基)
3. 分析口袋的理化性质
4. 提供药物设计建议

请从药物研发角度提供专业分析。`,
    tools: ['get_structure_details', 'analyze_sequence'],
    steps: [
      { id: 'step1', name: '获取结构信息', tool: 'get_structure_details' },
      { id: 'step2', name: '分析疏水表面', tool: 'analyze_sequence', params: { focus: 'hydropathy' } },
    ],
    examples: ['找出 5HT1A 受体的结合口袋', '分析这个蛋白质的药物结合位点', '识别结构中的空腔'],
    parameters: { analysis_type: 'druggability' },
  },
  // ============ 新增技能 ============
  {
    id: 'sequence_properties',
    name: '序列理化分析', // 新增
    description: '计算蛋白质/核酸序列的理化性质：分子量、等电点、疏水性、二级结构倾向',
    category: 'sequence',
    triggerKeywords: ['理化', '分子量', '等电点', '疏水性', '性质', 'molecular weight', 'pi', 'gravy', '理化性质'],
    systemPrompt: `你是一个专业的生物序列理化性质分析专家。你的任务是：
1. 调用序列分析工具计算分子量、等电点、GRAVY 疏水性、氨基酸组成、二级结构倾向等
2. 解读这些理化参数的生物学意义
3. 给出实验建议 (如表达纯化条件、缓冲液 pH 选择)

请基于工具返回的数据进行专业解读。`,
    tools: ['analyze_sequence', 'fetch_uniprot'],
    steps: [{ id: 'step1', name: '计算理化性质', tool: 'analyze_sequence' }],
    examples: ['计算这条序列的分子量和等电点', '这段蛋白序列的疏水性如何？', '帮我分析序列的理化性质'],
    parameters: {},
  },
  {
    id: 'kg_navigator',
    name: '知识图谱导航', // 新增
    description: '在结构-文献-蛋白质知识图谱中导航，发现隐藏关联',
    category: 'knowledge',
    triggerKeywords: ['图谱', '关联', '导航', '关系', '邻居', 'knowledge graph', '关联结构'],
    systemPrompt: `你是一个蛋白质知识图谱导航专家。你的任务是：
1. 在结构-文献-蛋白质关联图谱中查询节点邻域
2. 发现结构与文献之间的隐藏关联
3. 解读关联强度 (共现次数)
4. 提供关联挖掘建议

请基于图谱工具返回的节点和边数据进行解读。`,
    tools: ['get_kg_neighbors', 'search_literature', 'get_structure_details'],
    steps: [{ id: 'step1', name: '查询图谱邻域', tool: 'get_kg_neighbors' }],
    examples: ['6M0J 和哪些文献有关联？', '这个结构在知识图谱中的邻居', '帮我找和这篇文献相关的结构'],
    parameters: { depth: 1 },
  },
  {
    id: 'paper_skimmer',
    name: '文献快读', // 新增
    description: '快速提取文献核心要点：方法、结论、结构数据',
    category: 'literature',
    triggerKeywords: ['快读', '速读', '要点', '总结这篇', '这篇文献讲了什么', 'tl;dr'],
    systemPrompt: `你是一个高效的文献快读专家。你的任务是：
1. 基于检索到的文献片段快速提炼核心要点
2. 按【研究问题】【方法】【关键结果】【结构数据】【局限】结构化输出
3. 提取具体的 Cryo-EM 参数 (分辨率、颗粒数、B因子等)
4. 控制在一屏以内

请用中文输出结构化的快读摘要。`,
    tools: ['search_literature'],
    steps: [{ id: 'step1', name: '检索文献片段', tool: 'search_literature' }],
    examples: ['快读这篇关于 spike 蛋白的文献', '总结这篇 Cryo-EM 论文的要点', 'tl;dr 这篇文献'],
    parameters: { output: 'structured' },
  },
];

/** 根据查询匹配技能 (对应原 registry.match / Skill.matches_query)
 *  短英文关键词 (<=3字符) 用词边界匹配, 避免子字符串误匹配 (如 spike 中的 pi)
 */
export function matchSkills(query: string, skills: SkillDef[]): { skill: SkillDef; matchedKeywords: string[] }[] {
  const q = query.toLowerCase();
  const results: { skill: SkillDef; matchedKeywords: string[] }[] = [];
  for (const skill of skills) {
    const matched = skill.triggerKeywords.filter((k) => {
      const kw = k.toLowerCase();
      if (/^[a-z0-9-]+$/.test(kw) && kw.length <= 3) {
        // 短英文关键词: 词边界匹配
        const re = new RegExp(`(^|[^a-z0-9])${kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^a-z0-9]|$)`);
        return re.test(q);
      }
      return q.includes(kw);
    });
    if (matched.length > 0) results.push({ skill, matchedKeywords: matched });
  }
  return results.sort((a, b) => b.matchedKeywords.length - a.matchedKeywords.length);
}

export const SKILL_CATEGORIES: Record<string, { label: string; color: string }> = {
  structure: { label: '结构分析', color: 'teal' },
  literature: { label: '文献研究', color: 'amber' },
  sequence: { label: '序列分析', color: 'emerald' },
  methodology: { label: '实验方法', color: 'rose' },
  design: { label: '蛋白质设计', color: 'violet' },
  visualization: { label: '可视化', color: 'cyan' },
  target: { label: '药物靶点', color: 'orange' },
  mutation: { label: '突变分析', color: 'red' },
  knowledge: { label: '知识图谱', color: 'lime' },
};
