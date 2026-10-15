import { db } from '@/lib/db';
import { getUserOrAnonymous } from '@/lib/auth';
import { ragSearch, buildRagContext, invalidateRagIndex } from '@/lib/rag';
import { chatCompletionStream, CRYO_SYSTEM_PROMPT, type ChatMessage } from '@/lib/llm';
import { matchSkills, DEFAULT_SKILLS } from '@/lib/skills';
import { safeParse } from '@/lib/rag';

/**
 * POST /api/qa/ask — RAG 智能问答 (SSE 流式)
 * 对应原 routes/qa.py ask + ask-v2
 */
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      question?: string;
      sessionId?: string;
      mode?: 'rag' | 'agent' | 'direct';
      useRag?: boolean;
      skillId?: string | null;
      history?: ChatMessage[];
    };
    const question = (body.question || '').trim();
    if (!question) {
      return new Response(JSON.stringify({ error: '缺少 question' }), { status: 400 });
    }
    const sessionId = body.sessionId || `sess-${Date.now()}`;
    const user = await getUserOrAnonymous();
    const mode = body.mode || 'rag';
    const useRag = body.useRag !== false && mode !== 'direct';

    // 1. RAG 检索
    const ragStart = Date.now();
    const hits = useRag ? await ragSearch(question, 'hybrid', 6) : [];
    const retrievalMs = Date.now() - ragStart;
    const ragContext = buildRagContext(hits);

    // 2. 技能匹配 (提示系统)
    const skillMatches = matchSkills(question, DEFAULT_SKILLS).slice(0, 1);
    const activeSkill = body.skillId ? DEFAULT_SKILLS.find((s) => s.id === body.skillId) : skillMatches[0]?.skill;

    let systemPrompt = CRYO_SYSTEM_PROMPT;
    if (activeSkill) {
      systemPrompt = `${activeSkill.systemPrompt}\n\n[全局规范同 CryoAgent Pro: 引用标注来源编号 [n], Markdown 输出]`;
    }
    if (ragContext) {
      systemPrompt += `\n\n【文献片段】\n${ragContext}`;
    }

    // 3. 历史消息 (最多保留 8 条)
    const history = (body.history || []).slice(-8);

    // 4. SSE 流式输出
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      async start(controller) {
        let closed = false;
        const send = (event: string, data: unknown) => {
          // 客户端断开后 enqueue 会抛错, 需吞掉避免未处理 rejection
          if (closed) return;
          try {
            controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
          } catch {
            closed = true;
          }
        };

        send('meta', {
          sessionId,
          mode,
          skill: activeSkill ? { id: activeSkill.id, name: activeSkill.name } : null,
          sources: hits.map((h, i) => ({
            index: i + 1,
            literatureId: h.literatureId,
            chunkIndex: h.chunkIndex,
            title: h.title,
            section: h.section,
            score: Math.round(h.score * 10000) / 10000,
            snippet: h.snippet,
          })),
          retrievalMs,
          autoSkillMatched: skillMatches.length > 0,
        });

        if (hits.length === 0 && useRag) {
          send('notice', { message: '本地文献库中未检索到相关内容, 将基于模型知识回答' });
        }

        try {
          const messages: ChatMessage[] = [
            { role: 'assistant', content: systemPrompt },
            ...history,
            { role: 'user', content: question },
          ];
          const { full, tokensUsed, latencyMs } = await chatCompletionStream(messages, (chunk) => {
            send('delta', { text: chunk });
          });

          // 保存历史
          await db.qaHistory
            .create({
              data: {
                userId: user.id === 'anonymous' ? null : user.id,
                sessionId,
                question,
                answer: full,
                sources: JSON.stringify(
                  hits.map((h, i) => ({
                    literatureId: h.literatureId,
                    title: h.title,
                    chunkIndex: h.chunkIndex,
                    score: h.score,
                    snippet: h.snippet.slice(0, 300),
                    index: i + 1,
                  }))
                ),
                mode,
                skillId: activeSkill?.id || null,
                tokensUsed,
                latencyMs,
              },
            })
            .catch(() => {});

          send('done', { tokensUsed, latencyMs, answer: full });
        } catch (err) {
          send('error', { message: err instanceof Error ? err.message : 'AI 调用失败' });
        } finally {
          try {
            controller.close();
          } catch {
            /* 已关闭 */
          }
        }
      },
    });

    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
    });
  } catch (err) {
    // JSON 错误
    return new Response(JSON.stringify({ error: err instanceof Error ? err.message : '问答失败' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

/** GET /api/qa/ask — 索引状态 (轻量) */
export async function GET() {
  const chunkCount = await db.literatureChunk.count().catch(() => 0);
  const litCount = await db.literature.count().catch(() => 0);
  return Response.json({ chunkCount, literatureCount: litCount });
}

// 引用避免未使用告警
void invalidateRagIndex;
void safeParse;
