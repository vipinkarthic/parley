"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { Avatar } from "./Avatar";
import { ZoomLogo } from "./ZoomLogo";
import { ChevronDownIcon, SearchIcon, SettingsIcon } from "./Icons";
import { SoonBadge } from "./SoonBadge";

const NAV_LINKS = [
  { label: "Home", href: "/", soon: false },
  { label: "Meetings", href: "/meetings", soon: false },
  { label: "Contacts", href: "/contacts", soon: false },
  { label: "Whiteboards", href: "/whiteboards", soon: true },
];

export function Navbar() {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  const signOut = () => {
    logout();
    router.replace("/login");
  };

  return (
    <header className="sticky top-0 z-30 border-b border-zoom-line bg-white/95 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1180px] items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-8">
          <Link href="/" aria-label="Home">
            <ZoomLogo />
          </Link>
          <nav className="hidden items-center gap-1 md:flex">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`flex items-center gap-1.5 rounded-md px-3 py-2 text-[15px] transition-colors ${
                  isActive(link.href)
                    ? "font-semibold text-zoom-ink"
                    : "text-zoom-muted hover:text-zoom-ink"
                }`}
              >
                {link.label}
                {link.soon && <SoonBadge />}
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-1 sm:gap-2">
          <Link
            href="/meetings"
            aria-label="Search"
            className="grid h-9 w-9 place-items-center rounded-full text-zoom-muted transition-colors hover:bg-black/5"
          >
            <SearchIcon className="h-5 w-5" />
          </Link>
          <Link
            href="/settings"
            aria-label="Settings"
            className="grid h-9 w-9 place-items-center rounded-full text-zoom-muted transition-colors hover:bg-black/5"
          >
            <SettingsIcon className="h-5 w-5" />
          </Link>

          <div className="relative ml-1" ref={menuRef}>
            <button
              onClick={() => setMenuOpen((v) => !v)}
              className="flex items-center gap-2 rounded-full py-1 pl-1 pr-2 transition-colors hover:bg-black/5"
            >
              <Avatar
                name={user?.name || "You"}
                color={user?.avatar_color}
                size={32}
              />
              <span className="hidden text-sm font-medium text-zoom-ink sm:block">
                {user?.name || "You"}
              </span>
              <ChevronDownIcon className="hidden h-4 w-4 text-zoom-muted sm:block" />
            </button>

            {menuOpen && (
              <div className="absolute right-0 top-12 w-56 overflow-hidden rounded-xl border border-zoom-line bg-white py-1 shadow-modal animate-scale-in">
                <div className="border-b border-zoom-line px-4 py-3">
                  <p className="truncate text-sm font-semibold text-zoom-ink">
                    {user?.name}
                  </p>
                  <p className="truncate text-xs text-zoom-muted">
                    {user?.email}
                  </p>
                </div>
                <Link
                  href="/settings"
                  onClick={() => setMenuOpen(false)}
                  className="block px-4 py-2.5 text-sm text-zoom-ink hover:bg-zoom-field"
                >
                  Settings
                </Link>
                <button
                  onClick={signOut}
                  className="block w-full px-4 py-2.5 text-left text-sm text-[#EF4444] hover:bg-[#FEF3F2]"
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
