'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutDashboard, FolderOpen, User, LogOut } from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { label: 'Dashboard', href: '/ejecutivo', icon: LayoutDashboard },
  { label: 'Mis Casos', href: '/ejecutivo', icon: FolderOpen },
  { label: 'Perfil', href: '/ejecutivo', icon: User },
]

export function SidebarNav() {
  const pathname = usePathname()

  return (
    <nav className="flex flex-col h-full">
      <ul className="flex-1 flex flex-col gap-1 p-3">
        {navItems.map((item) => {
          const isActive = item.href === '/ejecutivo'
            ? pathname === '/ejecutivo' || pathname.startsWith('/ejecutivo/caso')
            : pathname === item.href
          const Icon = item.icon
          return (
            <li key={item.label}>
              <Link
                href={item.href}
                className={cn(
                  'flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all',
                  isActive
                    ? 'bg-[#1168BD]/10 text-[#1168BD] border-l-4 border-[#1168BD]'
                    : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900 border-l-4 border-transparent'
                )}
              >
                <Icon className="w-5 h-5" />
                {item.label}
              </Link>
            </li>
          )
        })}
      </ul>

      <div className="p-3 border-t border-gray-100">
        <Link
          href="/"
          className="flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-red-400 hover:bg-red-50 transition-all"
        >
          <LogOut className="w-5 h-5" />
          Salir
        </Link>
      </div>
    </nav>
  )
}
