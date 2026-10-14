/**
 * CryoAgent Pro - LLM 服务层 (对应原 ai_config + Anthropic 调用)
 * 基于 z-ai-web-dev-sdk, 仅后端调用
 */

import ZAI from 'z-ai-web-dev-sdk';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface LlmResult {
  content: string;
  tokensUsed: number;
  latencyMs: number;
}

/** 基础对话补全 (带重试 + 429 退避) */
export async function chatCompletion(
  messages: ChatMessage[],
  options: { retries?: number; maxTokensHint?: number } = {}
): Promise<LlmResult> {
  const { retries = 3 } = options;
  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const start = Date.now();
      const zai = await ZAI.create();
      const completion = await zai.chat.completions.create({
        messages,
        thinking: { type: 'disabled' },
      });
      const content = completion.choices[0]?.message?.content || '';
      if (!content.trim()) throw new Error('AI 返回为空');
      const latencyMs = Date.now() - start;
      const tokensUsed = Math.ceil((content.length + messages.reduce((a, m) => a + m.content.length, 0)) / 4);
      return { content, tokensUsed, latencyMs };
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      const is429 = lastError.message.includes('429') || lastError.message.toLowerCase().includes('too many');
      if (attempt < retries) {
        // 429 用更长退避 (15s/30s/45s), 其他错误短退避
        const delay = is429 ? 15000 * (attempt + 1) : 800 * (attempt + 1);
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  }
  const msg = lastError?.message || 'LLM 调用失败';
  if (msg.includes('429') || msg.toLowerCase().includes('too many')) {
    throw new Error('AI 服务繁忙 (429 限流), 请稍后重试');
  }
  throw lastError || new Error('LLM 调用失败');
}

/** 从 LLM 提取 JSON (容错解析) */
export async function chatCompletionJson<T>(messages: ChatMessage[]): Promise<{ data: T; raw: string }> {
  const { content } = await chatCompletion([
    ...messages.slice(0, -1),
    {
      role: 'user',
      content: `${messages[messages.length - 1].content}\n\n[请只输出合法 JSON, 不要 markdown 代码块]`,
    },
  ]);
  const cleaned = content.replace(/```json\s*/g, '').replace(/```\s*/g, '').trim();
  try {
    return { data: JSON.parse(cleaned) as T, raw: content };
  } catch {
    // 尝试提取第一个 {...} 或 [...]
    const match = cleaned.match(/[[{][\s\S]*[\]}]/);
    if (match) {
      try {
        return { data: JSON.parse(match[0]) as T, raw: content };
      } catch {
        /* ignore */
      }
    }
    throw new Error(`JSON 解析失败: ${content.slice(0, 200)}`);
  }
}

/** CryoAgent 系统提示词 (对应原 qa_agent 的 system prompt) */
export const CRYO_SYSTEM_PROMPT = `你是 CryoAgent Pro —— 一个专业的 Cryo-EM(冷冻电镜)文献与蛋白质结构智能分析助手。

你的能力:
- 基于检索到的文献片段(RAG)回答 Cryo-EM、蛋白质结构、结构生物学问题
- 分析蛋白质结构 (PDB/EMDB/AlphaFold)
- 解读实验方法 (样品制备、数据收集、三维重构)
- 序列分析与比对解读

回答规范:
1. 优先基于提供的【文献片段】作答, 引用时标注来源编号如 [1][2]
2. 文献中没有的信息, 基于你的专业知识回答并说明 "此信息来自模型知识库"
3. 使用 Markdown 格式, 结构清晰 (标题/列表/表格)
4. 涉及具体数据(分辨率、B因子、FSC)时保持精确
5. 中文提问用中文回答, 英文提问用英文回答`;

/** 流式对话 (SSE) */
export async function chatCompletionStream(
  messages: ChatMessage[],
  onChunk: (text: string) => void
): Promise<{ full: string; tokensUsed: number; latencyMs: number }> {
  const start = Date.now();
  try {
    const zai = await ZAI.create();
    const stream = await zai.chat.completions.create({
      messages,
      thinking: { type: 'disabled' },
      stream: true,
    });
    let full = '';
    for await (const chunk of stream) {
      const delta = (chunk as { choices?: { delta?: { content?: string } }[] }).choices?.[0]?.delta?.content || '';
      if (delta) {
        full += delta;
        onChunk(delta);
      }
    }
    if (!full.trim()) throw new Error('空流式响应');
    const latencyMs = Date.now() - start;
    return { full, tokensUsed: Math.ceil(full.length / 3), latencyMs };
  } catch {
    // 回退: 非流式, 分块模拟输出
    const { content, tokensUsed, latencyMs } = await chatCompletion(messages);
    // 按句子分块推送
    const sentences = content.match(/[^。！？\n]+[。！？\n]*/g) || [content];
    let acc = '';
    for (const s of sentences) {
      acc += s;
      onChunk(s);
      await new Promise((r) => setTimeout(r, 15));
    }
    return { full: content, tokensUsed, latencyMs };
  }
}
