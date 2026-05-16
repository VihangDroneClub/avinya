#!/usr/bin/env python3
import os
import subprocess
import shutil
import sys
from pathlib import Path

def main():
    base_dir = Path(__file__).parent.parent.resolve()
    graphify_dir = base_dir / "converters" / "graphify"
    graphify_out = base_dir / "graphify-out"
    ckb_dir = base_dir / "CKB"
    vault_dir = base_dir / "knowledge_vault"

    print("--- Running Graphify Extraction ---")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(graphify_dir)
    env["OLLAMA_API_KEY"] = "dummy"

    try:
        subprocess.run(
            [sys.executable, "-m", "graphify", "extract", ".", "--backend", "ollama"],
            cwd=str(base_dir),
            env=env,
            check=True
        )
        print("--- Running Graphify Clustering ---")
        subprocess.run(
            [sys.executable, "-m", "graphify", "cluster-only", "."],
            cwd=str(base_dir),
            env=env,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Error during graphify extract/cluster: {e}")
        return

    print("--- Moving Outputs to CKB ---")
    ckb_dir.mkdir(exist_ok=True)
    
    for f in ["graph.json", "GRAPH_REPORT.md", "graph.html"]:
        src = graphify_out / f
        dst = ckb_dir / f
        if src.exists():
            shutil.copy2(src, dst)
            print(f"Copied {f} to CKB/")
        else:
            print(f"Warning: {f} not found in {graphify_out}")

    print("--- Exporting Obsidian Vault ---")
    vault_dir.mkdir(exist_ok=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "graphify", "export", "obsidian", "--graph", str(ckb_dir / "graph.json"), "--dir", str(vault_dir)],
            cwd=str(base_dir),
            env=env,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Error during graphify obsidian export: {e}")
        return

    print("--- Graph update complete ---")

if __name__ == "__main__":
    main()
