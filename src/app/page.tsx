'use client';

/**
 * CryoAgent Pro — 单页应用入口
 * 所有视图通过状态切换 (对应原 Flask 多页面应用)
 */

import { useEffect } from 'react';
import { ThemeProvider } from 'next-themes';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useAppStore, api } from '@/lib/store';
import { AppShell } from '@/components/app-shell';
import { DashboardView } from '@/components/views/dashboard-view';
import { QaView } from '@/components/views/qa-view';
import { LiteratureView } from '@/components/views/literature-view';
import { LiteratureDetailView } from '@/components/views/literature-detail-view';
import { StructuresView } from '@/components/views/structures-view';
import { StructureDetailView } from '@/components/views/structure-detail-view';
import { KgView } from '@/components/views/kg-view';
import { AlignmentView } from '@/components/views/alignment-view';
import { SequenceAnalyzerView } from '@/components/views/sequence-analyzer-view';
import { SkillsView } from '@/components/views/skills-view';
import { EvaluationView } from '@/components/views/evaluation-view';
import { SettingsView } from '@/components/views/settings-view';
import { ApiDocsView } from '@/components/views/api-docs-view';

export default function Home() {
  const view = useAppStore((s) => s.view);

  // 首次访问自动初始化演示数据
  useEffect(() => {
    api<{ needsSeed: boolean }>('/api/seed')
      .then((d) => {
        if (d.needsSeed) {
          return api('/api/seed', { method: 'POST' }).catch(() => {});
        }
      })
      .catch(() => {});
  }, []);

  const renderView = () => {
    switch (view) {
      case 'dashboard':
        return <DashboardView />;
      case 'qa':
        return <QaView />;
      case 'literature':
        return <LiteratureView />;
      case 'literature-detail':
        return <LiteratureDetailView />;
      case 'structures':
        return <StructuresView />;
      case 'structure-detail':
        return <StructureDetailView />;
      case 'kg':
        return <KgView />;
      case 'alignment':
        return <AlignmentView />;
      case 'sequence-analyzer':
        return <SequenceAnalyzerView />;
      case 'skills':
        return <SkillsView />;
      case 'evaluation':
        return <EvaluationView />;
      case 'settings':
        return <SettingsView />;
      case 'api-docs':
        return <ApiDocsView />;
      default:
        return <DashboardView />;
    }
  };

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <TooltipProvider delayDuration={200}>
        <AppShell activeView={view}>
          {/* key 强制视图切换时重建 (重置内部状态) */}
          <div key={view} className="min-h-0">
            {renderView()}
          </div>
        </AppShell>
      </TooltipProvider>
    </ThemeProvider>
  );
}
