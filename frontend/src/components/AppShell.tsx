import { NavLink, Outlet } from 'react-router';
import { Inbox, MessagesSquare, Phone, Settings, UsersRound } from 'lucide-react';
import { cn } from '@/lib/utils';

const NAV = [
  { to: '/inbox', label: 'Inbox', icon: Inbox },
  { to: '/groups', label: 'Groups', icon: MessagesSquare },
  { to: '/contacts', label: 'Contacts', icon: UsersRound },
  { to: '/numbers', label: 'Numbers', icon: Phone },
  { to: '/settings', label: 'Settings', icon: Settings },
];

/** Sidebar navigation shell — grows per master doc Phase 1 UI spec
 * (Contacts, Groups, Broadcasts, Automation, Analytics, Settings land per epic). */
export default function AppShell(): React.JSX.Element {
  return (
    <div className="flex h-screen">
      <nav className="flex w-14 shrink-0 flex-col border-r bg-muted/30 p-3 md:w-48">
        <div className="mb-6 px-2 text-lg font-semibold">
          <span className="md:hidden">W</span>
          <span className="hidden md:inline">WaveDesk</span>
        </div>
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            aria-label={label}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm',
                isActive
                  ? 'bg-primary/10 font-medium text-primary'
                  : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="hidden md:inline">{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="min-w-0 flex-1 overflow-auto">
        <Outlet />
      </div>
    </div>
  );
}
