'use client';

/**
 * Markdown 渲染组件 (支持代码高亮 / 表格 / 引用)
 */

import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { cn } from '@/lib/utils';

export function MarkdownView({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn('prose-cryo text-sm leading-relaxed', className)}>
      <ReactMarkdown
        components={{
          h1: ({ children }) => <h1 className="mt-5 mb-3 text-xl font-bold tracking-tight border-b pb-2 first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="mt-5 mb-2 text-lg font-semibold tracking-tight first:mt-0">{children}</h2>,
          h3: ({ children }) => <h3 className="mt-4 mb-2 text-base font-semibold first:mt-0">{children}</h3>,
          p: ({ children }) => <p className="my-2.5 leading-7">{children}</p>,
          ul: ({ children }) => <ul className="my-2.5 list-disc pl-5 space-y-1.5">{children}</ul>,
          ol: ({ children }) => <ol className="my-2.5 list-decimal pl-5 space-y-1.5">{children}</ol>,
          li: ({ children }) => <li className="leading-6">{children}</li>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-teal-600 dark:text-teal-400 underline underline-offset-2 hover:opacity-80">
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-3 border-l-4 border-teal-500/60 pl-4 italic text-muted-foreground">{children}</blockquote>
          ),
          code: ({ className: cls, children, ...props }) => {
            const match = /language-(\w+)/.exec(cls || '');
            const isBlock = match || String(children).includes('\n');
            if (!isBlock) {
              return (
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-teal-700 dark:text-teal-300" {...props}>
                  {children}
                </code>
              );
            }
            return (
              <SyntaxHighlighter
                style={oneDark}
                language={match?.[1] || 'text'}
                PreTag="div"
                className="!my-3 !rounded-lg !text-xs"
              >
                {String(children).replace(/\n$/, '')}
              </SyntaxHighlighter>
            );
          },
          pre: ({ children }) => <div className="my-3 overflow-x-auto">{children}</div>,
          table: ({ children }) => (
            <div className="my-3 overflow-x-auto rounded-lg border">
              <table className="w-full text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted/80 font-semibold">{children}</thead>,
          th: ({ children }) => <th className="border-b px-3 py-2 text-left">{children}</th>,
          td: ({ children }) => <td className="border-b px-3 py-2 align-top">{children}</td>,
          hr: () => <hr className="my-4 border-border" />,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
