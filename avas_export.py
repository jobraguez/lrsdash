#!/usr/bin/env python3
# clean_evaluations.py — Limpeza dos CSVs de avaliação (ID + respostas)

import pandas as pd
import os

# ─── CONFIGURAÇÃO ───────────────────────────────────────────────
FILES = {
    "diagnostica": "A2D.12-Avaliação Diagnóstica-notas.csv",
    "final":       "A2D.12-Avaliação Final-notas.csv",
    "satisfacao":  "Avalia_o_Satisfa_o_do_curso.csv",
}

# Colunas a remover em cada ficheiro
DROP_COLUMNS = {
    "diagnostica": ["Apelido", "Nome", "E-mail", "Estado", "Iniciada", "Terminada"],
    "final":       ["Apelido", "Nome", "E-mail", "Estado", "Iniciada", "Terminada"],
    "satisfacao":  [
        "Resposta",
        "Data/hora de submissão:",
        "Instituição",
        "Departamento",
        "Disciplina",
        "Grupo",
        "Nome completo",
        "Nome de utilizador",
        "Concluído",
        "E-mail"
    ],
}

# ─── FUNÇÃO DE LIMPEZA ───────────────────────────────────────────
def clean_file(key: str, path: str):
    if not os.path.isfile(path):
        print(f"⚠️  Ficheiro não encontrado: {path}")
        return

    # 1) Leitura automática do separador e remoção de BOM/spaces
    df = pd.read_csv(path, sep=None, engine="python", encoding="utf8")
    df.columns = df.columns.str.replace('\ufeff', '', regex=False).str.strip()

    # 2) Elimina as colunas indesejadas
    to_drop = DROP_COLUMNS.get(key, [])
    df_clean = df.drop(columns=to_drop, errors="ignore")

    # 3) Se a primeira coluna não chamar "id", renomeia-a
    first = df_clean.columns[0]
    if first.lower() != "id":
        df_clean = df_clean.rename(columns={ first: "id" })

    # 4) Escreve o CSV limpo
    out_file = f"{key}_clean.csv"
    df_clean.to_csv(out_file, index=False, encoding="utf8")
    print(f"✔️  {out_file} criado com colunas: {list(df_clean.columns)}")

def main():
    print("🔹 Iniciando limpeza dos ficheiros de avaliação...\n")
    for key, filepath in FILES.items():
        clean_file(key, filepath)
    print("\n🔹 Limpeza concluída.")

if __name__ == "__main__":
    main()
