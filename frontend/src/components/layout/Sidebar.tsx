import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, CreditCard, Users, UserCheck,
  FileText, BarChart3, Shield, Receipt, ClipboardList,
} from 'lucide-react'
import { usePermissions } from '@/store/authStore'
import clsx from 'clsx'

const navItems = [
  { to: '/dashboard',   label: 'Dashboard',   icon: LayoutDashboard, always: true },
  { to: '/pagos',       label: 'Pagos',       icon: Receipt,         always: true },
  { to: '/creditos',    label: 'Créditos',    icon: CreditCard,      always: true },
  { to: '/clientes',    label: 'Clientes',    icon: Users,           always: true },
  { to: '/gestores',    label: 'Gestores',    icon: UserCheck,       permission: 'canGestionarReceptores' as const },
  { to: '/reportes',    label: 'Reportes',    icon: BarChart3,       permission: 'canVerReportes' as const },
  { to: '/receptores',  label: 'Receptores',  icon: Shield,          permission: 'canGestionarReceptores' as const },
  { to: '/usuarios',    label: 'Usuarios',    icon: Shield,          permission: 'canGestionarUsuarios' as const },
  { to: '/auditoria',  label: 'Auditoría',   icon: ClipboardList,   permission: 'canGestionarUsuarios' as const },
]

export default function Sidebar() {
  const perms = usePermissions()

  return (
    <aside className="w-60 bg-primary-600 flex flex-col h-full shadow-xl">
      {/* Logo */}
      <div className="px-6 py-6 border-b border-primary-500">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-accent rounded-lg flex items-center justify-center shadow-md flex-shrink-0">
            <span className="text-primary-600 font-black text-base">SE</span>
          </div>
          <div>
            <p className="text-white font-bold text-sm leading-tight">Soluciones</p>
            <p className="text-accent font-bold text-sm leading-tight">Efectivas</p>
          </div>
        </div>
      </div>

      {/* Navegación */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          // Verificar permisos
          if (item.permission && !perms[item.permission]) return null

          const Icon = item.icon
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150',
                  isActive
                    ? 'bg-accent text-primary-600 shadow-md'
                    : 'text-primary-100 hover:bg-primary-500 hover:text-white'
                )
              }
            >
              <Icon size={18} strokeWidth={2} />
              {item.label}
            </NavLink>
          )
        })}
      </nav>

      {/* Footer del sidebar */}
      <div className="px-4 py-4 border-t border-primary-500">
        <p className="text-primary-300 text-xs text-center">v1.0.0 — 2026</p>
      </div>
    </aside>
  )
}
