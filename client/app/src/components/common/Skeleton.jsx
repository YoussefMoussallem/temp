// Single-purpose skeleton block. Tailwind only — `animate-pulse` is built
// in, so no extra CSS keyframes. Mirrors the layout footprint of the
// real content so there's no jump when data lands.
//
// Use `<Skeleton className="h-4 w-32" />` for a sized rectangle, or
// compose multiple inside a wrapper that mirrors the eventual layout
// (e.g. a fake "card" with three Skeleton bars inside).
//
// Convention: skeletons are gray-200 by default — sits cleanly against
// both white and gray-50 backgrounds. Pass `className` to override.

export default function Skeleton({ className = "" }) {
  return (
    <div
      aria-hidden="true"
      className={`bg-gray-200 rounded animate-pulse ${className}`}
    />
  );
}
