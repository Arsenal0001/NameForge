import { NavLink, Outlet } from "react-router-dom";

import { cn } from "@/lib/utils";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "block rounded-md px-3 py-2 text-sm font-medium transition-colors",
    isActive
      ? "bg-accent text-accent-foreground"
      : "text-muted-foreground hover:bg-muted hover:text-foreground",
  );

export function AppShell() {
  return (
    <div className="flex min-h-screen bg-background">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border">
        <div className="border-b border-border px-4 py-4">
          <span className="text-lg font-semibold tracking-tight text-foreground">
            NameForge
          </span>
          <p className="text-xs text-muted-foreground">PIM · Odoo 19</p>
        </div>
        <nav className="flex flex-col gap-1 p-3">
          <NavLink to="/" end className={linkClass}>
            Каталог товаров
          </NavLink>
          <NavLink to="/categories" className={linkClass}>
            Настройка категорий
          </NavLink>
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <Outlet />
      </div>
    </div>
  );
}
