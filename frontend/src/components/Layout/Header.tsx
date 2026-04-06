interface HeaderProps {
  documentTitle?: string
}

export default function Header({ documentTitle }: HeaderProps) {
  return (
    <header className="h-14 bg-white border-b border-gray-200 flex items-center px-6">
      <h2 className="text-lg font-medium text-gray-800">
        {documentTitle || '请选择文档'}
      </h2>
    </header>
  )
}
