import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createUser,
  listUsers,
  resetMfa,
  resetPassword,
  ROLES,
  updateUser,
  type AdminUser,
} from "../../api/admin";
import { useAuth } from "../../hooks/useAuth";
import { ErrorMessage, Loading } from "../StatusMessage";
import ConfirmDialog from "./ConfirmDialog";
import OneTimeSecret from "./OneTimeSecret";

type Pending =
  | { kind: "role"; user: AdminUser; roleId: number }
  | { kind: "active"; user: AdminUser }
  | { kind: "password"; user: AdminUser }
  | { kind: "mfa"; user: AdminUser };

const field = "mt-1 w-full rounded border border-slate-400 px-2 py-1.5 text-sm dark:bg-slate-900";

function describe(p: Pending): { title: string; body: string; label: string; danger: boolean } {
  const name = p.user.username;
  switch (p.kind) {
    case "role":
      return {
        title: `Change ${name}'s role?`,
        body: `${name} becomes ${ROLES.find((r) => r.id === p.roleId)?.name}. They are signed out of every device and get the new permissions when they log in again.`,
        label: "Change role",
        danger: false,
      };
    case "active":
      return p.user.is_active
        ? {
            title: `Deactivate ${name}?`,
            body: `${name} is signed out everywhere and can no longer log in. Their history is kept.`,
            label: "Deactivate",
            danger: true,
          }
        : {
            title: `Reactivate ${name}?`,
            body: `${name} can log in again with their current password.`,
            label: "Reactivate",
            danger: false,
          };
    case "password":
      return {
        title: `Reset ${name}'s password?`,
        body: `A temporary password is created and shown once. ${name} is signed out everywhere and must choose a new password at their next login. Any lockout is cleared.`,
        label: "Reset password",
        danger: true,
      };
    case "mfa":
      return {
        title: `Reset ${name}'s two-factor authentication?`,
        body: `Use this when ${name} has lost their authenticator. They are signed out and set up two-factor authentication again at their next login.`,
        label: "Reset 2FA",
        danger: true,
      };
  }
}

/** User management (§4.5): create, role, deactivate/reactivate, reset password and MFA. */
export default function AdminUsers() {
  const qc = useQueryClient();
  const { user: me } = useAuth();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: listUsers });
  const [form, setForm] = useState({ username: "", email: "", role_id: 2 });
  const [creating, setCreating] = useState(false);
  const [roleDraft, setRoleDraft] = useState<Record<number, number>>({});
  const [pending, setPending] = useState<Pending | null>(null);
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);
  const [notice, setNotice] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin", "users"] });

  const create = useMutation({
    mutationFn: () =>
      createUser({ ...form, username: form.username.trim(), email: form.email.trim() }),
    onSuccess: (r) => {
      setSecret({
        label: `Temporary password for ${r.user.username}`,
        value: r.temporary_password,
      });
      setNotice(r.message);
      setForm({ username: "", email: "", role_id: 2 });
      setCreating(false);
      refresh();
    },
  });
  const act = useMutation({
    mutationFn: async (
      p: Pending,
    ): Promise<{ message: string; user: AdminUser; temporary_password?: string }> => {
      const id = p.user.user_id;
      if (p.kind === "role") return updateUser(id, { role_id: p.roleId });
      if (p.kind === "active") return updateUser(id, { is_active: !p.user.is_active });
      if (p.kind === "password") return resetPassword(id);
      return resetMfa(id);
    },
    onSuccess: (r) => {
      setNotice(r.message);
      if (r.temporary_password)
        setSecret({
          label: `Temporary password for ${r.user.username}`,
          value: r.temporary_password,
        });
      setPending(null);
      refresh();
    },
  });

  if (users.isPending) return <Loading label="Loading users…" />;
  if (users.isError) return <ErrorMessage error={users.error} onRetry={() => users.refetch()} />;

  return (
    <section aria-labelledby="users-title" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="users-title" className="text-xl font-semibold">
          Users
        </h2>
        {!creating && (
          <button
            type="button"
            onClick={() => {
              create.reset();
              setCreating(true);
            }}
            className="rounded bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800"
          >
            Create a user
          </button>
        )}
      </div>
      <p role="status" className="text-sm text-emerald-800 dark:text-emerald-300">
        {notice}
      </p>
      {secret && (
        <OneTimeSecret
          label={secret.label}
          value={secret.value}
          note="Give it to the user through a separate channel (not email together with the username). They must change it when they log in. It will not be shown again."
          onDismiss={() => setSecret(null)}
        />
      )}
      {creating && (
        <form
          aria-label="Create a user"
          className="grid gap-3 rounded border border-slate-300 p-4 sm:grid-cols-3 dark:border-slate-700"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <label className="text-sm">
            Username
            <input
              className={field}
              required
              pattern="[a-z0-9][a-z0-9_.\-]{2,39}"
              title="3–40 characters: lower-case letters, digits, dot, dash or underscore"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value.toLowerCase() })}
            />
          </label>
          <label className="text-sm">
            Email
            <input
              type="email"
              className={field}
              required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </label>
          <label className="text-sm">
            Role
            <select
              className={field}
              value={form.role_id}
              onChange={(e) => setForm({ ...form, role_id: Number(e.target.value) })}
            >
              {ROLES.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
          {create.error && (
            <div className="sm:col-span-3">
              <ErrorMessage error={create.error} />
            </div>
          )}
          <div className="flex gap-2 sm:col-span-3">
            <button
              type="submit"
              disabled={create.isPending}
              className="rounded bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800 disabled:opacity-60"
            >
              Create user
            </button>
            <button
              type="button"
              onClick={() => setCreating(false)}
              className="rounded border border-slate-400 px-4 py-2 text-sm"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">User accounts</caption>
          <thead className="border-b border-slate-400">
            <tr>
              <th scope="col" className="py-2 pr-3">
                User
              </th>
              <th scope="col" className="pr-3">
                Role
              </th>
              <th scope="col" className="pr-3">
                Status
              </th>
              <th scope="col" className="pr-3">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {users.data.users.map((u) => {
              const self = u.user_id === me?.user_id;
              const draft = roleDraft[u.user_id] ?? u.role_id;
              return (
                <tr
                  key={u.user_id}
                  className="border-b border-slate-200 align-top dark:border-slate-800"
                >
                  <th scope="row" className="py-2 pr-3 font-normal">
                    <span className="font-medium">{u.username}</span>
                    {self && <span className="ml-1 text-slate-600 dark:text-slate-400">(you)</span>}
                    <span className="block text-slate-600 dark:text-slate-400">{u.email}</span>
                  </th>
                  <td className="pr-3">
                    {self ? (
                      u.role_name
                    ) : (
                      <span className="flex items-center gap-1">
                        <label className="sr-only" htmlFor={`role-${u.user_id}`}>
                          Role for {u.username}
                        </label>
                        <select
                          id={`role-${u.user_id}`}
                          className="rounded border border-slate-400 px-1 py-1 dark:bg-slate-900"
                          value={draft}
                          onChange={(e) =>
                            setRoleDraft({ ...roleDraft, [u.user_id]: Number(e.target.value) })
                          }
                        >
                          {!ROLES.some((r) => r.id === u.role_id) && (
                            <option value={u.role_id} disabled>
                              {u.role_name} (retired)
                            </option>
                          )}
                          {ROLES.map((r) => (
                            <option key={r.id} value={r.id}>
                              {r.name}
                            </option>
                          ))}
                        </select>
                        {draft !== u.role_id && (
                          <button
                            type="button"
                            className="underline"
                            aria-label={`Apply role for ${u.username}`}
                            onClick={() => setPending({ kind: "role", user: u, roleId: draft })}
                          >
                            Apply
                          </button>
                        )}
                      </span>
                    )}
                  </td>
                  <td className="pr-3">
                    {u.is_active ? "Active" : "Deactivated"}
                    {u.locked && " · locked"}
                    {u.must_change_password && " · must change password"}
                    <span className="block text-slate-600 dark:text-slate-400">
                      2FA {u.mfa_enabled ? "on" : "off"}
                    </span>
                  </td>
                  <td className="space-x-2 whitespace-nowrap pr-3">
                    {self ? (
                      <span className="text-slate-600 dark:text-slate-400">
                        Another administrator manages your account
                      </span>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="underline"
                          aria-label={`${u.is_active ? "Deactivate" : "Reactivate"} ${u.username}`}
                          onClick={() => setPending({ kind: "active", user: u })}
                        >
                          {u.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                        <button
                          type="button"
                          className="underline"
                          aria-label={`Reset password for ${u.username}`}
                          onClick={() => setPending({ kind: "password", user: u })}
                        >
                          Reset password
                        </button>
                        {u.mfa_enabled && (
                          <button
                            type="button"
                            className="underline"
                            aria-label={`Reset 2FA for ${u.username}`}
                            onClick={() => setPending({ kind: "mfa", user: u })}
                          >
                            Reset 2FA
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {act.error && <ErrorMessage error={act.error} />}
      {pending &&
        (() => {
          const d = describe(pending);
          return (
            <ConfirmDialog
              title={d.title}
              confirmLabel={d.label}
              danger={d.danger}
              busy={act.isPending}
              onConfirm={() => act.mutate(pending)}
              onCancel={() => setPending(null)}
            >
              {d.body}
            </ConfirmDialog>
          );
        })()}
    </section>
  );
}
