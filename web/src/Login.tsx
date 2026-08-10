import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api";

export function Login() {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const login = useMutation({
    mutationFn: () => api.login(username, password),
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
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="아이디"
          autoComplete="username"
          // 아이폰이 첫 글자를 대문자로 바꾸거나 자동수정하면 로그인이 실패한다.
          // 서버가 소문자로 맞춰주지만 화면에 보이는 값도 흔들리지 않는 편이 낫다.
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
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
