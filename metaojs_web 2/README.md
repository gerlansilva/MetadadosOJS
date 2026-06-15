# MetaOJS

![MetaOJS](assets/metaojs_logo.svg)

**MetaOJS** é uma aplicação web em Python para coletar e enriquecer metadados de artigos científicos a partir de um **OpenAlex Author ID**. O fluxo combina:

1. **OpenAlex** — identificação do pesquisador, seleção de registros `type:article`, DOI, título, ano e links;
2. **Crossref** — título, autores, afiliações, periódico, resumo, referências e contagem de citações;
3. **página do periódico/OJS** — autores, afiliações, resumo, palavras-chave e referências disponíveis em HTML, XHTML ou XML;
4. **consolidação** — prioridade por fonte, remoção de duplicatas, auditoria de preenchimento e exportação CSV.

## Identidade visual

O símbolo representa três fontes de metadados conectadas a um registro científico central. A ramificação converge para a saída consolidada, sintetizando o princípio da ferramenta: **integrar, enriquecer e auditar**.

- azul-marinho: rigor científico e confiabilidade;
- verde-petróleo: integração e processamento de dados;
- amarelo: resultado consolidado e descoberta.

## Recursos da aplicação

- entrada por OpenAlex Author ID ou URL completa;
- chave da OpenAlex opcional;
- limite de artigos para testes rápidos;
- barra de progresso por artigo;
- tabela pesquisável e filtrável;
- indicadores de cobertura por campo;
- gráficos de produção anual e periódicos mais frequentes;
- tabela de auditoria com links das páginas localizadas;
- download do corpus e da auditoria em CSV UTF-8.

## Instalação

Requer Python 3.10 ou superior.

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows

pip install -r requirements.txt
streamlit run app.py
```

A aplicação será aberta no navegador, normalmente em `http://localhost:8501`.

## Estrutura

```text
metaojs_web/
├── app.py
├── metaojs_core.py
├── requirements.txt
├── README.md
├── assets/
│   ├── metaojs_logo.svg
│   └── metaojs_mark.svg
└── .streamlit/
    └── config.toml
```

## Campos exportados

| Campo | Regra principal |
|---|---|
| `ano_publicacao` | Crossref → página → OpenAlex |
| `titulo` | Crossref → página → OpenAlex |
| `autores` | página → Crossref |
| `instituicao` | página → Crossref |
| `revista` | Crossref → página → OpenAlex |
| `resumo` | página → Crossref |
| `palavras_chave` | página |
| `references_page` | página → Crossref |
| `citation` | Crossref |

## Limites metodológicos

- processa somente registros classificados pela OpenAlex como `type:article`;
- não lê arquivos PDF;
- não realiza busca aproximada no Crossref;
- não gera arquivos de exportação Scopus ou Web of Science;
- campos não encontrados permanecem vazios, favorecendo a auditoria manual;
- a disponibilidade dos dados depende das APIs e da marcação HTML/XML dos periódicos.

## Uso responsável

Informe um e-mail válido na interface. Ele é enviado no `User-Agent` e no parâmetro `mailto`, conforme boas práticas de identificação nas APIs. Ajuste o intervalo entre requisições quando processar perfis extensos.

## Licença sugerida

Para publicação acadêmica e disponibilização no GitHub, uma opção adequada é a licença MIT para o código. A marca e os elementos visuais podem ser distribuídos sob termos separados, caso necessário.
