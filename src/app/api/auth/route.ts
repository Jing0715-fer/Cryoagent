import { NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { hashPassword, verifyPassword, createSession, getCurrentUser, destroySession } from '@/lib/auth';

/** POST /api/auth — action: register | login | logout */
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      action: 'register' | 'login' | 'logout';
      username?: string;
      password?: string;
    };

    if (body.action === 'logout') {
      await destroySession();
      return NextResponse.json({ success: true });
    }

    const username = (body.username || '').trim();
    const password = body.password || '';
    if (!username || username.length < 2) {
      return NextResponse.json({ success: false, error: '用户名至少 2 个字符' }, { status: 400 });
    }
    if (password.length < 4) {
      return NextResponse.json({ success: false, error: '密码至少 4 位' }, { status: 400 });
    }

    if (body.action === 'register') {
      const existing = await db.user.findUnique({ where: { username } });
      if (existing) {
        return NextResponse.json({ success: false, error: '用户名已存在' }, { status: 409 });
      }
      const user = await db.user.create({
        data: {
          username,
          passwordHash: hashPassword(password),
          displayName: username,
          role: 'user',
          avatarColor: ['teal', 'amber', 'rose', 'violet', 'emerald'][Math.floor(Math.random() * 5)],
        },
      });
      await createSession(user.id);
      return NextResponse.json({
        success: true,
        user: { id: user.id, username: user.username, displayName: user.displayName, role: user.role },
      });
    }

    // login
    const user = await db.user.findUnique({ where: { username } });
    if (!user || !verifyPassword(password, user.passwordHash)) {
      return NextResponse.json({ success: false, error: '用户名或密码错误' }, { status: 401 });
    }
    await createSession(user.id);
    return NextResponse.json({
      success: true,
      user: { id: user.id, username: user.username, displayName: user.displayName, role: user.role },
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : '服务器错误' },
      { status: 500 }
    );
  }
}

/** GET /api/auth — 当前用户 */
export async function GET() {
  const user = await getCurrentUser();
  const userCount = await db.user.count();
  return NextResponse.json({
    user,
    needSetup: userCount === 0,
    authEnabled: true,
  });
}
