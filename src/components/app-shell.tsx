'use client';

/**
 * CryoAgent Pro — 应用外壳 · WARM BENCH 设计系统
 * Claude 式暖纸侧边栏 (赤陶品牌块 + 乳白导航) + 面包屑顶栏 + 状态条页脚 + 命令面板
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
  ClipboardCheck, Settings, BookMarked, Menu, Search, Sun, Moon, Monitor, LogOut, LogIn, UserPlus, PanelLeft,
  ChevronRight, Command as CommandIcon, type LucideIcon,
} from 'lucide-react';
import { Toaster } from '@/components/ui/sonner';
import { toast } from 'sonner';

export interface NavItem {
  id: ViewId;
  label: string;
  slug: string; // 仪器面板式拉丁短码 (面包屑/命令面板用, 仅显示)
  code: string; // 侧栏通道选择器短码 (BENCH/QA/SKL…)
  icon: LucideIcon;
  group: string;
}

export const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: '平台总览', slug: 'bench', code: 'BENCH', icon: LayoutDashboard, group: '总览' },
  { id: 'qa', label: '智能问答', slug: 'qa', code: 'QA', icon: MessageSquare, group: 'AI 分析' },
  { id: 'skills', label: '技能中心', slug: 'skills', code: 'SKL', icon: Sparkles, group: 'AI 分析' },
  { id: 'literature', label: '文献管理', slug: 'library', code: 'LIB', icon: BookOpen, group: '知识库' },
  { id: 'structures', label: '结构浏览器', slug: 'pdb', code: 'PDB', icon: Boxes, group: '知识库' },
  { id: 'kg', label: '知识图谱', slug: 'graph', code: 'KG', icon: Network, group: '知识库' },
  { id: 'alignment', label: '序列比对', slug: 'align', code: 'ALN', icon: GitCompareArrows, group: '分析工具' },
  { id: 'sequence-analyzer', label: '序列理化分析', slug: 'seq', code: 'SEQ', icon: FlaskConical, group: '分析工具' },
  { id: 'evaluation', label: '评估中心', slug: 'eval', code: 'EVAL', icon: ClipboardCheck, group: '系统' },
  { id: 'settings', label: '系统设置', slug: 'cfg', code: 'CFG', icon: Settings, group: '系统' },
  { id: 'api-docs', label: '接口文档', slug: 'api', code: 'API', icon: BookMarked, group: '系统' },
];

const GROUP_ORDER = ['总览', 'AI 分析', '知识库', '分析工具', '系统'];

interface UserInfo {
  id: string;
  username: string;
  displayName: string | null;
  role: string;
}

/** 详情视图 → 所属导航项 (保持父项高亮) */
const PARENT_OF: Partial<Record<ViewId, ViewId>> = {
  'literature-detail': 'literature',
  'structure-detail': 'structures',
};

const TITLE_OF_DETAIL: Partial<Record<ViewId, { label: string; slug: string }>> = {
  'literature-detail': { label: '文献详情', slug: 'library/item' },
  'structure-detail': { label: '结构详情', slug: 'pdb/item' },
};

/** 仪器时钟 — 活体 HH:MM:SS (1s 步进, 卸载即清理) */
function LiveClock({ className }: { className?: string }) {
  const [time, setTime] = useState('--:--:--');
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const p = (n: number) => String(n).padStart(2, '0');
      setTime(`${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <span className={cn('num tabular-nums normal-case tracking-normal', className)} suppressHydrationWarning>
      {time}
    </span>
  );
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

  // 面包屑: 详情视图显示专属标题, 其余取导航项
  const parentView = PARENT_OF[activeView];
  const activeItem = NAV_ITEMS.find((n) => n.id === activeView);
  const crumb = activeItem
    ? { label: activeItem.label, slug: activeItem.slug }
    : TITLE_OF_DETAIL[activeView] || { label: '平台总览', slug: 'bench' };

  /* ============ 侧边栏 (桌面展开态) ============ */
  const sidebar = (
    <div className="flex h-full flex-col bg-sidebar">
      {/* 品牌区 — 赤陶渐变块 + 编辑性 wordmark */}
      <div className="border-b border-sidebar-border px-4 pb-4 pt-4">
        <div className="flex items-center gap-3">
          <div className="brand-tile flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px]">
            <svg viewBox="0 0 32 32" className="h-5 w-5" fill="none" aria-hidden="true">
              <g stroke="#ffffff" strokeOpacity={0.85} strokeWidth={1.4}>
                <path d="M16 16 L10 10 M16 16 L22 10 M16 16 L10 22 M16 16 L22 22 M10 10 L22 10 M10 22 L22 22 M10 10 L10 22 M22 10 L22 22" />
              </g>
              <circle cx="10" cy="10" r="2.1" fill="#ffffff" />
              <circle cx="22" cy="10" r="2.1" fill="#ffffff" />
              <circle cx="10" cy="22" r="2.1" fill="#ffffff" />
              <circle cx="22" cy="22" r="2.1" fill="#ffffff" />
              <circle cx="16" cy="16" r="3.6" fill="#ffffff" />
            </svg>
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-1.5">
              <span className="font-display text-[21px] leading-none tracking-tight text-sidebar-foreground">
                CryoAgent
              </span>
              <span className="label-tech rounded-[4px] border border-sidebar-primary/40 bg-primary-wash px-1 py-px !text-[9px] !tracking-[0.12em] text-sidebar-primary">
                PRO
              </span>
            </div>
            <div className="label-tech mt-1.5 !text-[9px] !tracking-[0.16em]">
              Cryo-EM Intelligence Workbench
            </div>
          </div>
        </div>
      </div>

      {/* 导航 — 暖调分组 + 赤陶激活态 */}
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4 custom-scrollbar" aria-label="主导航">
        {grouped.map(({ group, items }) => (
          <div key={group}>
            <div className="mb-1.5 flex items-center gap-2 px-2.5">
              <span className="label-tech shrink-0 !text-[9px]">{group}</span>
              <span className="flex-1 border-t border-sidebar-border" aria-hidden />
            </div>
            <div className="space-y-0.5">
              {items.map((item) => {
                const active = activeView === item.id || parentView === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => navigate(item.id)}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'group relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-[13px] transition-colors',
                      active
                        ? 'bg-primary-wash font-medium text-sidebar-primary'
                        : 'text-sidebar-foreground/72 hover:bg-sidebar-accent/70 hover:text-sidebar-foreground'
                    )}
                    type="button"
                  >
                    <item.icon className="h-[15px] w-[15px] shrink-0" strokeWidth={active ? 2 : 1.75} />
                    <span className="truncate">{item.label}</span>
                    <span
                      className={cn(
                        'ml-auto shrink-0 font-mono text-[9px] font-medium uppercase tracking-[0.1em] transition-colors',
                        active
                          ? 'text-sidebar-primary/80'
                          : 'text-sidebar-foreground/38 group-hover:text-sidebar-foreground/75'
                      )}
                      aria-hidden
                    >
                      {item.code}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* 底部铭牌 — 系统状态 + 仪器时钟 */}
      <div className="border-t border-sidebar-border px-4 py-2.5">
        <div className="label-tech flex items-center gap-2 !text-[9px]">
          <span className="status-dot" aria-hidden />
          <span className="text-sidebar-foreground/80">SYS ONLINE</span>
          <span className="ml-auto text-sidebar-foreground/45">NEXT·16</span>
        </div>
        <div className="label-tech mt-1 flex items-center justify-between !text-[9px]">
          <span className="text-sidebar-foreground/45">SYS.TIME</span>
          <LiveClock className="text-[12px] leading-none text-sidebar-foreground/75" />
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-background">
      <div className="flex flex-1 overflow-hidden">
        {/* 桌面侧边栏 — 展开 / 收缩导轨 */}
        <aside
          className={cn(
            'hidden shrink-0 border-r border-sidebar-border transition-[width] duration-200 md:block',
            sidebarOpen ? 'w-[216px]' : 'w-[56px]'
          )}
        >
          {sidebarOpen ? (
            sidebar
          ) : (
            <div className="flex h-full flex-col items-center bg-sidebar py-4">
              <div className="brand-tile mb-4 flex h-9 w-9 items-center justify-center rounded-[10px]" title="CryoAgent Pro">
                <svg viewBox="0 0 32 32" className="h-5 w-5" fill="none" aria-hidden="true">
                  <g stroke="#ffffff" strokeOpacity={0.85} strokeWidth={1.4}>
                    <path d="M16 16 L10 10 M16 16 L22 10 M16 16 L10 22 M16 16 L22 22 M10 10 L22 10 M10 22 L22 22 M10 10 L10 22 M22 10 L22 22" />
                  </g>
                  <circle cx="16" cy="16" r="3.6" fill="#ffffff" />
                </svg>
              </div>
              <nav className="flex flex-1 flex-col items-center gap-1" aria-label="主导航">
                {NAV_ITEMS.map((item) => {
                  const active = activeView === item.id || parentView === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => navigate(item.id)}
                      title={item.label}
                      aria-current={active ? 'page' : undefined}
                      className={cn(
                        'relative flex h-8 w-8 items-center justify-center rounded-lg transition-colors',
                        active
                          ? 'bg-primary-wash text-sidebar-primary'
                          : 'text-sidebar-foreground/58 hover:bg-sidebar-accent/70 hover:text-sidebar-foreground'
                      )}
                      type="button"
                    >
                      <item.icon className="h-[15px] w-[15px]" strokeWidth={active ? 2 : 1.75} />
                    </button>
                  );
                })}
              </nav>
              <div className="status-dot mt-2" title="SYS ONLINE" />
            </div>
          )}
        </aside>

        {/* 主区域 */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* 顶栏 — 面包屑 + 全局动作 */}
          <header className="flex h-12 shrink-0 items-center gap-1.5 border-b bg-background px-2.5 md:px-4">
            {/* 移动端菜单 */}
            <Sheet>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8 md:hidden" aria-label="打开导航">
                  <Menu className="h-[18px] w-[18px]" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-[232px] border-sidebar-border p-0 [&>button:last-child]:hidden">
                {sidebar}
              </SheetContent>
            </Sheet>

            {/* 侧栏折叠 */}
            <Button
              variant="ghost"
              size="icon"
              className="hidden h-8 w-8 text-muted-foreground md:flex"
              onClick={() => setSidebarOpen(!sidebarOpen)}
              aria-label={sidebarOpen ? '收起侧栏' : '展开侧栏'}
            >
              <PanelLeft className="h-4 w-4" />
            </Button>

            {/* 面包屑 — 中文标题 + chevron + 拉丁短码 */}
            <nav className="flex min-w-0 items-center gap-1.5 pl-1" aria-label="当前视图">
              <h1 className="truncate text-[13.5px] font-semibold tracking-tight">{crumb.label}</h1>
              <ChevronRight className="hidden h-2.5 w-2.5 shrink-0 text-muted-foreground/50 sm:block" strokeWidth={2} aria-hidden />
              <span className="label-tech hidden !text-[10px] sm:inline">{crumb.slug}</span>
            </nav>

            <div className="ml-auto flex items-center gap-1.5">
              {/* 命令面板触发 */}
              <button
                onClick={() => setCommandOpen(true)}
                className="hidden h-8 items-center gap-2 rounded-lg border bg-card px-2.5 text-muted-foreground transition-colors hover:border-primary/45 hover:text-foreground sm:flex"
                type="button"
              >
                <Search className="h-3.5 w-3.5" strokeWidth={1.75} />
                <span className="label-tech !text-[9px]">SEARCH</span>
                <kbd className="rounded-[4px] border bg-muted px-1 py-px font-mono text-[9px] text-muted-foreground">⌘K</kbd>
              </button>
              <Button variant="ghost" size="icon" className="h-8 w-8 sm:hidden" onClick={() => setCommandOpen(true)} aria-label="搜索">
                <Search className="h-4 w-4" />
              </Button>

              {/* 主题切换 */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="切换主题">
                    {mounted && theme === 'dark' ? <Moon className="h-4 w-4" /> : mounted && theme === 'light' ? <Sun className="h-4 w-4" /> : <Monitor className="h-4 w-4" />}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => setTheme('light')}><Sun className="mr-2 h-3.5 w-3.5" />浅色</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setTheme('dark')}><Moon className="mr-2 h-3.5 w-3.5" />深色</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setTheme('system')}><Monitor className="mr-2 h-3.5 w-3.5" />跟随系统</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              {/* 用户 */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" className="h-8 gap-2 px-1.5">
                    <div className="brand-tile flex h-6 w-6 items-center justify-center rounded-[6px] text-[11px] font-semibold uppercase text-primary-foreground">
                      {user ? (user.displayName || user.username).slice(0, 1) : '·'}
                    </div>
                    <span className="hidden text-xs font-medium md:inline">{user ? user.displayName || user.username : '游客'}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-44">
                  {user ? (
                    <>
                      <DropdownMenuLabel className="font-normal">
                        <div className="text-[13px] font-medium">{user.displayName || user.username}</div>
                        <div className="label-tech mt-0.5 !text-[9px] normal-case !tracking-normal">@{user.username} · {user.role}</div>
                      </DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={() => navigate('settings')}><Settings className="mr-2 h-3.5 w-3.5" />系统设置</DropdownMenuItem>
                      <DropdownMenuItem onClick={handleLogout} className="text-destructive"><LogOut className="mr-2 h-3.5 w-3.5" />退出登录</DropdownMenuItem>
                    </>
                  ) : (
                    <>
                      <DropdownMenuLabel className="label-tech !text-[9px] normal-case !tracking-normal">
                        {needSetup ? '创建管理员账号开始使用' : '登录以同步你的数据'}
                      </DropdownMenuLabel>
                      <DropdownMenuItem onClick={() => { setLoginMode('login'); setLoginOpen(true); }}>
                        <LogIn className="mr-2 h-3.5 w-3.5" />登录
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => { setLoginMode('register'); setLoginOpen(true); }}>
                        <UserPlus className="mr-2 h-3.5 w-3.5" />注册
                      </DropdownMenuItem>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </header>

          {/* 内容 — 视图在 min-h 布局中渲染, 页脚粘底 */}
          <main className="flex-1 overflow-y-auto custom-scrollbar">
            <div className="flex min-h-full flex-col">
              <div className="flex-1">{children}</div>
              {/* 粘性状态条页脚 */}
              <footer className="mt-auto border-t bg-background px-4 py-2 md:px-5">
                <div className="label-tech flex flex-wrap items-center gap-x-5 gap-y-1 !text-[9px]">
                  <span className="flex items-center gap-1.5">
                    <span className="status-dot" aria-hidden />
                    CRYOAGENT PRO v2.1
                  </span>
                  <span className="hidden text-muted-foreground/70 sm:inline">BM25+VEC 混合检索 · 11 AGENT TOOLS · 14 SKILLS</span>
                  <span className="hidden items-center gap-1.5 text-muted-foreground/70 sm:flex">
                    SYS.TIME
                    <LiveClock className="text-[12px] leading-none text-foreground/75" />
                  </span>
                  <Link
                    href="#"
                    onClick={(e) => { e.preventDefault(); setCommandOpen(true); }}
                    className="ml-auto flex items-center gap-1.5 text-muted-foreground/70 transition-colors hover:text-foreground"
                  >
                    <CommandIcon className="h-3 w-3" />K NAVIGATE
                  </Link>
                </div>
              </footer>
            </div>
          </main>
        </div>
      </div>

      {/* 命令面板 */}
      <CommandDialog open={commandOpen} onOpenChange={setCommandOpen}>
        <CommandInput placeholder="搜索功能或输入命令…" />
        <CommandList>
          <CommandEmpty>未找到匹配项</CommandEmpty>
          {grouped.map(({ group, items }) => (
            <CommandGroup key={group} heading={group}>
              {items.map((item) => (
                <CommandItem key={item.id} onSelect={() => runCommand(item.id)}>
                  <item.icon className="mr-2 h-4 w-4" strokeWidth={1.75} />
                  {item.label}
                  <span className="label-tech ml-auto !text-[9px]">{item.slug}</span>
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

      {/* 登录/注册 — 暖纸面板 */}
      {loginOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/25 p-4 backdrop-blur-[2px]"
          onClick={() => setLoginOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-label={loginMode === 'login' ? '登录' : '注册'}
        >
          <div
            className="card-shadow w-full max-w-[340px] rounded-xl border bg-card p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 border-b pb-3.5">
              <div className="brand-tile flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px]">
                <svg viewBox="0 0 32 32" className="h-4.5 w-4.5" fill="none" aria-hidden="true">
                  <circle cx="16" cy="16" r="3.6" fill="#ffffff" />
                </svg>
              </div>
              <div className="min-w-0 flex-1">
                <div className="font-display text-lg leading-none tracking-tight">CryoAgent</div>
                <div className="label-tech mt-1 !text-[9px]">{loginMode === 'login' ? 'SIGN IN' : 'SIGN UP'}</div>
              </div>
            </div>
            <p className="label-tech mt-3 !text-[9px] normal-case !tracking-normal">
              {needSetup && loginMode === 'register' ? '首个注册用户将成为管理员' : '登录后同步问答历史与阅读笔记'}
            </p>
            <div className="mt-3 space-y-2.5">
              <div>
                <label htmlFor="login-username" className="label-tech mb-1 block">用户名</label>
                <Input
                  id="login-username"
                  value={loginForm.username}
                  onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })}
                  placeholder="至少 2 个字符"
                  autoComplete="username"
                  autoFocus
                  className="h-9"
                />
              </div>
              <div>
                <label htmlFor="login-password" className="label-tech mb-1 block">密码</label>
                <Input
                  id="login-password"
                  type="password"
                  value={loginForm.password}
                  onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
                  placeholder="至少 4 位"
                  autoComplete={loginMode === 'login' ? 'current-password' : 'new-password'}
                  onKeyDown={(e) => e.key === 'Enter' && handleAuth(loginMode)}
                  className="h-9"
                />
              </div>
              <Button className="h-9 w-full font-medium" disabled={loginBusy} onClick={() => handleAuth(loginMode)}>
                {loginBusy ? '处理中…' : loginMode === 'login' ? '登录' : '注册并登录'}
              </Button>
              <button
                type="button"
                className="label-tech w-full text-center !text-[10px] normal-case !tracking-normal transition-colors hover:text-foreground"
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
