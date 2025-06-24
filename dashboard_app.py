#!/usr/bin/env python3
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import subprocess, sys
import unidecode
from dateutil import parser
import re
import os
from fpdf import FPDF
import tempfile

# --- CONFIGURAÇÃO GERAL ---
st.set_page_config(page_title="Dashboard Animação 2D", layout="wide")

# --- AUTENTICAÇÃO SIMPLES ---
CREDENTIALS = {
    "admin": {"password": "admin123", "view": "admin"},
    "learn": {"password": "learn123", "view": "learn"}
}

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_role = None

if not st.session_state.logged_in:
    st.title("🔒 Login Necessário")
    user = st.text_input("👤 Utilizador")
    pwd = st.text_input("🔑 Password", type="password")
    login_btn = st.button("Entrar")

    if login_btn:
        if user and user in CREDENTIALS and CREDENTIALS[user]["password"] == pwd:
            st.session_state.logged_in = True
            st.session_state.user_role = CREDENTIALS[user]["view"]

        else:
            st.error("Utilizador ou palavra-passe incorretos.")

    st.stop()

    
# ─── 1. Constantes ─────────────────────────────────────────────┐
CSV_FILE = "statements_clean.csv"
DIAG_CSV       = 'diagnostica_clean.csv'
FINAL_CSV      = 'final_clean.csv'
SATISF_CSV     = 'satisfacao_clean.csv'
DIAG_RAW = "a2d12_avaliacao_diagnostica_notas.csv"
FINAL_RAW = "a2d12_avaliação_final-notas.csv"
# ────────────────────────────────────────────────────────────────┘

# --- BOTÃO PARA ATUALIZAR ---
from streamlit.runtime.scriptrunner import RerunException, RerunData
if st.button("🔄 Atualizar dados"):
    # chama o export.py com o mesmo interpretador Python
    subprocess.run([sys.executable, "export.py"], check=True)
    # força o Streamlit a reiniciar o script
    raise RerunException(RerunData())
    
# ──────────────────────────┐
@st.cache_data
# --- FUNÇÃO: EXTRAIR MÉDIAS DE PERGUNTAS DO CSV BRUTO ---
def extract_avg_scores(path):
    
    # 1) Leitura com vírgula como separador
    df_raw = pd.read_csv(path, sep=',', encoding='utf8', dtype=str)

    # 2) Procura a linha 'Média' na primeira coluna
    first_col = df_raw.columns[0]
    mask = df_raw[first_col].str.strip().eq("Média")
    if not mask.any():
        raise ValueError(f"Média row not found in {path}")

    avg_row = df_raw[mask].iloc[0]

    # 3) Seleciona apenas colunas de pergunta, por exemplo 'P. 1 /0,77'
    #    usar regex para pegar colunas que começam por 'P.'
    q_cols = [c for c in df_raw.columns if re.match(r"^\s*P\.\s*\d+", c)]
    if not q_cols:
        raise ValueError(f"No question columns found in {path}")

    # 4) Extrai valores, substitui vírgula por ponto e converte em float
    avg_scores = {}
    for col in q_cols:
        raw = avg_row[col]
        if pd.isna(raw):
            continue
        # mantém apenas a parte numérica antes de qualquer espaço
        # ou "/" para tirar o "/0,77" que acompanha no header
        val_str = re.split(r"[ /]", raw.strip())[0]
        val_str = val_str.replace(",", ".")
        try:
            avg_scores[col] = float(val_str)
        except ValueError:
            # ignora se não der para converter
            continue

    # 5) Retorna Series com índice "P. 1", "P. 2", ...
    #    retirando o resto do texto da coluna
    clean_index = [re.match(r"P\.\s*(\d+)", c).group(0) for c in avg_scores.keys()]
    return pd.Series(list(avg_scores.values()), index=clean_index)

# --- no seu fluxo principal, troque a chamada anterior por:
try:
    diag_avgs  = extract_avg_scores(DIAG_RAW)
    final_avgs = extract_avg_scores(FINAL_RAW)
    # monte um DataFrame para exibir lado a lado
    df_evol = pd.DataFrame({
        "Diagnóstica": diag_avgs,
        "Final":      final_avgs
    }).dropna(how="all")  # tira perguntas que não existem em nenhum
    df_evol["Diferença"] = (df_evol["Final"] - df_evol["Diagnóstica"]).round(1)

    #st.subheader("📈 Evolução Média por Pergunta")
    #st.dataframe(df_evol, use_container_width=True)
    #st.line_chart(df_evol[["Diagnóstica","Final"]])

except Exception as e:
    st.warning(f"Não foi possível extrair as médias dos CSVs brutos: {e}")

# --- FUNÇÃO: CARREGAMENTO DE DADOS ---
def load_data():
    df = pd.read_csv(CSV_FILE)
    df.columns = df.columns.map(str)
    # 2.1 Timestamp → datetime[ns, UTC]
    df["timestamp"] = (
        df["timestamp"]
        .astype(str)  # garante object
        .apply(lambda s: parser.isoparse(s) if s and s.lower() != "nan" else pd.NaT)
        .dt.tz_convert("UTC")
    )
    # 2.2 Limpa módulo de espaços/brancos invisíveis
    df["module"] = df["module"].astype(str).str.strip()
    # avaliações
    df_diag = pd.read_csv(DIAG_CSV)
    df_final = pd.read_csv(FINAL_CSV)
    df_satis = pd.read_csv(SATISF_CSV)
    return df, df_diag, df_final, df_satis

# --- INICIALIZA OS DADOS ---
df, df_diag, df_final, df_satis = load_data()
# Lista de módulos realmente existentes (ordenada)
modules_list = sorted(df["module"].dropna().unique())
# ────────────────────────────────────────────────────────────────┘
def load_satisfacao():
    df = pd.read_csv(SATISF_CSV, encoding="utf8")
    # 1) Concelhos: colunas que começam por “Q05_Distrito”
    concelhos = [c for c in df.columns if c.startswith("Q05_Distrito")]
    # melt para apanhar o concelho com valor True/1
    df_conc = (
        df[["ID"] + concelhos]
        .melt(id_vars="ID", value_vars=concelhos,
              var_name="origem", value_name="flag")
        .query("flag == True or flag == 1")
    )
    df_conc["Distrito"] = df_conc["origem"].str.split("->").str[-1]
    # 2) Escolaridade: colunas que começam por “Q07_Nível”
    escolaridade = [c for c in df.columns if c.startswith("Q07_Nível")]
    df_esc = (
        df[["ID"] + escolaridade]
        .melt(id_vars="ID", value_vars=escolaridade,
              var_name="origem", value_name="flag")
        .query("flag == True or flag == 1")
    )
    df_esc["Escolaridade"] = df_esc["origem"].str.split("->").str[-1]
    # 3) Nacionalidade diretamente
    df_nat = df[["ID", "Q06_Nacionalidade"]].rename(
        columns={"Q06_Nacionalidade": "Nacionalidade"}
    )
    # 4) Junta tudo
    df_demo = (
        df_nat
        .merge(df_conc[["ID", "Distrito"]], on="ID", how="left")
        .merge(df_esc[["ID", "Escolaridade"]], on="ID", how="left")
        .drop(columns="ID")
    )
    # ───────────── Normalização de Nacionalidades ──────────────
    # 1) Lowercase e strip
    df_demo["Nacionalidade"] = (
        df_demo["Nacionalidade"]
        .astype(str)
        .str.lower()
        .str.strip()
    )

    # 2) Dicionário de mapeamento das variantes para o termo canónico
    mapping = {
        # Portuguesa
        "portugal": "Portuguesa",
        "portugual": "Portuguesa",
        "portuguesa": "Portuguesa",
        "potuguesa": "Portuguesa",
        "português": "Portuguesa",
        "pt": "Portuguesa",
    }

    # 3) Aplica o mapeamento, valores não incluídos ficam como 'Outro'
    df_demo["Nacionalidade"] = (
        df_demo["Nacionalidade"]
        .map(mapping)
        .fillna(df_demo["Nacionalidade"].str.title())  # título de variantes desconhecidas
    )
    return df_demo

 # --- Selector de visão ---
    #    view = st.sidebar.radio(
    #    "🗂️ Seleciona a Visão",
    #    ["Visão Admin", "Visão Learn Stats"]
    #)

# ─── VISÃO ADMINISTRATIVA ─────────────────────────────────────────────
if st.session_state.view == "admin":
    st.title("🔧 Visão Admin")
    st.text("Dashboard de administração do curso Animação 2D")
    st.text("Este painel tem dados completos, para uma visão de síntese e já com algumas conclusões, por favor aceda à Visão Learn Stats")

    # ─── MÉTRICAS GERAIS ─────────────────────────────────────────
    st.header("Visão Geral")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Statements", len(df))
    c2.metric("Total Módulos", df["module"].nunique())

    # Normaliza coluna module para filtragem
    df["module_norm"] = (
        df["module"]
        .astype(str)
        .fillna("")
        .apply(unidecode.unidecode)
        .str.lower()
        .str.strip()
    )
    df["verb_lc"] = df["verb"].str.lower()
    
    # Filtra utilizadores que submeteram o questionário de satisfação
    mask_satisf_submit = (
            (df["verb_lc"] == "submitted") &
            (df["module_norm"].str.contains("satisfacao", na=False))
    )

    # Conta utilizadores únicos
    n_users_satisf = df[mask_satisf_submit]["user"].nunique()

    # Atualiza métrica com esse valor
    c3.metric("Total Utilizadores", n_users_satisf)

     # ─── STATEMENTS POR MÓDULO ──────────────────────────────────
    st.subheader("📦 Statements por Módulo")

    # Garante zero para módulos sem statements hoje
    mod_counts = df["module"].value_counts().reindex(modules_list, fill_value=0)

    # Tabela
    st.dataframe(
        mod_counts
        .rename_axis("Módulo")
        .reset_index(name="Contagem")
    )

    # Gráfico de barras
    fig, ax = plt.subplots(figsize=(8,4))
    mod_counts.plot.bar(ax=ax)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_xlabel("Módulo")
    ax.set_ylabel("Número de statements")
    plt.xticks(rotation=45, ha='right')
    st.pyplot(fig)
    plt.tight_layout()
   
    # ─── VERBOS POR MÓDULO ──────────────────────────────────────
    st.subheader("🔤 Verbos mais comuns")
    # 1) Pivot table: linhas = módulo, colunas = verbo, valores = contagem
    verb_counts = df["verb"].value_counts()
    st.dataframe(
        verb_counts
        .rename_axis("Verbo")
        .reset_index(name="Contagem")
    )
    st.bar_chart(verb_counts)
    # ────────────────────────────────────────────────────────────────┘
    # ─── X. Contagem de Verbos por Módulo ────────────────────────────
    st.subheader("📊 Verbos por Módulo")

    # 1) Pivot table: linhas = módulo, colunas = verbo, valores = contagem
    verbs_of_interest = ["completed","answered","progressed","interacted","attempted"]
    # normaliza tudo para lowercase para evitar duplicados
    df["verb_lc"] = df["verb"].str.lower()

    pivot = (
        df[df["verb_lc"].isin(verbs_of_interest)]
        .groupby(["module","verb_lc"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=verbs_of_interest, fill_value=0)
    )

    # 2) Exibe tabela
    st.dataframe(pivot.rename_axis("Módulo").rename(columns=str.capitalize))

    # 3) Gráfico de barras empilhadas (opcional)
    fig2, ax2 = plt.subplots(figsize=(10, 5))
    pivot.plot(
        kind="bar",
        stacked=True,
        ax=ax2
    )
    ax2.set_xlabel("Módulo")
    ax2.set_ylabel("Contagem de Statements")
    ax2.legend(title="Verbo", bbox_to_anchor=(1.02,1), loc="upper left")
    plt.xticks(rotation=45, ha="right")
    st.pyplot(fig2)

    # ─── 7. Evolução Diária de Statements ──────────────────────────┐
    st.subheader("📅 Evolução Diária de Statements")

    # Garante que estamos usando DatetimeIndex
    df_daily = df.set_index("timestamp").resample("D").size()
    st.line_chart(df_daily)
    
    
    # ─── TENTATIVAS Por Pergunta ──────────────────────────────
    st.subheader("❓ Tentativas por Pergunta")
    st.text("Perguntas do módulo 1 ao 4 (perguntas dos conteúdos H5P). ")
    # filtra statements com verbo contendo 'attempt' e 'answer'
    df_attempts = df[df['verb'].str.lower().str.contains('attempt', na=False)]

    # conta tentativas e respondidas por activity
    attempts = df_attempts['activity'].value_counts()

    # mantém só perguntas que começam por "Pergunta"
    mask = attempts.index.str.startswith("Pergunta")
    attempts = attempts[mask]

    # prepara DataFrame final
    df_q = pd.DataFrame({
        'Pergunta': attempts.index,
        'Tentativas': attempts.values,

    })
    if df_q.empty:
        st.info("Não há tentativas registadas em perguntas.")
    else:
        # ordenação interativa
        sort_col = st.selectbox("Ordenar por:", ['Pergunta', 'Tentativas'], index=1)
        asc = st.checkbox("Ordem ascendente", value=False)
        df_q_sorted = df_q.sort_values(sort_col, ascending=asc)
        # exibe tabela completa
        # st.dataframe(df_q_sorted, use_container_width=True)
        # gráfico de barras agrupadas
        fig, ax = plt.subplots(figsize=(10, 5))
        x = range(len(df_q_sorted))
        ax.bar(x, df_q_sorted['Tentativas'], width=0.4, label='Tentativas')

        ax.set_xticks([i + 0.2 for i in x])
        ax.set_xticklabels(df_q_sorted['Pergunta'], rotation=45, ha='right')
        ax.set_xlabel("Pergunta")
        ax.set_ylabel("Contagem")
        ax.legend()
        plt.tight_layout()
        st.pyplot(fig)
    
    # ─── Avaliações & Satisfação ──────────────────────────
    st.header("📊 Avaliação diagnóstica, Avaliação final e Inquérito de Satisfação")
    #st.text("Todas respostas")
    tabs = st.tabs(["Ava. Diagnóstica", "Ava. Final", "Inq. Satisfação"])
    df_diag.columns = [col.replace("id", "Tempo") if col.lower() == "id" else col for col in df_diag.columns]

    with tabs[0]:
        st.subheader("📝 Avaliação Diagnóstica")
        st.dataframe(df_diag, use_container_width=True)
        # exemplo de gráfico de respostas por questão
        if 'Pergunta' in df_diag.columns and 'Resposta' in df_diag.columns:
            q_counts = df_diag.groupby('Pergunta')['Resposta'].value_counts().unstack(fill_value=0)
            st.bar_chart(q_counts)

    with tabs[1]:
        st.subheader("📝 Avaliação Final")
        st.dataframe(df_final, use_container_width=True)
        if 'Pergunta' in df_final.columns and 'Resposta' in df_final.columns:
            qf_counts = df_final.groupby('Pergunta')['Resposta'].value_counts().unstack(fill_value=0)
            st.bar_chart(qf_counts)

    with tabs[2]:
        st.subheader("🙂 Satisfação do Curso")
        st.dataframe(df_satis, use_container_width=True)
        if 'Pergunta' in df_satis.columns and 'Resposta' in df_satis.columns:
            qs_counts = df_satis.groupby('Pergunta')['Resposta'].value_counts().unstack(fill_value=0)
            st.bar_chart(qs_counts)


# ────────────────────────────────────────────────────────────────┘
# ───  Visão Learn Stats ────────────────────────────────────────
else:
    st.title("📊 Visão Learn Stats")
    st.text("Dashboard de estatísticas do curso Animação 2D")
    st.text("Esta visão tem dados já filtrados e com algumas conclusões. Esta visão é aconselhada a professores.")
    #  Carrega dados limpos
    df_sat = pd.read_csv("satisfacao_clean.csv", encoding="utf8")

    #  Caracterização da Amostra
    # ————————————————————————————————————————————————
    st.header("📝Caracterização da Amostra")

    df_satis = load_satisfacao()

    # st.subheader("🔹 Tabela de Caracterização")
    # st.dataframe(df_satis)

    # Distribuições
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Distrito")
        st.bar_chart(df_satis["Distrito"].value_counts())
    with col2:
        st.subheader("Nacionalidade")
        st.bar_chart(df_satis["Nacionalidade"].value_counts())
    with col3:
        st.subheader("Escolaridade")
        st.bar_chart(df_satis["Escolaridade"].value_counts())

        # ─── Tempo Diagnóstica → Satisfação por Utilizador ────────────────
    #st.subheader("⏱️ Tempo")
    #st.text("Tempo médio que os utilizadores levaram a concluir o curso. Foi contabilizado todo o tempo desde que iniciou até que finalizou. Assim mesmo que o utilizador fizesse log-off entre sessões, esse tempo foi contabilizado")
    # 1) Normaliza módulo
    df["module_norm"] = (
        df["module"]
        .fillna("")
        .astype(str)
        .apply(unidecode.unidecode)  # tira acentos
        .str.lower()
    )
    # 2) normaliza verbos
    df["verb_lc"] = df["verb"].str.lower()

    # 3) máscaras corretas
    start_mask = (
            (df["verb_lc"] == "viewed") &
            df["module_norm"].str.contains("diagnostica", na=False)
    )
    end_mask = (
            (df["verb_lc"].isin(["submitted", "answered"])) &
            df["module_norm"].str.contains("satisf", na=False)
    )

    # 5) agrupa e intersecta users
    starts = df[start_mask].groupby("user")["timestamp"].min()
    ends = df[end_mask].groupby("user")["timestamp"].max()
    common = starts.index.intersection(ends.index)

    if len(common) == 0:
        st.warning("⚠️ Não há utilizadores com ambos os eventos de início e fim.")
    else:
        # 6) calcula durações em minutos
        durations = ((ends[common] - starts[common]).dt.total_seconds() / 60).round(1)
        avg = round(durations.mean(), 1)

        # 7) mostra resultados
        #st.metric("⏲️ Tempo Médio (min)", f"{avg}")
        dur_df = durations.reset_index()
        dur_df.columns = ["Utilizador", "Minutos"]
        # st.dataframe(dur_df, use_container_width=True)
        # st.bar_chart(dur_df.set_index("Utilizador")["Minutos"])

       # --- Evolução por Utilizador (Nota Global) ---
        def extract_overall_avg(path):
            # tenta ; e , como separadores
            for sep in (";", ","):
                try:
                    df = pd.read_csv(path, sep=sep, dtype=str, keep_default_na=False)
                except Exception:
                    continue
                if df.shape[1] > 1:
                    break
            else:
                raise ValueError(f"Não consegui ler {path} (sep. ';' ou ',').")

            # localiza a linha onde a primeira coluna é 'Média'
            col0 = df.columns[0]
            mask = df[col0].str.strip().eq("Média")
            if not mask.any():
                raise ValueError(f"Linha 'Média' não encontrada em {path}")

            # captura toda a linha e procura o primeiro valor numérico
            row = df.loc[mask].iloc[0].tolist()
            for cell in row[1:]:
                if isinstance(cell, str) and re.match(r"^\s*\d+[,.]\d+\s*$", cell):
                    return float(cell.strip().replace(",", "."))
            raise ValueError(f"Nenhum valor numérico encontrado na linha 'Média' de {path}")

        st.subheader("📈 Evolução dos utilizadores")
        st.text("A diferença entre a média das notas da avaliação diagnóstica e final.")
        try:
            avg_diag = extract_overall_avg(DIAG_RAW)
            avg_final = extract_overall_avg(FINAL_RAW)
            diff = round(avg_final - avg_diag, 2)

            c1, c2, c3 = st.columns(3)
            c1.metric("Média Diagnóstica", f"{avg_diag:.2f}")
            c2.metric("Média Final", f"{avg_final:.2f}")
            c3.metric("Δ MELHORIA", f"{diff:.2f}")
        except Exception as e:
            st.warning(f"Não foi possível extrair as médias dos CSVs brutos: {e}")

    # --- Evolução por Pergunta (Diagnóstica vs Final) ---
        st.subheader("📈 Evolução por Pergunta")
        st.text("A diferença entre a média das notas da avaliação diagnóstica e da avaliação final por pergunta.")

        # caminhos para os CSVs brutos

        DIAG_RAW = "a2d12_avaliacao_diagnostica_notas.csv"
        FINAL_RAW = "a2d12_avaliação_final-notas.csv"

        # Extract averages
        diag_avgs = extract_avg_scores(DIAG_RAW)
        final_avgs = extract_avg_scores(FINAL_RAW)

        # Build DataFrame
        df_evol = pd.DataFrame({
            "Diagnóstica": diag_avgs,
            "Final": final_avgs
        })

        # Calculate difference if you like
        df_evol["Diferença"] = (df_evol["Final"] - df_evol["Diagnóstica"]).round(2)

        # Display

        # st.dataframe(df_evol, use_container_width=True)
        st.line_chart(df_evol[["Diagnóstica", "Final"]])

    # ─── Top-3 Perguntas Mais Fáceis e Difíceis (Avaliação Final) ───
    st.subheader("🏅 Top-3 Perguntas com melhores e piores classificações (Avaliação Final)")

    # 1) Lê o CSV bruto, autodetectando delimitador
    raw_final = pd.read_csv(
        "a2d12_avaliação_final-notas.csv",
        sep=None,  # deixa o pandas adivinhar vírgula vs ponto‐e‐vírgula
        engine="python",
        dtype=str
    )

    # 2) Descobre qual é a primeira coluna (normalmente "Apelido" ou similar)
    id_col = raw_final.columns[0]

    # 3) Procura a linha “Média” nessa coluna
    mask_avg = (
        raw_final[id_col]
        .astype(str)
        .str.strip()
        .str.lower()
        .eq("média")
    )
    if not mask_avg.any():
        st.error(f"Linha 'Média' não encontrada na coluna {id_col!r}.")
    else:
        avg_row = raw_final.loc[mask_avg].iloc[0]

        # 4) Seleciona apenas as colunas de perguntas, ex: "P. 1 /0,77"
        q_cols = [c for c in raw_final.columns if re.match(r"^P\.\s*\d+", c)]
        if not q_cols:
            st.warning("Nenhuma coluna de pergunta (P. X) encontrada.")
        else:
            # 5) Extrai as médias e converte "8,61" → 8.61
            scores = (
                avg_row[q_cols]
                .str.replace(",", ".", regex=False)
                .astype(float)
            )

            # 6) Computa top‐3 fáceis (maiores médias) e top‐3 difíceis (menores)
            df_easy = (
                scores.nlargest(3)
                .reset_index()
                .rename(columns={"index": "Pergunta", 0: "Média"})
            )
            df_hard = (
                scores.nsmallest(3)
                .reset_index()
                .rename(columns={"index": "Pergunta", 0: "Média"})
            )

            # 7) Exibe lado a lado
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 🟢 3 Mais Fáceis")
                st.dataframe(df_easy)
            with c2:
                st.markdown("#### 🔴 3 Mais Difíceis")
                st.dataframe(df_hard)

    # ───────────────────────────────────────────────────────
    # ─── 6. Tentativas vs Respondidas por Pergunta (Global) ────────
    #st.subheader("❓ Tentativas vs Respondidas por Pergunta (Global)")

    # filtra statements com verbo contendo 'attempt' e 'answer'
    df_attempts = df[df['verb'].str.lower().str.contains('attempt', na=False)]
    df_answered = df[df['verb'].str.lower().str.contains('answer', na=False)]

    # conta tentativas e respondidas por activity
    attempts = df_attempts['activity'].value_counts()
    answered = df_answered['activity'].value_counts()

    # mantém só perguntas que começam por "Pergunta"
    mask = attempts.index.str.startswith("Pergunta")
    attempts = attempts[mask]
    answered = answered.reindex(attempts.index, fill_value=0)

    # prepara DataFrame final
    df_q = pd.DataFrame({
        'Pergunta': attempts.index,
        'Tentativas': attempts.values,
        'Respondida': answered.values
    })

# ─── Perguntas mais fáceis e mais difíceis ─────────

    st.subheader("🏅 Top-3 Perguntas Mais Fáceis e Difíceis (Módulo 1 a 4)")
    col_easy, col_hard = st.columns(2)

    # 3 mais fáceis: só Pergunta e Tentativas
    df_easy = df_q.nsmallest(3, 'Tentativas')[['Pergunta', 'Tentativas']].reset_index(drop=True)
    with col_easy:
        st.subheader("🟢 Mais Fáceis")
        st.dataframe(df_easy)

    # 3 mais difíceis: só Pergunta e Tentativas
    df_hard = df_q.nlargest(3, 'Tentativas')[['Pergunta', 'Tentativas']].reset_index(drop=True)
    with col_hard:
        st.subheader("🔴 Mais Difíceis")
        st.dataframe(df_hard)

    # ————————————————————————————————————————————————
    # 8. Inquérito de Satisfação
    # ————————————————————————————————————————————————

    # 8.3. Resultados por Pergunta
    st.subheader("📊 Satisfação: Resultados por Pergunta")

    # Seleciona apenas colunas cujo nome comece por 'Q' seguido de dígitos
    q_cols = [c for c in df_sat.columns
              if re.match(r"^Q0[1-3](_|$)", c, re.IGNORECASE)]

    if not q_cols:
        st.warning("Nenhuma coluna de pergunta Q01–Q03 encontrada.")
    else:
        # Converte vírgulas para ponto e força números; erros virão como NaN
        df_qnum = df_sat[q_cols].apply(
            lambda col: pd.to_numeric(
                col.astype(str).str.replace(",", ".", regex=False),
                errors="coerce"
            )
        )
        # Calcula média por pergunta, arredonda a 1 casa decimal
        mean_scores = df_qnum.mean().round(1)

        # Tabela interativa (ordenável)
        df_q = mean_scores.reset_index()
        df_q.columns = ["Pergunta", "Média"]
        st.dataframe(df_q, use_container_width=True)
    # Gráfico de barras
        #st.bar_chart(mean_scores)
    # 3) α de Cronbach
    # Remove linhas com NaN em qualquer uma das três
    df_items = df_qnum.dropna(how="any")
    if df_items.shape[0] < 2:
        st.warning("Não há dados suficientes para calcular o α de Cronbach.")
    else:
        n_items = df_items.shape[1]
        item_vars = df_items.var(axis=0, ddof=1)
        total_var = df_items.sum(axis=1).var(ddof=1)
        cronbach_alpha = (n_items / (n_items - 1)) * (1 - item_vars.sum() / total_var)
        st.metric("🧪 α de Cronbach (Inquérito de Satisfação)", f"{cronbach_alpha:.2f}","Excelente!")

    # 🖨️ Botão para gerar relatório
    if st.button("📄 Gerar Relatório em PDF"):
        with st.spinner("A gerar relatório..."):
            # Criar imagens temporárias
            tmp_dir = tempfile.mkdtemp()

            # 1. Gráfico de Distrito
            distrito_fig, ax = plt.subplots()
            df_satis["Distrito"].value_counts().plot(kind="bar", ax=ax)
            ax.set_title("Distribuição por Distrito")
            distrito_path = os.path.join(tmp_dir, "distrito.png")
            distrito_fig.savefig(distrito_path)
            plt.close(distrito_fig)
            # 1.b Nacionalidade
            nacionalidade_fig, ax = plt.subplots()
            df_satis["Nacionalidade"].value_counts().plot(kind="bar", ax=ax)
            ax.set_title("Distribuição por Nacionalidade")
            nacionalidade_path = os.path.join(tmp_dir, "nacionalidade.png")
            nacionalidade_fig.savefig(nacionalidade_path)
            plt.close(nacionalidade_fig)
            # 1.c Escolaridade
            escolaridade_fig, ax = plt.subplots()
            df_satis["Escolaridade"].value_counts().plot(kind="bar", ax=ax)
            ax.set_title("Distribuição por Escolaridade")
            escolaridade_path = os.path.join(tmp_dir, "escolaridade.png")
            escolaridade_fig.savefig(escolaridade_path)
            plt.close(escolaridade_fig)

            tempo_medio_texto = f"Tempo médio de conclusão do curso: {avg} minutos."
            top_easy_txt = "\n".join([f"{row['Pergunta']}: {row['Tentativas']:.2f}" for _, row in df_easy.iterrows()])
            top_hard_txt = "\n".join([f"{row['Pergunta']}: {row['Tentativas']:.2f}" for _, row in df_hard.iterrows()])

            # 2. Gráfico de evolução
            evol_fig, ax2 = plt.subplots()
            df_evol[["Diagnóstica", "Final"]].plot(ax=ax2)
            ax2.set_title("Evolução Diagnóstica vs Final")
            evol_path = os.path.join(tmp_dir, "evolucao.png")
            evol_fig.savefig(evol_path)
            plt.close(evol_fig)

            cronbach_txt = f"Alpha de Cronbach: {cronbach_alpha:.2f} (excelente consistência interna)."

            # 3. Criar PDF
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, "Relatório - Visão Learn Stats", ln=True)
            pdf.set_font("Arial", "", 12)
            pdf.multi_cell(0, 10, "Este relatório apresenta a caracterização da amostra, "
                                  "a evolução dos resultados da avaliação diagnóstica para a final "
                                  "e gráficos com os principais indicadores.")

            # Inserir gráficos
            # Página 1 – Caracterização da amostra
            pdf.add_page()
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, "Caracterização da Amostra", ln=True)
            pdf.image(distrito_path, w=100)
            pdf.ln(5)
            pdf.image(nacionalidade_path, w=100)
            pdf.ln(5)
            pdf.image(escolaridade_path, w=100)

            # Página 2 – Tempo e Evolução
            pdf.add_page()
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, "Tempo e Evolução", ln=True)
            pdf.set_font("Arial", "", 12)
            pdf.multi_cell(0, 10, tempo_medio_texto)
            pdf.ln(5)
            pdf.image(evol_path, w=180)

            # Página 3 – Top-3 Perguntas e Cronbach
            pdf.add_page()
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, "Top-3 Perguntas e Confiabilidade", ln=True)

            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "Mais Fáceis", ln=True)
            pdf.set_font("Arial", "", 12)
            pdf.multi_cell(0, 10, top_easy_txt)

            pdf.ln(5)
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "Mais Difíceis", ln=True)
            pdf.set_font("Arial", "", 12)
            pdf.multi_cell(0, 10, top_hard_txt)

            pdf.ln(5)
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 10, "Consistência Interna", ln=True)
            pdf.set_font("Arial", "", 12)
            pdf.multi_cell(0, 10, cronbach_txt)

            # Guardar PDF
            pdf_path = os.path.join(tmp_dir, "relatorio_visao_learn.pdf")
            pdf.output(pdf_path)

            # Mostrar botão de download
            with open(pdf_path, "rb") as f:
                st.download_button("⬇️ Baixar Relatório PDF", f, file_name="relatorio_learn.pdf")
