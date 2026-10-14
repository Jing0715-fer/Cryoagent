import { NextResponse } from 'next/server';
import { db } from '@/lib/db';

/** GET /api/config — 应用配置 (对应原 routes/config.py) */
export async function GET() {
  try {
    const rows = await db.appConfig.findMany();
    const config: Record<string, unknown> = {};
    for (const r of rows) {
      try {
        config[r.key] = JSON.parse(r.value);
      } catch {
        config[r.key] = r.value;
      }
    }
    return NextResponse.json({
      config: {
        defaultQaMode: config.defaultQaMode || 'rag',
        defaultSearchMode: config.defaultSearchMode || 'hybrid',
        maxSources: config.maxSources ?? 6,
        theme: config.theme || 'system',
        agentMaxSteps: config.agentMaxSteps ?? 6,
        chunkSize: config.chunkSize ?? 480,
        chunkOverlap: config.chunkOverlap ?? 50,
        llmModel: config.llmModel || 'glm-4.6',
        ...config,
      },
    });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '加载失败' }, { status: 500 });
  }
}

/** POST /api/config — 保存配置 */
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const allowed = [
      'defaultQaMode',
      'defaultSearchMode',
      'maxSources',
      'theme',
      'agentMaxSteps',
      'chunkSize',
      'chunkOverlap',
      'llmModel',
    ];
    for (const [key, value] of Object.entries(body)) {
      if (!allowed.includes(key)) continue;
      await db.appConfig.upsert({
        where: { key },
        create: { key, value: JSON.stringify(value) },
        update: { value: JSON.stringify(value) },
      });
    }
    return NextResponse.json({ success: true });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : '保存失败' }, { status: 500 });
  }
}

/** PUT /api/config — 连接测试 (对应原 test_ai_connection) */
export async function PUT() {
  try {
    const start = Date.now();
    const { chatCompletion } = await import('@/lib/llm');
    const result = await chatCompletion([
      { role: 'assistant', content: '你是连通性测试助手, 请只回复 "OK"' },
      { role: 'user', content: 'ping' },
    ]);
    return NextResponse.json({
      success: true,
      latencyMs: Date.now() - start,
      reply: result.content.slice(0, 50),
      tokensUsed: result.tokensUsed,
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : 'AI 连接失败' },
      { status: 502 }
    );
  }
}
