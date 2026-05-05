import ReactMarkdown from 'react-markdown'

interface MarkdownRendererProps {
  content: string
}

export default function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <ReactMarkdown
      components={{
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        p: ({ children }) => <span className="[&:not(:first-child)]:mt-2 block">{children}</span>,
        ul: ({ children }) => <ul className="list-disc pl-5 [&:not(:first-child)]:mt-2">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-5 [&:not(:first-child)]:mt-2">{children}</ol>,
        li: ({ children }) => <li className="leading-6">{children}</li>,
        code: ({ children }) => (
          <code className="rounded bg-gray-100 px-1.5 py-0.5 text-sm font-mono text-gray-800">{children}</code>
        ),
        pre: ({ children }) => (
          <pre className="overflow-x-auto rounded-lg bg-gray-50 p-3 text-sm [&:not(:first-child)]:mt-2">{children}</pre>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
