import { useState, type FormEvent } from "react";
import { login, type AuthUser } from "./auth";

type Props = {
  onSuccess: (user: AuthUser) => void;
};

export default function Login({ onSuccess }: Props) {
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("ChangeMe!123");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await login(email.trim().toLowerCase(), password);
      onSuccess(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="gate-root">
      <div className="gate-aurora" />
      <form className="gate-form glass-panel" onSubmit={submit}>
        <h2>Frontline Desk — Staff sign in</h2>
        <p className="small">
          Real JWT authentication. Seed admin is created on first launch.
        </p>
        <label className="field">
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label className="field">
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <div className="small risk-high">{error}</div>}
        <button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="small" style={{ marginTop: "0.75rem" }}>
          Default seed:{" "}
          <span className="mono">admin@example.com / ChangeMe!123</span>
        </p>
      </form>
    </div>
  );
}
