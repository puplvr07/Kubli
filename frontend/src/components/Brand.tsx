export function BrandMark({ className = '' }: { className?: string }) {
  return <svg className={className} viewBox="0 0 64 64" fill="none" aria-hidden="true"><rect width="64" height="64" rx="17" fill="currentColor"/><path d="M45.5 39.5a19 19 0 1 0-5.8 6.1" stroke="#A7EFCB" strokeWidth="5" strokeLinecap="round"/><path d="M40 40l9 9" stroke="#A7EFCB" strokeWidth="5" strokeLinecap="round"/><path d="M15.5 33h10l3-6 5.5 12 3-6h11" stroke="#A7EFCB" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
}

export function Wordmark({ className = '' }: { className?: string }) {
  return <span className={`brand-wordmark ${className}`}>tiboq<span>.</span></span>
}
