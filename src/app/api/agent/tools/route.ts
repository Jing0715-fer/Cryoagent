import { NextResponse } from 'next/server';
import { AGENT_TOOLS } from '@/lib/agent';

/** GET /api/agent/tools — Agent 工具列表 (对应原 /api/qa/agent/tools) */
export async function GET() {
  return NextResponse.json({
    total: AGENT_TOOLS.length,
    tools: AGENT_TOOLS.map((t) => ({
      name: t.name,
      description: t.description,
      parameters: Object.entries(t.parameters).map(([name, p]) => ({
        name,
        type: p.type,
        description: p.description,
        required: p.required || false,
        enum: p.enum,
      })),
    })),
  });
}
