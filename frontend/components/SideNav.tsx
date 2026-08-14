"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { isDesktop } from "@/lib/desktop";
import type { User } from "@/lib/types";

import { AccountMenu } from "./AccountMenu";
import { ProjectSwitcher } from "./ProjectSwitcher";

/* ─── Consistent Icons (24x24, 1.75 stroke, round caps/joins) ─────────────── */

function BrandLogo({ className }: { className?: string }) {
  return (
    <div
      className={`flex items-center justify-center bg-accent text-accent-contrast border border-accent ${
        className || "h-7 w-7"
      }`}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="square"
        strokeLinejoin="miter"
        className="h-4 w-4"
      >
        <polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2" />
        <line x1="12" y1="22" x2="12" y2="15.5" />
        <polyline points="22 8.5 12 15.5 2 8.5" />
      </svg>
    </div>
  );
}

function IconDashboard({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-5 w-5"}
    >
      <rect width="7" height="9" x="3" y="3" />
      <rect width="7" height="5" x="14" y="3" />
      <rect width="7" height="9" x="14" y="12" />
      <rect width="7" height="5" x="3" y="16" />
    </svg>
  );
}

function IconCorpus({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-5 w-5"}
    >
      <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
      <path d="M6 6h10" />
      <path d="M6 10h10" />
      <path d="M6 14h6" />
    </svg>
  );
}

function IconHistory({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-5 w-5"}
    >
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
      <path d="M12 7v5l4 2" />
    </svg>
  );
}

function IconChat({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-5 w-5"}
    >
      <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
      <path d="M8 12h.01" />
      <path d="M12 12h.01" />
      <path d="M16 12h.01" />
    </svg>
  );
}

function IconPlus({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-4 w-4"}
    >
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

function IconCollapse({ className, collapsed }: { className?: string; collapsed: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-4 w-4"}
    >
      <rect width="18" height="18" x="3" y="3" />
      <path d="M9 3v18" />
      {collapsed ? (
        <path d="m14 15 3-3-3-3" />
      ) : (
        <path d="m16 15-3-3 3-3" />
      )}
    </svg>
  );
}

function IconMenu({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-6 w-6"}
    >
      <line x1="4" x2="20" y1="12" y2="12" />
      <line x1="4" x2="20" y1="6" y2="6" />
      <line x1="4" x2="20" y1="18" y2="18" />
    </svg>
  );
}

function IconClose({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-5 w-5"}
    >
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </svg>
  );
}

/* ─── Navigation Item ─────────────────────────────────────────────────────── */

interface NavItemProps {
  href: string;
  label: string;
  icon: React.ReactNode;
  collapsed?: boolean;
  onClick?: () => void;
}

function NavItem({ href, label, icon, collapsed, onClick }: NavItemProps) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      title={collapsed ? label : undefined}
      className={`group relative flex items-center font-medium transition-colors duration-120 ${
        collapsed
          ? "h-9 w-9 justify-center mx-auto"
          : "h-9 px-3 text-[0.8125rem] gap-3"
      } ${
        active
          ? "bg-bg-elevated text-accent font-semibold border-l-2 border-accent"
          : "text-text-secondary hover:bg-bg-elevated hover:text-text-primary border-l-2 border-transparent"
      }`}
    >
      {/* Icon */}
      <span
        className={`shrink-0 ${
          active ? "text-accent" : "text-text-muted group-hover:text-text-primary"
        }`}
      >
        {icon}
      </span>

      {/* Label */}
      {!collapsed && <span className="truncate">{label}</span>}
    </Link>
  );
}

/* ─── Primary SideNav Component ───────────────────────────────────────────── */

export function SideNav({ user }: { user?: User }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const renderNavContent = (isMobile = false) => (
    <div className="flex h-full flex-col justify-between p-3">
      {/* Top Section: Brand + Actions + Nav Items */}
      <div className="space-y-4">
        {/* Brand Header */}
        <div className={`flex items-center ${collapsed && !isMobile ? "flex-col gap-2.5" : "justify-between"} px-1 pt-1`}>
          <Link
            href="/dashboard"
            className="flex items-center gap-2.5 group overflow-hidden"
            title={collapsed && !isMobile ? "Research Assistant" : undefined}
          >
            <BrandLogo className="transition-transform duration-200 group-hover:scale-105 shrink-0" />
            {(!collapsed || isMobile) && (
              <div className="flex flex-col">
                <span className="font-serif text-[1rem] font-bold tracking-tight text-text-primary leading-tight">
                  Research
                </span>
                <span className="font-mono text-[0.625rem] font-semibold tracking-widest text-text-muted uppercase leading-tight">
                  Assistant
                </span>
              </div>
            )}
          </Link>

          {!isMobile && (
            <button
              type="button"
              onClick={() => setCollapsed(!collapsed)}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="flex h-6.5 w-6.5 items-center justify-center text-text-muted hover:bg-bg-elevated hover:text-text-primary transition-colors duration-120 shrink-0 border border-transparent hover:border-border"
            >
              <IconCollapse collapsed={collapsed} />
            </button>
          )}
        </div>

        {/* Workspace: which project you're in, before anything scoped by it */}
        <div className="pt-1">
          {(!collapsed || isMobile) && (
            <div className="px-2 pb-1 font-mono text-[0.6875rem] font-semibold uppercase tracking-wider text-text-muted">
              Workspace
            </div>
          )}
          <ProjectSwitcher collapsed={collapsed && !isMobile} menuDirection="down" />
        </div>

        {/* New Research Quick Button */}
        <div className="pt-1">
          <Link
            href="/dashboard"
            onClick={() => isMobile && setMobileOpen(false)}
            title={collapsed && !isMobile ? "New Research" : undefined}
            className={`btn btn-primary w-full ${
              collapsed && !isMobile
                ? "h-9 w-9 p-0 justify-center mx-auto"
                : "h-9 px-3 text-xs justify-center"
            }`}
          >
            <IconPlus className="h-4 w-4 shrink-0" />
            {(!collapsed || isMobile) && <span>New Research</span>}
          </Link>
        </div>

        {/* Nav Links */}
        <nav className="space-y-1 pt-2">
          {(!collapsed || isMobile) && (
            <div className="px-2 pb-1 font-mono text-[0.6875rem] font-semibold uppercase tracking-wider text-text-muted">
              Navigation
            </div>
          )}
          <NavItem
            href="/dashboard"
            label="Dashboard"
            icon={<IconDashboard />}
            collapsed={collapsed && !isMobile}
            onClick={() => isMobile && setMobileOpen(false)}
          />
          <NavItem
            href="/corpus"
            label="Corpus"
            icon={<IconCorpus />}
            collapsed={collapsed && !isMobile}
            onClick={() => isMobile && setMobileOpen(false)}
          />
          <NavItem
            href="/history"
            label="History"
            icon={<IconHistory />}
            collapsed={collapsed && !isMobile}
            onClick={() => isMobile && setMobileOpen(false)}
          />
          {!isDesktop && (
            <NavItem
              href="/chat"
              label="Chat"
              icon={<IconChat />}
              collapsed={collapsed && !isMobile}
              onClick={() => isMobile && setMobileOpen(false)}
            />
          )}
        </nav>
      </div>

      {/* Bottom Section: Profile */}
      <div className="pt-4 border-t border-border">
        {/* User Account Card */}
        <div>
          {user ? (
            <AccountMenu user={user} collapsed={collapsed && !isMobile} />
          ) : (
            <div
              className={`animate-pulse bg-bg-elevated ${
                collapsed && !isMobile ? "h-9 w-9 mx-auto" : "h-11 w-full"
              }`}
              aria-hidden
            />
          )}
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile Top Bar */}
      <header className="md:hidden shrink-0 flex h-14 items-center justify-between border-b border-border bg-bg-base/90 px-4 backdrop-blur-md z-30">
        <Link href="/dashboard" className="flex items-center gap-2 font-bold text-text-primary">
          <BrandLogo className="h-6 w-6" />
          <span className="text-sm font-semibold tracking-tight">Research Assistant</span>
        </Link>
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          className="border border-transparent p-2 text-text-secondary hover:border-border hover:bg-bg-elevated hover:text-text-primary transition-colors"
          aria-label="Open menu"
        >
          <IconMenu />
        </button>
      </header>

      {/* Desktop Sidebar (Left Rail / Fixed Width) */}
      <aside
        className={`hidden md:flex flex-col shrink-0 border-r border-border bg-bg-surface transition-all duration-200 z-20 ${
          collapsed ? "w-16" : "w-60"
        }`}
      >
        {renderNavContent(false)}
      </aside>

      {/* Mobile Slide-over Drawer */}
      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity duration-200"
            aria-hidden="true"
            onClick={() => setMobileOpen(false)}
          />
          {/* Drawer Panel */}
          <aside className="relative flex w-64 max-w-[calc(100%-3.5rem)] flex-col bg-bg-surface border-r border-border shadow-2xl z-10 animate-fade-in">
            <div className="absolute right-2 top-2 z-20">
              <button
                type="button"
                className="flex h-8 w-8 items-center justify-center border border-transparent text-text-muted hover:border-border hover:bg-bg-elevated hover:text-text-primary focus:outline-none transition-colors"
                onClick={() => setMobileOpen(false)}
              >
                <span className="sr-only">Close sidebar</span>
                <IconClose />
              </button>
            </div>
            {renderNavContent(true)}
          </aside>
        </div>
      )}
    </>
  );
}
