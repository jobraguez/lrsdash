#!/usr/bin/env python3
import requests, re
import pandas as pd
from requests.auth import HTTPBasicAuth
from urllib.parse import urljoin

# ─── CONFIGURAÇÃO ───────────────────────────────────────────────
ORG_ID   = "27295"
USER     = "b56b2923ba6e2a"
PASS     = "fea5fd69a1166a"
BASE_URL = f"https://watershedlrs.com/watershed/api/organizations/{ORG_ID}/lrs/statements"
AUTH     = HTTPBasicAuth(USER, PASS)
HEADERS  = {
    "Accept": "application/json",
    "X-Experience-API-Version": "1.0.3"
}

# ─── FETCH + PAGINAÇÃO ───────────────────────────────────────────
def fetch_all_statements(since=None, limit=500):
    all_stmts = []
    params = {"limit": limit}
    if since:
        params["since"] = since
    r = requests.get(BASE_URL, auth=AUTH, headers=HEADERS, params=params)
    r.raise_for_status()
    data = r.json()
    all_stmts.extend(data.get("statements", []))
    more = data.get("more")
    while more:
        r = requests.get(urljoin("https://watershedlrs.com", more),
                         auth=AUTH, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        all_stmts.extend(data.get("statements", []))
        more = data.get("more")
    return all_stmts

# ─── EXTRAI MÓDULO via parent ───────────────────────────────────
def extract_module_from_parent(parents):
    if isinstance(parents, list):
        for p in parents:
            url = p.get("id", "")
            m = re.search(r"section\.php\?id=(\d+)", url)
            if m:
                return f"Módulo {m.group(1)}"
    return None

# ─── EXTRAI CMID DO object.id ──────────────────────────────────
def extract_cmid(object_id):
    if isinstance(object_id, str):
        m = re.search(r"view\.php\?id=(\d+)", object_id)
        if m:
            return int(m.group(1))
    return None

def main():
    # 1) Fetch statements a partir de 11/06/2025 12:00 UTC
    since = "2025-06-11T12:00:00Z"
    stmts = fetch_all_statements(since=since, limit=500)
    if not stmts:
        print("⚠️ Nenhum statement retornado.")
        return

    # 2) Flatten JSON
    df = pd.json_normalize(stmts)
    #print(">>> colunas disponíveis:", df.columns.tolist())

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # 3) Extrai cmid
    df["cmid"] = df["object.id"].apply(extract_cmid).astype("Int64")

    # 4) Extrai módulo a partir dos parent
    parent_col = next((c for c in df.columns if "contextActivities.parent" in c), None)
    if parent_col:
        # garante listas e explode
        df[parent_col] = df[parent_col].apply(lambda x: x if isinstance(x, list) else [])
        exploded = df.explode(parent_col)
        exploded["module_parent"] = exploded[parent_col].apply(extract_module_from_parent)
        # retém apenas um módulo_parent por statement
        modules = (
            exploded[["id","module_parent"]]
            .dropna(subset=["module_parent"])
            .drop_duplicates("id")
        )
        df = df.merge(modules, on="id", how="left")
    else:
        df["module_parent"] = pd.NA

    # 5) Tenta ler cmid_module_map.csv e aplicar fallback
    try:
        map_df = pd.read_csv("cmid_module_map.csv", sep=";")
        map_df["cmid"] = map_df["cmid"].astype("Int64")
        map_df.rename(columns={"module":"module_map"}, inplace=True)
        df = df.merge(map_df, on="cmid", how="left")
    except FileNotFoundError:
        df["module_map"] = pd.NA
        print("ℹ️ cmid_module_map.csv não encontrado, só parent será usado.")
    except Exception as e:
        df["module_map"] = pd.NA
        print("⚠️ Erro ao ler cmid_module_map.csv:", e)

    # 6) Preenche módulo definitivo: parent → mapa → Outro
    df["module"] = df["module_parent"].combine_first(df["module_map"]).fillna("Outro")

    # 7) Limpa verb, activity, user
    # ------------------------------

    # (a) Limpa verb
    df["verb"] = (
        df.get("verb.display.en", pd.Series(dtype=str))
        .fillna(df.get("verb.id", "").str.rsplit("/", n=1).str[-1])
    )

    # (b) Descobre quais colunas de descrição e nome existem
    desc_cols = [c for c in df.columns if c.startswith("object.definition.description")]
    name_cols = [c for c in df.columns if c.startswith("object.definition.name.en-US")]

    if desc_cols:
        # Usa primeiro a descrição (texto completo da pergunta), senão o name, senão a URL
        df["activity"] = (
            df[desc_cols[0]]
            .fillna(df[name_cols[0]] if name_cols else "")
            .fillna(df.get("object.id", ""))
        )
    else:
        # Se não existir description, cai no name ou URL
        df["activity"] = (
            df[name_cols[0]] if name_cols
            else df.get("object.id", "")
        )

    # (c) Limpa user
    df["user"] = (
        df.get("actor.account.name", pd.Series(dtype=str))
        .fillna(df.get("actor.mbox", ""))
    )

    # 8) Exporta CSV final
    clean = df[["id","timestamp","user","cmid","module","verb","activity"]]
    clean.to_csv("statements_clean.csv", index=False, encoding="utf8")
    print(f"✅ statements_clean.csv criado com {len(clean)} linhas.")

if __name__ == "__main__":
    main()
