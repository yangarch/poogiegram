import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api";

export function Login() {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const login = useMutation({
    mutationFn: () => api.login(email, password),
    onSuccess: (me) => qc.setQueryData(["me"], me),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };

  return (
    <div className="login">
      <form onSubmit={submit}>
        <h1>poogiegram</h1>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="이메일"
          autoComplete="username"
          required
          autoFocus
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="비밀번호"
          autoComplete="current-password"
          required
        />
        <button type="submit" disabled={login.isPending}>
          {login.isPending ? "확인 중…" : "로그인"}
        </button>
        {login.isError && (
          <p className="error">
            {login.error instanceof ApiError ? login.error.message : "로그인에 실패했습니다"}
          </p>
        )}
      </form>
    </div>
  );
}
