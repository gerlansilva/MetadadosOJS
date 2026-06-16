from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from PIL import Image

from metaojs_core import PipelineConfig, dataframe_to_csv_bytes, run_pipeline

APP_DIR = Path(__file__).resolve().parent
ASSETS_DIR = APP_DIR / "assets"
LOGO_PATH = ASSETS_DIR / "metaojs_logo.svg"
MARK_PATH = ASSETS_DIR / "metaojs_mark.svg"
FAVICON_PATH = ASSETS_DIR / "metaojs_favicon.png"

st.set_page_config(
    page_title="MetaOJS | Metadados científicos integrados",
    page_icon=Image.open(FAVICON_PATH),
    layout="wide",
    initial_sidebar_state="expanded",
)


def svg_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --navy: #0B1F33;
          --teal: #0E8F93;
          --teal-light: #17B6AE;
          --gold: #F5B942;
          --paper: #F7FAFC;
          --ink: #102A43;
          --muted: #64788A;
        }

        .stApp { background: linear-gradient(180deg, #F8FBFC 0%, #F2F6F8 100%); }
        [data-testid="stSidebar"] { background: #0B1F33; }
        [data-testid="stSidebar"] * { color: #F6FBFD; }
        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] textarea,
        [data-testid="stSidebar"] [data-baseweb="select"] * { color: #102A43 !important; }
        [data-testid="stSidebar"] .stCaption { color: #B8CBD6 !important; }
        [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.14); }
        [data-testid="stSidebar"] .stButton > button {
          background: linear-gradient(135deg, #17B6AE, #0E8F93);
          color: white;
          border: 0;
          border-radius: 12px;
          font-weight: 750;
          min-height: 48px;
          box-shadow: 0 8px 22px rgba(23,182,174,.22);
        }
        [data-testid="stSidebar"] .stButton > button:hover {
          background: linear-gradient(135deg, #20C5BC, #109BA0);
          color: white;
        }

        .block-container { max-width: 1440px; padding-top: 1.4rem; padding-bottom: 3rem; }
        .brand-wrap {
          background: white;
          border: 1px solid #DDE8EE;
          border-radius: 22px;
          padding: 1.25rem 1.5rem;
          box-shadow: 0 12px 38px rgba(11,31,51,.06);
          margin-bottom: 1rem;
        }
        .brand-wrap svg { width: min(760px, 100%); height: auto; display: block; }
        .hero {
          background: linear-gradient(135deg, #0B1F33 0%, #123A4A 62%, #0E7C86 100%);
          color: white;
          border-radius: 24px;
          padding: 2rem 2.2rem;
          margin: .7rem 0 1.15rem;
          box-shadow: 0 16px 40px rgba(11,31,51,.18);
          overflow: hidden;
          position: relative;
        }
        .hero:after {
          content: "";
          position: absolute;
          width: 250px;
          height: 250px;
          border: 34px solid rgba(255,255,255,.05);
          border-radius: 50%;
          right: -80px;
          top: -95px;
        }
        .hero h1 { color: white; margin: 0 0 .45rem; font-size: clamp(2rem, 3vw, 3.25rem); }
        .hero p { color: #D6E8EE; margin: 0; max-width: 840px; font-size: 1.04rem; line-height: 1.6; }
        .pill-row { display:flex; flex-wrap:wrap; gap:.55rem; margin-top:1.15rem; }
        .pill {
          border:1px solid rgba(255,255,255,.22);
          background:rgba(255,255,255,.08);
          border-radius:999px;
          padding:.42rem .72rem;
          font-size:.82rem;
          color:#F4FBFC;
        }
        .metric-note { color:#64788A; font-size:.82rem; margin-top:-.35rem; }
        [data-testid="stMetric"] {
          background: white;
          border: 1px solid #DDE8EE;
          padding: 1rem 1.05rem;
          border-radius: 16px;
          box-shadow: 0 7px 22px rgba(11,31,51,.04);
        }
        [data-testid="stMetricValue"] { color: #0B1F33; }
        [data-testid="stMetricLabel"] { color: #587083; }
        .flow-grid {
          display:grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap:.8rem;
          margin:1rem 0;
        }
        .flow-card {
          background:white;
          border:1px solid #DDE8EE;
          border-radius:16px;
          padding:1rem;
          min-height:140px;
          box-shadow:0 7px 22px rgba(11,31,51,.04);
        }
        .flow-number {
          display:inline-grid;
          place-items:center;
          width:32px;
          height:32px;
          border-radius:10px;
          background:#DDF6F3;
          color:#0E7C86;
          font-weight:800;
          margin-bottom:.7rem;
        }
        .flow-card h4 { margin:.1rem 0 .35rem; color:#0B1F33; }
        .flow-card p { margin:0; color:#64788A; font-size:.9rem; line-height:1.45; }
        .section-kicker { color:#0E8F93; font-size:.78rem; font-weight:800; letter-spacing:.11em; text-transform:uppercase; }
        .empty-state {
          background:white;
          border:1px dashed #B8CBD6;
          border-radius:20px;
          padding:1.6rem;
          color:#52697A;
        }
        .source-tag {
          display:inline-block;
          padding:.25rem .5rem;
          border-radius:7px;
          background:#EAF6F5;
          color:#0E7C86;
          font-weight:700;
          font-size:.8rem;
          margin-right:.3rem;
        }
        @media (max-width: 900px) {
          .flow-grid { grid-template-columns: 1fr 1fr; }
        }
        @media (max-width: 600px) {
          .flow-grid { grid-template-columns: 1fr; }
          .hero { padding:1.4rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def safe_name(value: Any, fallback: str = "pesquisador") -> str:
    text = re.sub(r"[^\w\-]+", "_", str(value or "").strip(), flags=re.UNICODE)
    return text.strip("_") or fallback


def completeness_summary(df: pd.DataFrame) -> pd.DataFrame:
    labels = {
        "ano_publicacao": "Ano",
        "titulo": "Título",
        "autores": "Autores",
        "instituicao": "Instituição",
        "revista": "Revista",
        "resumo": "Resumo",
        "palavras_chave": "Palavras-chave",
        "references_page": "Referências",
        "citation": "Citações",
    }
    total = max(len(df), 1)
    rows = []
    for column, label in labels.items():
        filled = int(df[column].notna().sum())
        if df[column].dtype == object:
            filled = int(df[column].fillna("").astype(str).str.strip().ne("").sum())
        rows.append(
            {
                "Campo": label,
                "Registros preenchidos": filled,
                "Cobertura (%)": round((filled / total) * 100, 1),
            }
        )
    return pd.DataFrame(rows)


def filtered_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    c1, c2, c3 = st.columns([1.5, 1, 1.25])
    with c1:
        query = st.text_input(
            "Buscar em título, autor ou revista",
            placeholder="Digite um termo...",
            key="table_query",
        )
    years = sorted(
        [int(year) for year in df["ano_publicacao"].dropna().unique()],
        reverse=True,
    )
    with c2:
        selected_years = st.multiselect("Ano", years, placeholder="Todos")
    journals = sorted(df["revista"].dropna().astype(str).unique().tolist())
    with c3:
        selected_journals = st.multiselect(
            "Revista", journals, placeholder="Todas"
        )

    output = df.copy()
    if query.strip():
        needle = query.strip().casefold()
        mask = pd.Series(False, index=output.index)
        for column in ["titulo", "autores", "revista"]:
            mask = mask | output[column].fillna("").astype(str).str.casefold().str.contains(
                re.escape(needle), regex=True
            )
        output = output[mask]
    if selected_years:
        output = output[output["ano_publicacao"].isin(selected_years)]
    if selected_journals:
        output = output[output["revista"].isin(selected_journals)]
    return output


inject_css()

with st.sidebar:
    st.markdown(f'<div style="width:88px;margin:0 auto 8px">{svg_text(MARK_PATH)}</div>', unsafe_allow_html=True)
    st.markdown("### Nova coleta")
    st.caption("Informe um pesquisador identificado na OpenAlex.")

    author_id = st.text_input(
        "OpenAlex Author ID",
        value="A5030860157",
        placeholder="A123456789",
        help="Aceita também a URL completa, como https://openalex.org/A123456789.",
    )
    email = st.text_input(
        "E-mail para identificação das APIs",
        value="gerlanmatfis@gmail.com",
        help="Usado no User-Agent e no parâmetro mailto das APIs.",
    )
    api_key = st.text_input(
        "Chave da OpenAlex (opcional)",
        type="password",
        help="Preencha somente quando sua conta ou volume de uso exigir autenticação.",
    )

    with st.expander("Configurações avançadas"):
        max_articles = st.number_input(
            "Limite de artigos para teste",
            min_value=0,
            max_value=5000,
            value=0,
            step=10,
            help="Use 0 para processar todos os artigos.",
        )
        timeout = st.slider("Tempo limite por requisição (s)", 10, 120, 40, 5)
        retries = st.slider("Tentativas por requisição", 1, 6, 3)
        delay = st.slider("Intervalo entre requisições (s)", 0.0, 2.0, 0.5, 0.1)
        similarity = st.slider(
            "Similaridade mínima de título",
            0.30,
            0.95,
            0.50,
            0.05,
        )

    run = st.button("Executar coleta", use_container_width=True, type="primary")
    st.divider()
    st.caption(
        "A ferramenta consulta apenas artigos, não lê PDFs e mantém campos ausentes vazios para auditoria."
    )

st.markdown(
    f'<div class="brand-wrap">{svg_text(LOGO_PATH)}</div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
    <section class="hero">
      <div class="section-kicker" style="color:#82E3DB">COLETA E ENRIQUECIMENTO DE METADADOS</div>
      <h1>Da identificação do autor ao CSV auditável.</h1>
      <p>
        O MetaOJS combina a estrutura da OpenAlex e do Crossref com os metadados
        disponíveis nas páginas dos periódicos. O resultado preserva lacunas,
        indica a cobertura por campo e pode ser exportado para análise posterior.
      </p>
      <div class="pill-row">
        <span class="pill">OpenAlex Author ID</span>
        <span class="pill">Crossref</span>
        <span class="pill">HTML / XHTML / XML</span>
        <span class="pill">CSV UTF-8</span>
        <span class="pill">Auditoria de cobertura</span>
      </div>
    </section>
    """,
    unsafe_allow_html=True,
)

if run:
    if not author_id.strip():
        st.error("Informe um OpenAlex Author ID.")
    elif not email.strip() or "@" not in email:
        st.error("Informe um e-mail válido para identificação nas APIs.")
    else:
        progress = st.progress(0, text="Iniciando a coleta...")
        status = st.empty()

        def update_progress(done: int, total: int, message: str) -> None:
            ratio = 0 if total == 0 else min(done / total, 1.0)
            progress.progress(ratio, text=f"{done}/{total} artigos")
            status.caption(message)

        config = PipelineConfig(
            author_id=author_id,
            email=email,
            openalex_api_key=api_key,
            request_timeout=int(timeout),
            request_retries=int(retries),
            request_delay=float(delay),
            min_title_similarity=float(similarity),
            max_articles=int(max_articles) or None,
        )

        try:
            df, profile, audit = run_pipeline(config, update_progress)
            progress.progress(1.0, text="Coleta concluída")
            status.empty()
            st.session_state["result_df"] = df
            st.session_state["profile"] = profile
            st.session_state["audit_df"] = audit
            st.session_state["last_author_id"] = author_id
            st.success(
                f"Coleta concluída: {len(df)} registros finais para "
                f"{profile.get('display_name') or author_id}."
            )
        except Exception as exc:
            progress.empty()
            status.empty()
            st.error(f"Não foi possível concluir a coleta: {exc}")

if "result_df" not in st.session_state:
    st.markdown("### Como a aplicação trabalha")
    st.markdown(
        """
        <div class="flow-grid">
          <div class="flow-card"><span class="flow-number">1</span><h4>Identificação</h4><p>Valida o OpenAlex Author ID e recupera somente registros classificados como artigos.</p></div>
          <div class="flow-card"><span class="flow-number">2</span><h4>Base estruturada</h4><p>Obtém DOI, ano, título, periódico e links de controle na OpenAlex.</p></div>
          <div class="flow-card"><span class="flow-number">3</span><h4>Enriquecimento</h4><p>Consulta o Crossref e as páginas HTML, XHTML ou XML dos periódicos.</p></div>
          <div class="flow-card"><span class="flow-number">4</span><h4>Consolidação</h4><p>Aplica prioridades por campo, remove duplicatas e exporta um CSV auditável.</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="empty-state">
          <strong>Comece pela barra lateral.</strong><br>
          Use o limite de artigos para validar rapidamente um pesquisador antes de executar a coleta completa.
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    df: pd.DataFrame = st.session_state["result_df"]
    profile = st.session_state.get("profile", {})
    audit: pd.DataFrame = st.session_state.get("audit_df", pd.DataFrame())

    researcher = profile.get("display_name") or st.session_state.get("last_author_id")
    works_count = profile.get("works_count")
    cited_by_count = profile.get("cited_by_count")

    st.markdown(f"### Resultados de {html.escape(str(researcher))}")
    cols = st.columns(5)
    cols[0].metric("Registros finais", f"{len(df):,}".replace(",", "."))
    cols[1].metric("Com resumo", int(df["resumo"].notna().sum()))
    cols[2].metric("Com palavras-chave", int(df["palavras_chave"].notna().sum()))
    cols[3].metric("Com referências", int(df["references_page"].notna().sum()))
    cols[4].metric("Citações no corpus", int(df["citation"].fillna(0).sum()))
    if works_count is not None or cited_by_count is not None:
        st.caption(
            f"Perfil OpenAlex: {works_count or 0} trabalhos no total e "
            f"{cited_by_count or 0} citações associadas ao perfil."
        )

    tab_data, tab_coverage, tab_time, tab_audit, tab_method = st.tabs(
        ["Dados", "Cobertura", "Produção", "Auditoria", "Método"]
    )

    with tab_data:
        shown = filtered_dataframe(df)
        st.caption(f"Exibindo {len(shown)} de {len(df)} registros.")
        st.dataframe(
            shown,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ano_publicacao": st.column_config.NumberColumn("Ano", format="%d"),
                "references_page": st.column_config.TextColumn("Referências", width="large"),
                "citation": st.column_config.NumberColumn("Citações", format="%d"),
            },
        )
        filename = f"MetaOJS_{safe_name(researcher)}.csv"
        st.download_button(
            "Baixar CSV completo",
            data=dataframe_to_csv_bytes(df),
            file_name=filename,
            mime="text/csv",
            use_container_width=True,
        )

    with tab_coverage:
        coverage = completeness_summary(df)
        c1, c2 = st.columns([1.15, 1])
        with c1:
            st.markdown("#### Cobertura por campo")
            chart_data = coverage.set_index("Campo")[["Cobertura (%)"]]
            st.bar_chart(chart_data, height=430)
        with c2:
            st.markdown("#### Quadro de preenchimento")
            st.dataframe(coverage, use_container_width=True, hide_index=True)
            average = coverage["Cobertura (%)"].mean()
            st.metric("Cobertura média", f"{average:.1f}%")
            st.caption(
                "Campos vazios não são imputados: permanecem visíveis para revisão manual."
            )

    with tab_time:
        c1, c2 = st.columns([1.25, 1])
        with c1:
            st.markdown("#### Artigos por ano")
            by_year = (
                df.dropna(subset=["ano_publicacao"])
                .assign(ano_publicacao=lambda x: x["ano_publicacao"].astype(int))
                .groupby("ano_publicacao")
                .size()
                .rename("Artigos")
                .sort_index()
            )
            if by_year.empty:
                st.info("Não há anos suficientes para construir o gráfico.")
            else:
                st.line_chart(by_year, height=390)
        with c2:
            st.markdown("#### Periódicos mais frequentes")
            top_journals = (
                df["revista"].fillna("Não informado").value_counts().head(12).rename("Artigos")
            )
            st.bar_chart(top_journals, height=390)

    with tab_audit:
        st.markdown("#### Registros que exigem revisão")
        st.caption(
            "A tabela começa pelos registros com menor percentual de preenchimento."
        )
        if audit.empty:
            st.info("A auditoria não está disponível para esta execução.")
        else:
            st.dataframe(
                audit,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "url_final": st.column_config.LinkColumn("Página localizada"),
                    "percentual_preenchimento": st.column_config.ProgressColumn(
                        "Preenchimento", min_value=0, max_value=100, format="%.1f%%"
                    ),
                },
            )
            st.download_button(
                "Baixar auditoria em CSV",
                data=dataframe_to_csv_bytes(audit),
                file_name=f"MetaOJS_auditoria_{safe_name(researcher)}.csv",
                mime="text/csv",
                use_container_width=True,
            )

    with tab_method:
        st.markdown("#### Prioridade de consolidação")
        st.markdown(
            """
            <p>
              <span class="source-tag">Ano e título</span> Crossref → página → OpenAlex<br><br>
              <span class="source-tag">Autores e instituição</span> página → Crossref<br><br>
              <span class="source-tag">Revista</span> Crossref → página → OpenAlex<br><br>
              <span class="source-tag">Resumo</span> página → Crossref<br><br>
              <span class="source-tag">Palavras-chave</span> página do periódico<br><br>
              <span class="source-tag">Referências</span> página → Crossref<br><br>
              <span class="source-tag">Citações</span> Crossref
            </p>
            """,
            unsafe_allow_html=True,
        )
        st.info(
            "A aplicação não lê PDFs, não realiza busca aproximada no Crossref e não produz arquivos no formato Scopus ou Web of Science."
        )
