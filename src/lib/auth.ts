/**
 * CryoAgent Pro - 用户认证 (对应原 routes/auth.py)
 * scrypt 密码哈希 + HMAC 签名 session token (httpOnly cookie)
 */

import { createHmac, randomBytes, scryptSync, timingSafeEqual } from 'crypto';
import { cookies } from 'next/headers';
import { db } from '@/lib/db';

const SECRET = process.env.AUTH_SECRET || 'cryoagent-pro-nextjs-secret-2025';
const COOKIE_NAME = 'cryoagent_session';
const SESSION_TTL_DAYS = 7;

export function hashPassword(password: string): string {
  const salt = randomBytes(16).toString('hex');
  const hash = scryptSync(password, salt, 64).toString('hex');
  return `${salt}:${hash}`;
}

export function verifyPassword(password: string, stored: string): boolean {
  const [salt, hash] = stored.split(':');
  if (!salt || !hash) return false;
  const testHash = scryptSync(password, salt, 64);
  const storedHash = Buffer.from(hash, 'hex');
  return storedHash.length === testHash.length && timingSafeEqual(testHash, storedHash);
}

function signSessionId(sessionId: string): string {
  return createHmac('sha256', SECRET).update(sessionId).digest('hex');
}

export function createSessionToken(sessionId: string): string {
  return `${sessionId}.${signSessionId(sessionId)}`;
}

function parseSessionToken(token: string): string | null {
  const idx = token.lastIndexOf('.');
  if (idx <= 0) return null;
  const sessionId = token.slice(0, idx);
  const sig = token.slice(idx + 1);
  const expected = signSessionId(sessionId);
  return sig === expected ? sessionId : null;
}

export async function createSession(userId: string): Promise<string> {
  const sessionId = randomBytes(24).toString('hex');
  const expiresAt = new Date(Date.now() + SESSION_TTL_DAYS * 24 * 3600 * 1000);
  await db.session.create({ data: { id: sessionId, userId, expiresAt } });
  const store = await cookies();
  store.set(COOKIE_NAME, createSessionToken(sessionId), {
    httpOnly: true,
    sameSite: 'lax',
    path: '/',
    expires: expiresAt,
  });
  return sessionId;
}

export interface CurrentUser {
  id: string;
  username: string;
  displayName: string | null;
  role: string;
}

export async function getCurrentUser(): Promise<CurrentUser | null> {
  const store = await cookies();
  const token = store.get(COOKIE_NAME)?.value;
  if (!token) return null;
  const sessionId = parseSessionToken(token);
  if (!sessionId) return null;
  const session = await db.session.findUnique({ where: { id: sessionId } });
  if (!session || session.expiresAt < new Date()) return null;
  const user = await db.user.findUnique({ where: { id: session.userId } });
  if (!user) return null;
  return {
    id: user.id,
    username: user.username,
    displayName: user.displayName,
    role: user.role,
  };
}

export async function destroySession(): Promise<void> {
  const store = await cookies();
  const token = store.get(COOKIE_NAME)?.value;
  if (token) {
    const sessionId = parseSessionToken(token);
    if (sessionId) {
      await db.session.deleteMany({ where: { id: sessionId } });
    }
  }
  store.delete(COOKIE_NAME);
}

/** 兼容原版的 "无强制登录" 模式: 未登录时使用匿名身份 */
export async function getUserOrAnonymous(): Promise<CurrentUser> {
  const user = await getCurrentUser();
  if (user) return user;
  return { id: 'anonymous', username: 'anonymous', displayName: '游客', role: 'guest' };
}
