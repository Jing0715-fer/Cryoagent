import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { DEFAULT_SKILLS, matchSkills, SKILL_CATEGORIES } from '@/lib/skills';
import { safeParse } from '@/lib/rag';

/** GET /api/skills — 技能列表 (对应原 routes/skills.py) */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const category = searchParams.get('category');

    // 若数据库为空, 同步默认技能
    let skills = await db.skill.findMany({ where: { enabled: true }, orderBy: { usageCount: 'desc' } });
    if (skills.length === 0) {
      await db.skill.createMany({
        data: DEFAULT_SKILLS.map((s) => ({
          id: s.id,
          name: s.name,
          description: s.description,
          category: s.category,
          triggerKeywords: JSON.stringify(s.triggerKeywords),
          systemPrompt: s.systemPrompt,
          tools: JSON.stringify(s.tools),
          steps: JSON.stringify(s.steps),
          examples: JSON.stringify(s.examples),
          parameters: JSON.stringify(s.parameters),
          isBuiltin: true,
        })),
      });
      skills = await db.skill.findMany({ where: { enabled: true }, orderBy: { usageCount: 'desc' } });
    }

    const filtered = category && category !== 'all' ? skills.filter((s) => s.category === category) : skills;

    return NextResponse.json({
      total: filtered.length,
      categories: Object.entries(SKILL_CATEGORIES).map(([id, v]) => ({
        id,
        label: v.label,
        count: skills.filter((s) => s.category === id).length,
      })),
      skills: filtered.map((s) => ({
        id: s.id,
        name: s.name,
        description: s.description,
        category: s.category,
        categoryLabel: SKILL_CATEGORIES[s.category]?.label || s.category,
        triggerKeywords: safeParse(s.triggerKeywords, [] as string[]),
        tools: safeParse(s.tools, [] as string[]),
        steps: safeParse(s.steps, []),
        examples: safeParse(s.examples, [] as string[]),
        usageCount: s.usageCount,
        successCount: s.successCount,
        isBuiltin: s.isBuiltin,
      })),
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}

/** POST /api/skills — 技能匹配测试 */
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { query?: string };
    const query = (body.query || '').trim();
    if (!query) return NextResponse.json({ error: '缺少 query' }, { status: 400 });
    const matches = matchSkills(query, DEFAULT_SKILLS);
    return NextResponse.json({
      query,
      total: matches.length,
      matches: matches.map((m) => ({
        skill: { id: m.skill.id, name: m.skill.name, category: m.skill.category, description: m.skill.description },
        matchedKeywords: m.matchedKeywords,
        score: m.matchedKeywords.length,
      })),
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '匹配失败' }, { status: 500 });
  }
}
