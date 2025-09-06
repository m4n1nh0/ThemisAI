from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
from typing import Optional, List

from app.config.settings import settings


DEFAULT_CANDIDATES = [
    "/app/llama.cpp/build/bin/llama-cli",
    "/app/llama.cpp/build/bin/llama-bin",
    "/app/llama.cpp/build/bin/llama-simple",
    "/app/llama.cpp/build/bin/main",
    "/app/llama.cpp/build/bin/llama",
]


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _candidate_bins_from_dir(dir_path: str) -> List[str]:
    """Retorna possíveis executáveis dentro de um diretório."""
    if not os.path.isdir(dir_path):
        return []
    paths: List[str] = []
    # prioriza nomes mais comuns
    for name in ("llama-cli", "llama-bin", "llama-simple", "main", "llama"):
        p = os.path.join(dir_path, name)
        if _is_executable(p):
            paths.append(p)
    try:
        for name in os.listdir(dir_path):
            if name.startswith("llama-"):
                p = os.path.join(dir_path, name)
                if _is_executable(p):
                    paths.append(p)
    except Exception:
        pass
    return paths


def _search_path_for_llama_bins() -> List[str]:
    """Procura no PATH qualquer binário que comece com 'llama-'."""
    found: List[str] = []
    path = os.environ.get("PATH", "")
    for d in path.split(os.pathsep):
        try:
            for name in os.listdir(d):
                if name.startswith("llama-"):
                    cand = os.path.join(d, name)
                    if _is_executable(cand):
                        found.append(cand)
        except Exception:
            continue
    return found


class LlamaService:
    """
    Adapter para o binário do llama.cpp.
    - Usa LLAMA_CPP_PATH (env/config) se for executável.
    - Caso contrário, autodetecta um executável válido.
    - Decide automaticamente o modo de prompt (posicional vs. '-p') e faz fallback.
    """

    def __init__(
        self,
        llama_cpp: Optional[str] = None,
        model_path: Optional[str] = None,
        default_ngl: str = "0",
        default_extra_args: Optional[List[str]] = None,
    ) -> None:
        self.llama_cpp = llama_cpp or settings.LLAMA_CPP_PATH
        self.model_path = model_path or settings.MODEL_PATH
        self.default_ngl = default_ngl
        self.default_extra_args = default_extra_args or []
        self._validate_paths()
        self._prefer_positional = os.path.basename(self.llama_cpp).startswith("llama-simple")

    def _autodetect_bin(self) -> Optional[str]:
        if os.path.isdir(self.llama_cpp):
            for cand in _candidate_bins_from_dir(self.llama_cpp):
                return cand

        for p in DEFAULT_CANDIDATES:
            if _is_executable(p):
                return p

        maybe_dir = os.path.dirname(self.llama_cpp)
        if os.path.isdir(maybe_dir):
            for cand in _candidate_bins_from_dir(maybe_dir):
                return cand

        found = _search_path_for_llama_bins()
        if found:
            return found[0]

        return None

    def _validate_paths(self) -> None:
        if not _is_executable(self.llama_cpp):
            cand = self._autodetect_bin()
            if cand:
                print(f"[llama] Aviso: LLAMA_CPP_PATH inválido ('{self.llama_cpp}'). Usando '{cand}'.")
                self.llama_cpp = cand
            else:
                print(f"[llama] Aviso: caminho não é executável: '{self.llama_cpp}'. Verifique LLAMA_CPP_PATH.")
        # valida modelo
        if not os.path.isfile(self.model_path):
            print(f"[llama] Aviso: modelo não encontrado em '{self.model_path}'. Verifique MODEL_PATH.")

    def _build_command(
        self,
        prompt: str,
        max_tokens: int,
        use_prompt_flag: Optional[bool] = None,
        extra_args: Optional[List[str]] = None,
    ) -> List[str]:
        """
        use_prompt_flag:
            True  -> usa "-p <prompt>"
            False -> usa "<prompt>" posicional
            None  -> decide automaticamente (posicional se for 'llama-simple', senão '-p')
        """
        if use_prompt_flag is None:
            use_prompt_flag = not self._prefer_positional

        cmd = [
            self.llama_cpp,
            "-m", self.model_path,
            "-n", str(max_tokens),
            "-ngl", self.default_ngl,
        ]
        if extra_args:
            cmd.extend(extra_args)
        else:
            cmd.extend(self.default_extra_args)
        if use_prompt_flag:
            cmd.extend(["-p", prompt])
        else:
            cmd.append(prompt)
        return cmd

    # síncrono
    def generate_response(
        self,
        prompt: str,
        max_tokens: int = 200,
        extra_args: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> str:
        import subprocess

        if not _is_executable(self.llama_cpp):
            raise RuntimeError(f"LLaMA binário inválido: {self.llama_cpp}")
        if not os.path.isfile(self.model_path):
            raise RuntimeError(f"Modelo não encontrado: {self.model_path}")

        # tentativa 1: modo preferido pelo executável atual
        initial_flag = not self._prefer_positional
        cmd = self._build_command(prompt, max_tokens, use_prompt_flag=initial_flag, extra_args=extra_args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result.stdout.strip()

        fallback_flag = not initial_flag
        fallback_cmd = self._build_command(prompt, max_tokens, use_prompt_flag=fallback_flag, extra_args=extra_args)
        fallback = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=timeout)
        if fallback.returncode != 0:
            stderr = (result.stderr or "") + "\n" + (fallback.stderr or "")
            raise RuntimeError(
                f"LLaMA falhou (exit {fallback.returncode}).\n"
                f"cmd: {shlex.join(fallback_cmd)}\n"
                f"stderr:\n{stderr}"
            )
        return fallback.stdout.strip()

    # assíncrono
    async def generate_response_async(
        self,
        prompt: str,
        max_tokens: int = 200,
        extra_args: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> str:
        if not _is_executable(self.llama_cpp):
            raise RuntimeError(f"LLaMA binário inválido: {self.llama_cpp}")
        if not os.path.isfile(self.model_path):
            raise RuntimeError(f"Modelo não encontrado: {self.model_path}")

        # tentativa 1: modo preferido pelo executável atual
        initial_flag = not self._prefer_positional
        cmd = self._build_command(prompt, max_tokens, use_prompt_flag=initial_flag, extra_args=extra_args)
        try:
            stdout, stderr, returncode = await self._run_async(cmd, timeout=timeout)
            if returncode == 0:
                return stdout.strip()
        except asyncio.TimeoutError:
            raise RuntimeError(f"LLaMA timeout.\ncmd: {shlex.join(cmd)}")

        # fallback: modo inverso
        fallback_flag = not initial_flag
        fallback_cmd = self._build_command(prompt, max_tokens, use_prompt_flag=fallback_flag, extra_args=extra_args)
        try:
            stdout, stderr, returncode = await self._run_async(fallback_cmd, timeout=timeout)
            if returncode != 0:
                raise RuntimeError(
                    f"LLaMA falhou (exit {returncode}).\n"
                    f"cmd: {shlex.join(fallback_cmd)}\n"
                    f"stderr:\n{stderr}"
                )
            return stdout.strip()
        except asyncio.TimeoutError:
            raise RuntimeError(f"LLaMA timeout.\ncmd: {shlex.join(fallback_cmd)}")

    async def _run_async(self, cmd: List[str], timeout: Optional[float] = None):
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            raise
        return stdout.decode(errors="ignore"), stderr.decode(errors="ignore"), proc.returncode


def get_llama_service() -> LlamaService:
    return LlamaService()
