type Props = { title: string; note: string };

/** Stand-in for pages that later phases build (Phase 0 shell only). */
export default function PlaceholderPage({ title, note }: Props) {
  return (
    <section aria-labelledby="page-title">
      <h1 id="page-title" className="text-2xl font-semibold">
        {title}
      </h1>
      <p className="mt-2 text-slate-600 dark:text-slate-400">{note}</p>
    </section>
  );
}
