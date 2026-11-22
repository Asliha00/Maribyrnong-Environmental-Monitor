/**
 * Privacy notice (SEC-29, Privacy Act 1988 / APPs).
 * TODO(team): the team and the council must review this wording before submission.
 */
export default function PrivacyPage() {
  return (
    <section aria-labelledby="page-title" className="max-w-prose space-y-3">
      <h1 id="page-title" className="text-2xl font-semibold">
        Privacy notice
      </h1>
      <p>
        This dashboard collects only the personal information needed to give you access: your name,
        email address and role.
      </p>
      <p>
        It is stored in a database hosted in Sydney, Australia, and is used only to sign you in and
        to record actions for security auditing.
      </p>
      <p>To access or correct your information, contact your system administrator.</p>
    </section>
  );
}
