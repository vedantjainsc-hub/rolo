import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router";

export function AppBar({ title, back, actions }: { title: string; back?: boolean | string; actions?: ReactNode }) {
  const navigate = useNavigate();
  const goBack = () => {
    if (typeof back === "string") navigate(back);
    else if (window.history.state && window.history.state.idx > 0) navigate(-1);
    else navigate("/");
  };
  return (
    <header className="on-navy sticky top-0 z-30 bg-navy-900 text-white pt-[env(safe-area-inset-top)]">
      <div className="mx-auto flex h-14 max-w-[640px] items-center gap-1 px-2 md:px-6">
        {back ? (
          <button
            type="button"
            onClick={goBack}
            aria-label="Back"
            className="inline-flex size-11 items-center justify-center rounded-full hover:bg-white/10"
          >
            <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true">
              <path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        ) : (
          <Link to="/" className="ml-2 inline-flex min-h-11 min-w-11 items-center rounded-md px-1 text-[18px] font-semibold tracking-tight">
            Rolo
          </Link>
        )}
        {back && <span className="truncate text-[18px] font-semibold">{title}</span>}
        <div className="ml-auto flex items-center gap-1">{actions}</div>
      </div>
    </header>
  );
}

export function SettingsLink() {
  return (
    <Link
      to="/settings"
      aria-label="Settings"
      className="inline-flex size-11 items-center justify-center rounded-full hover:bg-white/10"
    >
      <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
      </svg>
    </Link>
  );
}

export function Page({ children }: { children: ReactNode }) {
  return <main id="main" className="mx-auto w-full max-w-[640px] px-5 pb-32 pt-6 md:px-8">{children}</main>;
}
