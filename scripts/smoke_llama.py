from __future__ import annotations
import argparse, os, shlex, subprocess, sys, multiprocessing
from glob import glob

DEFAULT_BIN_CANDIDATES = [
    "/app/llama.cpp/build/bin/llama-cli",
    "/app/llama.cpp/build/bin/llama-bin",
    "/app/llama.cpp/build/bin/llama-simple",
    "/app/llama.cpp/build/bin/main",
    "/app/llama.cpp/build/bin/llama",
]


def is_exec(p): return os.path.isfile(p) and os.access(p, os.X_OK)


def autodetect_llama_bin(current: str | None):
    if current and os.path.isdir(current):
        for n in ["llama-cli", "llama-bin", "llama-simple", "main", "llama"]:
            p = os.path.join(current, n)
            if is_exec(p): return p
    for p in DEFAULT_BIN_CANDIDATES:
        if is_exec(p): return p
    if current:
        maybe_dir = os.path.dirname(current)
        for n in ["llama-cli", "llama-bin", "llama-simple", "main", "llama"]:
            p = os.path.join(maybe_dir, n)
            if is_exec(p): return p
    for d in os.environ.get("PATH", "").split(os.pathsep):
        try:
            for n in os.listdir(d):
                if n.startswith("llama-"):
                    p = os.path.join(d, n)
                    if is_exec(p): return p
        except Exception:
            pass
    return None


def discover_model(current: str | None):
    if current and os.path.isfile(current): return current
    for pat in ("/models/**/*.gguf", "/models/*.gguf"):
        m = glob(pat, recursive=True)
        if m: return m[0]
    return None


def run(cmd: list[str], timeout: int = 900):
    print(f"\n$ {shlex.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="Olá")
    ap.add_argument("--max-tokens", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=900)  # 15 min p/ 1ª carga
    ap.add_argument("--threads", type=int, default=max(1, multiprocessing.cpu_count() - 1))
    args = ap.parse_args()

    llama = os.getenv("LLAMA_CPP_PATH", "/app/llama.cpp/build/bin/llama-cli")
    model = os.getenv("MODEL_PATH")

    print(f"LLAMA_CPP_PATH (env): {llama}")
    print(f"MODEL_PATH     (env): {model}")
    print(f"Threads (-t)   : {args.threads}")
    print("Obs.: a 1ª execução pode levar vários minutos para carregar o modelo.\n")

    if not is_exec(llama):
        auto = autodetect_llama_bin(llama)
        if not auto:
            print(f"[erro] Não achei executável válido: {llama}")
            return 2
        print(f"[ok] Autodetectado executável: {auto}")
        llama = auto

    model = discover_model(model)
    if not model:
        print("[erro] Modelo .gguf não encontrado em /models.")
        return 3
    print(f"[ok] Modelo: {model}")

    # help
    try:
        cp = run([llama, "-h"], timeout=20)
        if cp.stdout: print(cp.stdout[:300])
    except subprocess.TimeoutExpired:
        print("[aviso] Timeout no -h (ignorado)")

    # WARM-UP: carrega o modelo e sai sem gerar token
    try:
        cp = run([llama, "-m", model, "-n", "0", "-ngl", "0", "-t", str(args.threads), "-p", ""],
                 timeout=args.timeout)
        print("[ok] Warm-up concluído.")
    except subprocess.TimeoutExpired:
        print("[erro] Timeout no warm-up. Tente aumentar --timeout ou acelerar o storage (/models).")
        return 4

    # INFERÊNCIA
    try:
        cp = run(
            [llama, "-m", model, "-n", str(args.max_tokens), "-ngl", "0", "-t", str(args.threads), "-p", args.prompt],
            timeout=120)
    except subprocess.TimeoutExpired:
        print("[erro] Timeout na inferência após warm-up.")
        return 5

    out = (cp.stdout or "").strip()
    print("\n--- STDOUT (primeiras linhas) ---")
    print(out[:800] or "(vazio)")
    if cp.returncode != 0 or not out:
        print(f"\n[erro] rc={cp.returncode}. STDERR:\n{(cp.stderr or '')[:400]}")
        return 6

    print("\n[sucesso] Binário e modelo funcionando.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
