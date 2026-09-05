export function LogoMark({
  className,
  title,
}: {
  className?: string;
  title?: string;
}) {
  return (
    <svg
      viewBox="0 0 64 64"
      fill="none"
      className={className}
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title ? <title>{title}</title> : null}
      <path
        d="M31.2 13.2 12.6 16.1c-1.05.35-1.7 1.3-1.7 2.4v26.7c0 1.55 1.35 2.6 2.85 2.25L31.2 44.7Z"
        fill="#f3ead2"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      <path
        d="M32.8 13.2 51.4 16.1c1.05.35 1.7 1.3 1.7 2.4v26.7c0 1.55-1.35 2.6-2.85 2.25L32.8 44.7Z"
        fill="#fff8ea"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      <rect x="30.7" y="12.9" width="2.6" height="32" rx="1.2" fill="currentColor" />
      <path d="M14.2 20.4h13.4" stroke="currentColor" strokeWidth="1.55" strokeLinecap="round" />
      <path d="M36.4 20.4h13.4" stroke="currentColor" strokeWidth="1.55" strokeLinecap="round" />
      <circle cx="32" cy="33.2" r="8.15" fill="currentColor" />
      <path
        d="M29.55 29.85c0-.55.58-.9 1.05-.62l6.7 3.97c.48.28.48.96 0 1.24l-6.7 3.97c-.47.28-1.05-.07-1.05-.62Z"
        fill="var(--color-canvas, #0c0d11)"
      />
    </svg>
  );
}
