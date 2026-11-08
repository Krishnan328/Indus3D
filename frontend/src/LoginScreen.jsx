import React, { useState } from "react";
import { Lock } from "lucide-react";
import { useStore, API } from "./store";
import { useThemeTokens, useIsBrutalist, useIsSoft } from "./theme";

/**
 * Full-screen login gate, rendered when /api/auth/status says
 * auth_required && !authenticated. Respects all four themes
 * (Classic, Workshop, Blueprint, Creme).
 */
export function LoginScreen() {
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [loading, setLoading]   = useState(false);
  const fetchAuthStatus = useStore((s) => s.fetchAuthStatus);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const soft = useIsSoft();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
        credentials: "include",
      });
      const data = await res.json();
      if (res.ok) {
        await fetchAuthStatus();
      } else {
        setError(data.error || "Login failed");
        setPassword("");
      }
    } catch {
      setError("Cannot reach server");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={`flex items-center justify-center h-screen w-full font-sans ${t.page}`}>
      <form
        onSubmit={handleSubmit}
        className={`w-full max-w-sm mx-4 ${t.panel}`}
      >
        <div className={`px-6 py-5 flex items-center gap-3 ${
          brutalist ? "border-b-[3px] border-[#111]"
            : soft ? `border-b ${t.border}`
            : "border-b border-gray-800"
        }`}>
          <Lock size={20} className={brutalist ? "" : soft ? "text-[#7C9B6E]" : "text-blue-500"} />
          <h1 className={`text-xl font-bold ${
            brutalist ? "font-mono tracking-widest"
              : soft ? "text-[#7C9B6E] tracking-wide"
              : "text-blue-500 tracking-widest"
          }`}>
            INDUS<span className={brutalist ? "" : "opacity-80"}>3D</span>
          </h1>
        </div>

        <div className="p-6 flex flex-col gap-4">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoFocus
            disabled={loading}
            className={`w-full px-4 py-2.5 text-sm outline-none ${
              brutalist
                ? "bg-white border-2 border-[#111] text-[#111] font-mono placeholder:text-gray-500"
                : soft
                ? `bg-[#F5F0E8] border ${t.border} text-[#5A4E3C] rounded-xl placeholder:text-[#B5A990]`
                : "bg-gray-800 border border-gray-700 text-white rounded-lg placeholder:text-gray-500"
            }`}
          />
          {error && (
            <div className={`text-xs px-3 py-2 ${
              brutalist ? "bg-red-100 text-red-800 border-2 border-red-800"
                : soft ? "bg-red-50 text-red-600 rounded-lg"
                : "bg-red-900/40 text-red-400 rounded-lg"
            }`}>
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={loading || !password}
            className={`w-full py-2.5 text-sm font-semibold transition-all ${
              brutalist
                ? "bg-[#111] text-white border-2 border-[#111] hover:bg-white hover:text-[#111] disabled:opacity-40"
                : soft
                ? "bg-[#7C9B6E] text-white rounded-xl hover:bg-[#6B8A5E] disabled:opacity-40"
                : "bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-40"
            }`}
          >
            {loading ? "Signing in…" : "Sign In"}
          </button>
        </div>
      </form>
    </div>
  );
}
