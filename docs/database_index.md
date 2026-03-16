# 结构数据库索引文档

本文档描述结构数据库中各个表的字段和用途，帮助 AI 根据用户问题选择正确的查询方式。

---

## 表 1: structures（结构主表）

存储蛋白质结构的基本元数据信息。

| 字段名 | 类型 | 说明 | 用户问题示例 |
|--------|------|------|--------------|
| id | TEXT | PDB ID（如 8IRJ） | "8IRJ 的结构" |
| type | TEXT | 结构类型（PDB/EMDB） | "EMDB 结构" |
| title | TEXT | 结构标题 | "GPR179 结构" |
| resolution | REAL | 分辨率（Å） | "高分辨率结构" |
| method | TEXT | 实验方法（X-ray, Cryo-EM） | "Cryo-EM 结构" |
| organism | TEXT | 来源生物 | "人类蛋白结构" |
| gene | TEXT | 基因名称 | "GPR179 基因" |
| protein_name | TEXT | 蛋白名称 | "GPR179 蛋白" |
| authors | TEXT | 作者列表（JSON 数组） | - |
| deposition_date | TEXT | 沉积日期 | - |
| release_date | TEXT | 发布日期 | - |
| uniprot_ids | TEXT | 关联的 UniProt ID（JSON 数组） | "UniProt Q6ZMJ2" |
| related_ids | TEXT | 相关 ID（JSON 数组） | - |
| citation_count | TEXT | 引用次数 | - |

**用户问题示例**：
- "8IRJ 的分辨率是多少？"
- "GPR179 的实验方法是什么？"
- "有哪些人类蛋白的 Cryo-EM 结构？"

---

## 表 2: structure_entities（实体表）

存储每个结构中的分子实体信息，包括氨基酸序列。

| 字段名 | 类型 | 说明 | 用户问题示例 |
|--------|------|------|--------------|
| structure_id | TEXT | 关联的 PDB ID | "8IRJ 的序列" |
| entity_id | TEXT | 实体 ID（如 A, B） | - |
| molecule_type | TEXT | 分子类型（protein, DNA, RNA） | "蛋白序列" |
| molecule_name | TEXT | 分子/蛋白名称 | "蛋白名称" |
| sequence | TEXT | 单字母氨基酸序列 | "序列是什么" |
| length | INTEGER | 序列长度 | "多长" |
| gene_names | TEXT | 基因名称（逗号分隔） | "基因序列" |
| source_organism | TEXT | 来源生物 | - |
| uniprot_ids | TEXT | UniProt ID（JSON 数组） | "对应 UniProt" |

**用户问题示例**：
- "GPR179 的序列是什么？"
- "8IRJ 的氨基酸序列"
- "这个结构有多少个残基？"

---

## 表 3: uniprot_structure_mapping（UniProt-结构映射表）

关联 UniProt ID 和 PDB 结构。

| 字段名 | 类型 | 说明 | 用户问题示例 |
|--------|------|------|--------------|
| uniprot_id | TEXT | UniProt ID | "Q6ZMJ2 对应结构" |
| structure_id | TEXT | PDB ID | "哪些结构有 Q6ZMJ2" |
| entity_id | TEXT | 实体 ID | - |
| gene_name | TEXT | 基因名称 | - |
| protein_name | TEXT | 蛋白名称 | - |
| mapping_type | TEXT | 映射类型 | - |

**用户问题示例**：
- "Q6ZMJ2 对应的 PDB 结构有哪些？"
- "哪些结构包含 GPR179？"

---

## 表 4: structure_relationships（结构关系表）

存储结构之间的关系（相似性、比对结果等）。

| 字段名 | 类型 | 说明 | 用户问题示例 |
|--------|------|------|--------------|
| structure_id_1 | TEXT | 第一个 PDB ID | "与 7K5U 相似的结构" |
| structure_id_2 | TEXT | 第二个 PDB ID | - |
| relationship_type | TEXT | 关系类型（similar, aligned） | - |
| similarity_score | REAL | 相似度分数 | "相似度" |

---

## 表 5: literature_structure_mapping（文献-结构映射表）

关联文献和结构。

| 字段名 | 类型 | 说明 | 用户问题示例 |
|--------|------|------|--------------|
| literature_id | TEXT | 文献 ID | "GPR179 相关的文献" |
| structure_id | TEXT | PDB ID | "这篇文献涉及哪些结构" |
| section | TEXT | 文献章节 | - |

---

## 表 6: protein_structure_mapping（蛋白-结构映射表）

蛋白名称到结构的直接映射。

| 字段名 | 类型 | 说明 | 用户问题示例 |
|--------|------|------|--------------|
| protein_name | TEXT | 蛋白名称 | "GPR179 的结构" |
| gene_name | TEXT | 基因名称 | "GPR179 基因对应结构" |
| structure_id | TEXT | PDB ID | - |
| resolution | REAL | 分辨率 | - |
| method | TEXT | 实验方法 | - |

---

## AI 查询策略

### 根据问题类型选择查询方式：

1. **查询结构元数据** → 查询 `structures` 表
   - 分辨率、实验方法、标题、作者

2. **查询序列信息** → 查询 `structure_entities` 表
   - 氨基酸序列、序列长度、分子类型

3. **根据蛋白名称查询结构** → 查询 `uniprot_structure_mapping` 或 `protein_structure_mapping`
   - "GPR179 对应哪些结构"

4. **查询相关文献** → 查询 `literature_structure_mapping`
   - "这个结构相关文献"

5. **查询结构相似性** → 查询 `structure_relationships`
   - "与 XXX 相似的结构"

---

## 常用查询示例

### 获取结构元数据：
```sql
SELECT * FROM structures WHERE id = '8IRJ'
```

### 获取氨基酸序列：
```sql
SELECT entity_poly_seq_one_letter_code, entity_poly_seq_length
FROM structure_entities
WHERE structure_id = '8IRJ' AND molecule_type = 'protein'
```

### 根据蛋白名称搜索结构：
```sql
SELECT * FROM structures
WHERE protein_name LIKE '%GPR179%' OR gene LIKE '%GPR179%'
```

### 获取 UniProt 对应的结构：
```sql
SELECT structure_id FROM uniprot_structure_mapping
WHERE uniprot_id = 'Q6ZMJ2'
```
