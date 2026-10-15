'use client';

/**
 * Markdown 渲染组件 (BENCH 风格: 印刷期刊排版 + mono 数据强调)
 * 支持代码高亮 / 表格 / 引用
 */

import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { cn } from '@/lib/utils';

export function MarkdownView({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn('prose-cryo text-[13px] leading-relaxed', className)}>
      <ReactMarkdown
        components={{
          h1: ({ children }) => <h1 className="mt-5 mb-3 border-b pb-2 text-lg font-semibold tracking-tight first:mt-0">{children}</h1>,
          h2: ({ children }) => (
            <h2 className="mt-5 mb-2 text-base font-semibold tracking-tight first:mt-0">
              <span className="mr-2 inline-block h-[9px] w-[2px] translate-y-[-1px] rounded-full bg-primary" aria-hidden />
              {children}
            </h2>
          ),
          h3: ({ children }) => <h3 className="mt-4 mb-1.5 text-sm font-semibold first:mt-0">{children}</h3>,
          p: ({ children }) => <p className="my-2.5 leading-[1.75]">{children}</p>,
          ul: ({ children }) => <ul className="my-2.5 list-disc pl-5 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="my-2.5 list-decimal pl-5 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="leading-6">{children}</li>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2 decoration-primary/40 transition-colors hover:decoration-primary">
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-3 border-l-2 border-primary/50 bg-accent/40 py-1 pl-3.5 pr-2 text-muted-foreground">{children}</blockquote>
          ),
          code: ({ className: cls, children, ...props }) => {
            const match = /language-(\w+)/.exec(cls || '');
            const isBlock = match || String(children).includes('\n');
            if (!isBlock) {
              return (
                <code className="rounded-[3px] bg-muted px-1.5 py-px font-mono text-[0.82em] text-primary" {...props}>
                  {children}
                </code>
              );
            }
            return (
              <SyntaxHighlighter
                style={oneDark}
                language={match?.[1] || 'text'}
                PreTag="div"
                className="!my-3 !rounded-md !border !text-xs"
              >
                {String(children).replace(/\n$/, '')}
              </SyntaxHighlighter>
            );
          },
          pre: ({ children }) => <div className="my-3 overflow-x-auto">{children}</div>,
          table: ({ children }) => (
            <div className="my-3 overflow-x-auto rounded-md border">
              <table className="w-full text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted/70">{children}</thead>,
          th: ({ children }) => (
            <th className="label-tech border-b px-3 py-2 !text-[9px] text-left !tracking-[0.1em]">{children}</th>
          ),
          td: ({ children }) => <td className="border-b px-3 py-1.5 align-top last:border-b-0">{children}</td>,
          hr: () => <hr className="my-4 border-border" />,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
