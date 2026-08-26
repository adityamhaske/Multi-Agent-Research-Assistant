"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { isDesktop } from "@/lib/desktop";
import type { User } from "@/lib/types";

import { AccountMenu } from "./AccountMenu";
import { IconResearch,
  BrandLogo,
  IconChat,
  IconClose,
  IconCollapse,
  IconCorpus,
  IconOverview,
  IconHistory,
  IconMenu,
  IconPlus,
} from "./icons";
import { ProjectSwitcher } from "./ProjectSwitcher";

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
    <div className="flex h-full flex-col justify-between p-3 min-h-0">
      {/* Top Section: Brand + Actions + Nav Items (scrolls independently) */}
      <div className="space-y-4 overflow-y-auto flex-1 min-h-0 pr-0.5">
        {/* Brand Header */}
        <div className={`flex items-center ${collapsed && !isMobile ? "flex-col gap-2.5" : "justify-between"} px-1 pt-1`}>
          <Link
            href="/research"
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

        {/* The primary action, and it points at the V2 research flow. */}
        <div className="pt-1">
          <Link
            href="/research"
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

        {/* Nav links */}
        <nav className="space-y-1 pt-2">
          <NavItem
            href="/project"
            label="Overview"
            icon={<IconOverview />}
            collapsed={collapsed && !isMobile}
            onClick={() => isMobile && setMobileOpen(false)}
          />
          <NavItem
            href="/research"
            label="Research"
            icon={<IconResearch />}
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
            <div className="my-2 border-t border-border" aria-hidden />
          )}
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

      {/* Bottom Section: Profile (Stays pinned at bottom, never clips popups) */}
      <div className="pt-3 border-t border-border shrink-0 relative">
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
      <header className="md:hidden shrink-0 flex h-14 items-center justify-between border-b border-border bg-bg-base/90 px-4 backdrop-blur-md z-30 sticky top-0">
        <Link href="/research" className="flex items-center gap-2 font-bold text-text-primary">
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
        className={`hidden md:flex flex-col shrink-0 border-r border-border bg-bg-surface sticky top-0 h-screen transition-all duration-200 z-20 ${
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
