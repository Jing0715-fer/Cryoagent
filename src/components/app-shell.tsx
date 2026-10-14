'use client';

/**
 * CryoAgent Pro — 应用外壳 (侧边栏 + 顶栏 + 命令面板 + 粘性页脚)
 */

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useTheme } from 'next-themes';
import { useAppStore, type ViewId } from '@/lib/store';
import { api } from '@/lib/store';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet';
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from '@/components/ui/command';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  LayoutDashboard, MessageSquare, BookOpen, Boxes, Network, GitCompareArrows, FlaskConical, Sparkles,
  ClipboardCheck, Settings, BookMarked, Menu, Search, Sun, Moon, Monitor, LogOut, LogIn, UserPlus, ChevronLeft,
  Activity, Command as CommandIcon, Atom,
} from 'lucide-react';
import { Toaster } from '@/components/ui/sonner';
import { toast } from 'sonner';

export interface NavItem {
  id: ViewId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  group: string;
}

export const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: '仪表盘', icon: LayoutDashboard, group: '总览' },
  { id: 'qa', label: '智能问答', icon: MessageSquare, group: 'AI 分析' },
  { id: 'skills', label: '技能中心', icon: Sparkles, group: 'AI 分析' },
  { id: 'literature', label: '文献管理', icon: BookOpen, group: '知识库' },
  { id: 'structures', label: '结构浏览器', icon: Boxes, group: '知识库' },
  { id: 'kg', label: '知识图谱', icon: Network, group: '知识库' },
  { id: 'alignment', label: '序列比对', icon: GitCompareArrows, group: '分析工具' },
  { id: 'sequence-analyzer', label: '序列理化分析', icon: FlaskConical, group: '分析工具' },
  { id: 'evaluation', label: '评估中心', icon: ClipboardCheck, group: '系统' },
  { id: 'settings', label: '系统设置', icon: Settings, group: '系统' },
  { id: 'api-docs', label: '接口文档', icon: BookMarked, group: '系统' },
];

const GROUP_ORDER = ['总览', 'AI 分析', '知识库', '分析工具', '系统'];

interface UserInfo {
  id: string;
  username: string;
  displayName: string | null;
  role: string;
}

export function AppShell({ children, activeView }: { children: React.ReactNode; activeView: ViewId }) {
  const { navigate, sidebarOpen, setSidebarOpen, commandOpen, setCommandOpen } = useAppStore();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [needSetup, setNeedSetup] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginMode, setLoginMode] = useState<'login' | 'register'>('login');
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [loginBusy, setLoginBusy] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    api<{ user: UserInfo | null; needSetup: boolean }>('/api/auth')
      .then((d) => {
        setUser(d.user);
        setNeedSetup(d.needSetup);
      })
      .catch(() => {});
  }, []);

  // Cmd+K 命令面板
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setCommandOpen(!commandOpen);
      }
    };
    document.addEventListener('keydown', down);
    return () => document.removeEventListener('keydown', down);
  }, [commandOpen, setCommandOpen]);

  const grouped = useMemo(() => {
    const groups = new Map<string, NavItem[]>();
    for (const item of NAV_ITEMS) {
      if (!groups.has(item.group)) groups.set(item.group, []);
      groups.get(item.group)!.push(item);
    }
    return GROUP_ORDER.map((g) => ({ group: g, items: groups.get(g) || [] })).filter((g) => g.items.length > 0);
  }, []);

  const handleAuth = async (action: 'login' | 'register') => {
    if (!loginForm.username || !loginForm.password) {
      toast.error('请输入用户名和密码');
      return;
    }
    setLoginBusy(true);
    try {
      const d = await api<{ success: boolean; user: UserInfo }>('/api/auth', {
        method: 'POST',
        body: JSON.stringify({ action, ...loginForm }),
      });
      setUser(d.user);
      setLoginOpen(false);
      setLoginForm({ username: '', password: '' });
      toast.success(action === 'login' ? `欢迎回来, ${d.user.displayName || d.user.username}` : '注册成功, 已自动登录');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '操作失败');
    } finally {
      setLoginBusy(false);
    }
  };

  const handleLogout = async () => {
    try {
      await api('/api/auth', { method: 'POST', body: JSON.stringify({ action: 'logout' }) });
      setUser(null);
      toast.success('已退出登录');
    } catch {
      toast.error('退出失败');
    }
  };

  const runCommand = (view: ViewId) => {
    navigate(view);
    setCommandOpen(false);
  };

  const activeItem = NAV_ITEMS.find((n) => n.id === activeView);
  const sidebar = (
    <div className="flex h-full flex-col">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-4 py-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 text-white shadow-lg shadow-teal-500/20">
          <Atom className="h-5 w-5" />
        </div>
        <div className="leading-tight">
          <div className="text-[15px] font-bold tracking-tight">CryoAgent <span className="text-teal-600 dark:text-teal-400">Pro</span></div>
          <div className="text-[10px] text-muted-foreground">蛋白质结构智能分析平台 v2.0</div>
        </div>
      </div>

      {/* 导航 */}
      <nav className="flex-1 space-y-4 overflow-y-auto px-2.5 pb-4 custom-scrollbar">
        {grouped.map(({ group, items }) => (
          <div key={group}>
            <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">{group}</div>
            <div className="space-y-0.5">
              {items.map((item) => {
                const active = activeView === item.id || (activeView === 'literature-detail' && item.id === 'literature') || (activeView === 'structure-detail' && item.id === 'structures');
                return (
                  <button
                    key={item.id}
                    onClick={() => navigate(item.id)}
                    className={cn(
                      'group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-all',
                      active
                        ? 'bg-teal-600/10 font-medium text-teal-700 dark:bg-teal-500/10 dark:text-teal-300'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                    )}
                    type="button"
                  >
                    <item.icon className={cn('h-4 w-4 shrink-0', active && 'text-teal-600 dark:text-teal-400')} />
                    <span className="truncate">{item.label}</span>
                    {active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-teal-500" />}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* 底部状态 */}
      <div className="border-t px-3 py-3">
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          </span>
          <span>系统在线</span>
          <span className="ml-auto font-mono">Next.js 16</span>
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-background">
      <div className="flex flex-1 overflow-hidden">
        {/* 桌面侧边栏 */}
        <aside
          className={cn(
            'hidden shrink-0 border-r bg-card/50 backdrop-blur transition-all duration-300 md:block',
            sidebarOpen ? 'w-[230px]' : 'w-0 md:w-[64px] overflow-hidden'
          )}
        >
          {sidebarOpen ? sidebar : (
            <div className="flex h-full flex-col items-center gap-1 py-4">
              <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 text-white">
                <Atom className="h-4 w-4" />
              </div>
              {NAV_ITEMS.map((item) => {
                const active = activeView === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => navigate(item.id)}
                    title={item.label}
                    className={cn(
                      'flex h-9 w-9 items-center justify-center rounded-lg transition-colors',
                      active ? 'bg-teal-600/10 text-teal-600 dark:text-teal-400' : 'text-muted-foreground hover:bg-accent'
                    )}
                    type="button"
                  >
                    <item.icon className="h-4 w-4" />
                  </button>
                );
              })}
            </div>
          )}
        </aside>

        {/* 主区域 */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* 顶栏 */}
          <header className="flex h-[52px] shrink-0 items-center gap-2 border-b bg-background/80 px-3 backdrop-blur md:px-5">
            {/* 移动端菜单 */}
            <Sheet>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className="md:hidden">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-[240px] p-0">
                {sidebar}
              </SheetContent>
            </Sheet>

            {/* 折叠 */}
            <Button variant="ghost" size="icon" className="hidden md:flex" onClick={() => setSidebarOpen(!sidebarOpen)}>
              <ChevronLeft className={cn('h-4 w-4 transition-transform', !sidebarOpen && 'rotate-180')} />
            </Button>

            <h1 className="flex items-center gap-2 text-sm font-semibold">
              {activeItem && <activeItem.icon className="h-4 w-4 text-teal-600 dark:text-teal-400" />}
              {activeView === 'literature-detail' ? '文献详情' : activeView === 'structure-detail' ? '结构详情' : activeItem?.label}
            </h1>

            <div className="ml-auto flex items-center gap-1.5">
              {/* 命令面板触发 */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCommandOpen(true)}
                className="hidden h-8 gap-2 text-xs text-muted-foreground sm:flex"
              >
                <Search className="h-3.5 w-3.5" />
                快速跳转
                <kbd className="pointer-events-none ml-1 rounded border bg-muted px-1.5 font-mono text-[10px]">⌘K</kbd>
              </Button>

              {/* 主题切换 */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-8 w-8">
                    {mounted && theme === 'dark' ? <Moon className="h-4 w-4" /> : mounted && theme === 'light' ? <Sun className="h-4 w-4" /> : <Monitor className="h-4 w-4" />}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => setTheme('light')}><Sun className="mr-2 h-4 w-4" />浅色</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setTheme('dark')}><Moon className="mr-2 h-4 w-4" />深色</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setTheme('system')}><Monitor className="mr-2 h-4 w-4" />跟随系统</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              {/* 用户 */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" className="h-8 gap-2 px-2">
                    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-br from-teal-500 to-emerald-600 text-[11px] font-bold text-white">
                      {user ? (user.displayName || user.username).slice(0, 1).toUpperCase() : '?'}
                    </div>
                    <span className="hidden text-xs font-medium md:inline">{user ? user.displayName || user.username : '游客'}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-44">
                  {user ? (
                    <>
                      <DropdownMenuLabel className="font-normal">
                        <div className="text-sm font-medium">{user.displayName || user.username}</div>
                        <div className="text-xs text-muted-foreground">@{user.username} · {user.role}</div>
                      </DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={() => navigate('settings')}><Settings className="mr-2 h-4 w-4" />系统设置</DropdownMenuItem>
                      <DropdownMenuItem onClick={handleLogout} className="text-red-600"><LogOut className="mr-2 h-4 w-4" />退出登录</DropdownMenuItem>
                    </>
                  ) : (
                    <>
                      <DropdownMenuLabel className="font-normal text-xs text-muted-foreground">
                        {needSetup ? '创建管理员账号开始使用' : '登录以同步你的数据'}
                      </DropdownMenuLabel>
                      <DropdownMenuItem onClick={() => { setLoginMode('login'); setLoginOpen(true); }}>
                        <LogIn className="mr-2 h-4 w-4" />登录
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => { setLoginMode('register'); setLoginOpen(true); }}>
                        <UserPlus className="mr-2 h-4 w-4" />注册
                      </DropdownMenuItem>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </header>

          {/* 内容 */}
          <main className="flex-1 overflow-y-auto custom-scrollbar">
            <div className="flex min-h-full flex-col">
              <div className="flex-1">{children}</div>
              {/* 粘性页脚 */}
              <footer className="mt-auto border-t bg-background/90 px-4 py-2.5 text-[11px] text-muted-foreground backdrop-blur md:px-6">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <span className="flex items-center gap-1.5">
                    <Activity className="h-3 w-3 text-teal-600 dark:text-teal-400" />
                    CryoAgent Pro · 重构自 Flask 版
                  </span>
                  <span className="hidden sm:inline">BM25 + 向量混合检索 · 11 Agent 工具 · 14 技能</span>
                  <Link href="#" onClick={(e) => { e.preventDefault(); setCommandOpen(true); }} className="ml-auto flex items-center gap-1 hover:text-foreground">
                    <CommandIcon className="h-3 w-3" />K 快速跳转
                  </Link>
                </div>
              </footer>
            </div>
          </main>
        </div>
      </div>

      {/* 命令面板 */}
      <CommandDialog open={commandOpen} onOpenChange={setCommandOpen}>
        <CommandInput placeholder="搜索功能或输入命令..." />
        <CommandList>
          <CommandEmpty>未找到匹配项</CommandEmpty>
          {grouped.map(({ group, items }) => (
            <CommandGroup key={group} heading={group}>
              {items.map((item) => (
                <CommandItem key={item.id} onSelect={() => runCommand(item.id)}>
                  <item.icon className="mr-2 h-4 w-4" />
                  {item.label}
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
          <CommandSeparator />
          <CommandGroup heading="主题">
            <CommandItem onSelect={() => { setTheme('light'); setCommandOpen(false); }}><Sun className="mr-2 h-4 w-4" />浅色模式</CommandItem>
            <CommandItem onSelect={() => { setTheme('dark'); setCommandOpen(false); }}><Moon className="mr-2 h-4 w-4" />深色模式</CommandItem>
          </CommandGroup>
        </CommandList>
      </CommandDialog>

      {/* 登录/注册弹窗 */}
      {loginOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm" onClick={() => setLoginOpen(false)}>
          <div className="w-full max-w-sm rounded-xl border bg-card p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600 text-white">
                <Atom className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-base font-semibold">{loginMode === 'login' ? '登录 CryoAgent Pro' : '创建账号'}</h2>
                <p className="text-xs text-muted-foreground">
                  {needSetup && loginMode === 'register' ? '首个注册用户将成为管理员' : '同步问答历史与阅读笔记'}
                </p>
              </div>
            </div>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium">用户名</label>
                <Input
                  value={loginForm.username}
                  onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })}
                  placeholder="至少 2 个字符"
                  autoFocus
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium">密码</label>
                <Input
                  type="password"
                  value={loginForm.password}
                  onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
                  placeholder="至少 4 位"
                  onKeyDown={(e) => e.key === 'Enter' && handleAuth(loginMode)}
                />
              </div>
              <Button className="w-full" disabled={loginBusy} onClick={() => handleAuth(loginMode)}>
                {loginBusy ? '处理中...' : loginMode === 'login' ? '登录' : '注册并登录'}
              </Button>
              <button
                type="button"
                className="w-full text-center text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setLoginMode(loginMode === 'login' ? 'register' : 'login')}
              >
                {loginMode === 'login' ? '没有账号? 切换到注册' : '已有账号? 切换到登录'}
              </button>
            </div>
          </div>
        </div>
      )}

      <Toaster position="top-center" richColors />
    </div>
  );
}
