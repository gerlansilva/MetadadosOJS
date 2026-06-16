
# ============================================================
# MetaOJS Híbrido Simples v2.2 — Google Colab
#
# Fluxo:
#   1. OpenAlex Author ID -> filtra somente type:article
#   2. OpenAlex -> DOI, links e dados mínimos de controle
#   3. Crossref -> ano, título, autores, afiliações, revista,
#                  resumo, referências e citation
#   4. Página HTML -> enriquece autores, afiliações, resumo,
#                     palavras-chave e referências
#   5. Exporta um único CSV com nove campos
#
# Não lê PDF.
# Não gera Scopus/WoS.
# Não faz busca aproximada no Crossref.
# Campos ausentes permanecem vazios para auditoria manual.
# ============================================================

from __future__ import annotations

import csv
import difflib
import json
import re
import time
import warnings
from html import unescape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Alguns portais entregam XHTML/XML com cabeçalho de página web.
# A função create_soup escolhe o parser adequado; este filtro evita
# que o BeautifulSoup mostre o aviso durante tentativas de fallback.
warnings.filterwarnings(
    "ignore",
    category=XMLParsedAsHTMLWarning,
)
from tqdm.auto import tqdm


# ------------------------------------------------------------
# CONFIGURAÇÕES
# ------------------------------------------------------------

# Pode ser A123456789 ou https://openalex.org/A123456789
OPENALEX_AUTHOR_ID = "A5030860157"

EMAIL = "gerlanmatfis@gmail.com"

# Opcional. Preencha somente quando a OpenAlex solicitar chave.
OPENALEX_API_KEY = ""

OUTPUT_DIR = Path("/content/outputs_metaojs")
OUTPUT_FILENAME = "MetaOJS_metadados_hibridos.csv"

REQUEST_TIMEOUT = 40
REQUEST_RETRIES = 3
REQUEST_DELAY = 0.5

MIN_TITLE_SIMILARITY = 0.50

OPENALEX_API = "https://api.openalex.org"
OPENALEX_WORKS_API = f"{OPENALEX_API}/works"
CROSSREF_WORKS_API = "https://api.crossref.org/works"

AGGREGATOR_DOMAINS = {
    "doaj.org",
    "lareferencia.info",
    "researchgate.net",
    "academia.edu",
    "semanticscholar.org",
    "oasisbr.ibict.br",
}


# ------------------------------------------------------------
# FUNÇÕES GERAIS
# ------------------------------------------------------------

def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text or None


def normalize_key(value: Optional[str]) -> str:
    text = clean_text(value) or ""
    text = text.casefold()
    text = re.sub(r"[^\w\sÀ-ÿ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_author_id(value: str) -> str:
    text = clean_text(value) or ""
    text = text.rstrip("/").rsplit("/", 1)[-1].upper()

    if not re.fullmatch(r"A\d+", text):
        raise ValueError(
            "O OpenAlex Author ID deve ter o formato A123456789."
        )

    return text


def normalize_doi(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    text = clean_text(value)

    if not text:
        return None

    text = re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"^doi:\s*", "", text, flags=re.I)
    text = re.sub(r"[\]\),.;]+$", "", text)
    text = text.strip().lower()

    return text or None


def doi_url(value: Optional[str]) -> Optional[str]:
    doi = normalize_doi(value)
    return f"https://doi.org/{doi}" if doi else None


def unique_values(values: Iterable[Any]) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()

    for value in values:
        text = clean_text(value)

        if not text:
            continue

        key = normalize_key(text)

        if key and key not in seen:
            seen.add(key)
            output.append(text)

    return output


def join_unique(
    values: Iterable[Any],
    separator: str = "; ",
) -> Optional[str]:
    items = unique_values(values)
    return separator.join(items) if items else None


def first_valid(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass

        return value

    return None


def title_similarity(
    first: Optional[str],
    second: Optional[str],
) -> float:
    if not first or not second:
        return 0.0

    return difflib.SequenceMatcher(
        None,
        normalize_key(first),
        normalize_key(second),
    ).ratio()


def extract_year(value: Optional[str]) -> Optional[int]:
    if not value:
        return None

    match = re.search(r"\b(?:19|20)\d{2}\b", str(value))
    return int(match.group(0)) if match else None


def domain_from_url(value: Optional[str]) -> str:
    if not value:
        return ""

    try:
        return (
            urlparse(value)
            .netloc
            .lower()
            .removeprefix("www.")
        )
    except Exception:
        return ""


def is_aggregator(value: Optional[str]) -> bool:
    domain = domain_from_url(value)

    return any(
        domain == blocked
        or domain.endswith(f".{blocked}")
        for blocked in AGGREGATOR_DOMAINS
    )


def split_keywords(values: Iterable[Any]) -> List[str]:
    output: List[str] = []

    for value in values:
        text = clean_text(value)

        if not text:
            continue

        text = re.sub(
            r"^\s*(?:palavras[- ]chave|keywords?|palabras clave)"
            r"\s*[:\-–—]?\s*",
            "",
            text,
            flags=re.I,
        )

        parts = re.split(r"\s*(?:;|\||•|·)\s*", text)

        output.extend(
            part for part in parts
            if clean_text(part)
        )

    return unique_values(output)


# ------------------------------------------------------------
# REQUISIÇÕES
# ------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            f"MetaOJS-Hibrido/2.2 (mailto:{EMAIL})"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
)


def request_get(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    accept: Optional[str] = None,
) -> requests.Response:
    headers: Dict[str, str] = {}

    if accept:
        headers["Accept"] = accept

    last_error: Optional[Exception] = None

    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = SESSION.get(
                url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            if response.status_code in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(
                    f"HTTP {response.status_code}",
                    response=response,
                )

            time.sleep(REQUEST_DELAY)
            return response

        except Exception as error:
            last_error = error

            if attempt < REQUEST_RETRIES:
                time.sleep(min(attempt * 2, 6))

    if last_error:
        raise last_error

    raise RuntimeError("Falha desconhecida na requisição.")


# ------------------------------------------------------------
# OPENALEX: PERFIL E ARTIGOS
# ------------------------------------------------------------

def fetch_author_profile(author_id: str) -> Dict[str, Any]:
    params: Dict[str, Any] = {"mailto": EMAIL}

    if OPENALEX_API_KEY.strip():
        params["api_key"] = OPENALEX_API_KEY.strip()

    response = request_get(
        f"{OPENALEX_API}/authors/{author_id}",
        params=params,
        accept="application/json",
    )

    if response.status_code == 404:
        raise RuntimeError(
            f"O autor {author_id} não foi encontrado na OpenAlex."
        )

    if response.status_code in {401, 403}:
        raise RuntimeError(
            "A OpenAlex solicitou autenticação. "
            "Preencha OPENALEX_API_KEY."
        )

    response.raise_for_status()
    return response.json()


def parse_openalex_work(work: Dict[str, Any]) -> Dict[str, Any]:
    primary_location = work.get("primary_location") or {}
    best_oa_location = work.get("best_oa_location") or {}
    source = primary_location.get("source") or {}

    other_urls: List[str] = []

    for location in work.get("locations") or []:
        url = clean_text(location.get("landing_page_url"))

        if url and url not in other_urls:
            other_urls.append(url)

    return {
        "openalex_id": clean_text(work.get("id")),
        "year_openalex": work.get("publication_year"),
        "title_openalex": clean_text(work.get("title")),
        "journal_openalex": clean_text(source.get("display_name")),
        "doi": normalize_doi(work.get("doi")),
        "primary_url": clean_text(
            primary_location.get("landing_page_url")
        ),
        "best_oa_url": clean_text(
            best_oa_location.get("landing_page_url")
        ),
        "other_urls": other_urls,
    }


def fetch_articles(author_id: str) -> List[Dict[str, Any]]:
    """
    Recupera somente trabalhos classificados pela OpenAlex como article.
    """
    raw_works: List[Dict[str, Any]] = []
    cursor = "*"

    while cursor:
        params: Dict[str, Any] = {
            "filter": f"author.id:{author_id},type:article",
            "sort": "publication_date:desc",
            "per_page": 100,
            "cursor": cursor,
            "mailto": EMAIL,
        }

        if OPENALEX_API_KEY.strip():
            params["api_key"] = OPENALEX_API_KEY.strip()

        response = request_get(
            OPENALEX_WORKS_API,
            params=params,
            accept="application/json",
        )

        # Algumas versões da API podem rejeitar um formato de
        # ordenação. Nesse caso, repete a consulta sem sort.
        if response.status_code == 400:
            error_text = clean_text(response.text) or ""

            if (
                "publication_date" in error_text
                or "sort" in error_text.casefold()
            ):
                params_without_sort = dict(params)
                params_without_sort.pop("sort", None)

                response = request_get(
                    OPENALEX_WORKS_API,
                    params=params_without_sort,
                    accept="application/json",
                )

        if response.status_code == 400:
            raise RuntimeError(
                "Erro HTTP 400 da OpenAlex:\n"
                + (clean_text(response.text) or "")
            )

        if response.status_code in {401, 403}:
            raise RuntimeError(
                "A OpenAlex solicitou autenticação. "
                "Preencha OPENALEX_API_KEY."
            )

        response.raise_for_status()

        data = response.json()
        results = data.get("results") or []

        if not results:
            break

        raw_works.extend(results)

        next_cursor = (data.get("meta") or {}).get("next_cursor")

        if not next_cursor or next_cursor == cursor:
            break

        cursor = next_cursor

    parsed: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for work in raw_works:
        item = parse_openalex_work(work)

        key = (
            item.get("doi")
            or item.get("openalex_id")
            or (
                f"{normalize_key(item.get('title_openalex'))}|"
                f"{item.get('year_openalex')}"
            )
        )

        if not key or key in seen:
            continue

        seen.add(key)
        parsed.append(item)

    return parsed


# ------------------------------------------------------------
# CROSSREF: BASE ESTRUTURADA
# ------------------------------------------------------------

def crossref_year(message: Dict[str, Any]) -> Optional[int]:
    for field in (
        "published-print",
        "published-online",
        "published",
        "issued",
    ):
        date_parts = (
            (message.get(field) or {}).get("date-parts")
            or []
        )

        if date_parts and date_parts[0]:
            try:
                return int(date_parts[0][0])
            except (TypeError, ValueError):
                pass

    return None


def crossref_authors(message: Dict[str, Any]) -> List[str]:
    authors: List[str] = []

    for author in message.get("author") or []:
        given = clean_text(author.get("given")) or ""
        family = clean_text(author.get("family")) or ""
        name = clean_text(f"{given} {family}")

        if name:
            authors.append(name)

    return unique_values(authors)


def crossref_affiliations(message: Dict[str, Any]) -> List[str]:
    affiliations: List[str] = []

    for author in message.get("author") or []:
        for affiliation in author.get("affiliation") or []:
            name = clean_text(affiliation.get("name"))

            if name:
                affiliations.append(name)

    return unique_values(affiliations)


def format_crossref_reference(
    reference: Dict[str, Any],
) -> Optional[str]:
    unstructured = clean_text(reference.get("unstructured"))

    if unstructured:
        return unstructured

    parts = [
        clean_text(reference.get("author")),
        clean_text(reference.get("article-title")),
        clean_text(reference.get("journal-title")),
        clean_text(reference.get("year")),
        clean_text(reference.get("volume")),
        clean_text(reference.get("first-page")),
    ]

    text = ". ".join(part for part in parts if part)
    doi = normalize_doi(reference.get("DOI"))

    if doi:
        text = f"{text}. DOI: {doi}" if text else f"DOI: {doi}"

    return clean_text(text)


def fetch_crossref_record(
    doi: Optional[str],
) -> Dict[str, Any]:
    empty = {
        "year_crossref": None,
        "title_crossref": None,
        "authors_crossref": None,
        "affiliations_crossref": None,
        "journal_crossref": None,
        "abstract_crossref": None,
        "references_crossref": None,
        "citation_crossref": None,
    }

    doi = normalize_doi(doi)

    if not doi:
        return empty

    try:
        response = request_get(
            (
                f"{CROSSREF_WORKS_API}/"
                f"{requests.utils.quote(doi, safe='')}"
            ),
            params={"mailto": EMAIL},
            accept="application/json",
        )

        if response.status_code == 404:
            return empty

        response.raise_for_status()

        message = response.json().get("message") or {}

        returned_doi = normalize_doi(message.get("DOI"))

        if returned_doi and returned_doi != doi:
            return empty

        references = unique_values(
            formatted
            for formatted in (
                format_crossref_reference(reference)
                for reference in message.get("reference") or []
            )
            if formatted
        )

        citation = message.get("is-referenced-by-count")

        return {
            "year_crossref": crossref_year(message),
            "title_crossref": clean_text(
                (message.get("title") or [None])[0]
            ),
            "authors_crossref": join_unique(
                crossref_authors(message)
            ),
            "affiliations_crossref": join_unique(
                crossref_affiliations(message)
            ),
            "journal_crossref": clean_text(
                (message.get("container-title") or [None])[0]
            ),
            "abstract_crossref": clean_text(
                message.get("abstract")
            ),
            "references_crossref": (
                "; ".join(references)
                if references
                else None
            ),
            "citation_crossref": (
                int(citation)
                if citation is not None
                else None
            ),
        }

    except Exception:
        return empty


# ------------------------------------------------------------
# PÁGINA HTML: JSON-LD, METATAGS E CONTEÚDO VISÍVEL
# ------------------------------------------------------------


def create_soup(
    content: str,
    content_type: str = "",
) -> BeautifulSoup:
    """
    Seleciona automaticamente o parser.

    - text/html: parser HTML do lxml;
    - application/xhtml+xml, application/xml ou documento iniciado
      por declaração XML: parser XML do lxml;
    - cabeçalho ausente: inspeciona o início do conteúdo.
    """
    content_type_key = (content_type or "").casefold()
    beginning = (content or "").lstrip()[:500].casefold()

    looks_like_xml = (
        "xml" in content_type_key
        or beginning.startswith("<?xml")
        or beginning.startswith("<rss")
        or beginning.startswith("<feed")
    )

    # XHTML é XML válido e pode ser interpretado com features="xml".
    parser = "xml" if looks_like_xml else "lxml"

    return BeautifulSoup(
        content,
        features=parser,
    )



def meta_values(
    soup: BeautifulSoup,
    names: List[str],
) -> List[str]:
    names_lower = {name.casefold() for name in names}
    values: List[str] = []

    for meta in soup.find_all("meta"):
        meta_name = (
            meta.get("name")
            or meta.get("property")
            or ""
        ).strip().casefold()

        if meta_name in names_lower:
            content = clean_text(meta.get("content"))

            if content:
                values.append(content)

    return unique_values(values)


def meta_first(
    soup: BeautifulSoup,
    names: List[str],
) -> Optional[str]:
    values = meta_values(soup, names)
    return values[0] if values else None


def json_ld_objects(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    objects: List[Dict[str, Any]] = []

    for script in soup.find_all(
        "script",
        attrs={"type": "application/ld+json"},
    ):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        if isinstance(data, dict):
            graph = data.get("@graph")

            if isinstance(graph, list):
                objects.extend(
                    item
                    for item in graph
                    if isinstance(item, dict)
                )
            else:
                objects.append(data)

        elif isinstance(data, list):
            objects.extend(
                item
                for item in data
                if isinstance(item, dict)
            )

    return objects


def find_article_json_ld(
    soup: BeautifulSoup,
) -> Optional[Dict[str, Any]]:
    accepted_types = {
        "ScholarlyArticle",
        "Article",
        "Report",
    }

    for item in json_ld_objects(soup):
        item_type = item.get("@type")
        types = (
            item_type
            if isinstance(item_type, list)
            else [item_type]
        )

        if any(value in accepted_types for value in types):
            return item

    return None


def json_ld_authors(
    article: Optional[Dict[str, Any]],
) -> List[str]:
    if not article:
        return []

    authors = article.get("author") or []

    if isinstance(authors, (str, dict)):
        authors = [authors]

    values: List[str] = []

    for author in authors:
        if isinstance(author, str):
            values.append(author)

        elif isinstance(author, dict):
            name = clean_text(author.get("name"))

            if name:
                values.append(name)

    return unique_values(values)


def json_ld_affiliations(
    article: Optional[Dict[str, Any]],
) -> List[str]:
    if not article:
        return []

    authors = article.get("author") or []

    if isinstance(authors, dict):
        authors = [authors]

    values: List[str] = []

    for author in authors:
        if not isinstance(author, dict):
            continue

        affiliation = author.get("affiliation")

        if not affiliation:
            continue

        items = (
            affiliation
            if isinstance(affiliation, list)
            else [affiliation]
        )

        for item in items:
            if isinstance(item, str):
                values.append(item)

            elif isinstance(item, dict):
                name = clean_text(item.get("name"))

                if name:
                    values.append(name)

    return unique_values(values)


def json_ld_references(
    article: Optional[Dict[str, Any]],
) -> List[str]:
    if not article:
        return []

    citations = article.get("citation") or []

    if isinstance(citations, (str, dict)):
        citations = [citations]

    values: List[str] = []

    for citation in citations:
        if isinstance(citation, str):
            values.append(citation)

        elif isinstance(citation, dict):
            parts = [
                clean_text(citation.get("author")),
                clean_text(
                    citation.get("headline")
                    or citation.get("name")
                ),
                clean_text(citation.get("datePublished")),
            ]
            text = ". ".join(part for part in parts if part)

            if text:
                values.append(text)

    return unique_values(values)


def visible_texts(
    soup: BeautifulSoup,
    selectors: List[str],
    *,
    min_length: int = 1,
) -> List[str]:
    values: List[str] = []

    for selector in selectors:
        for element in soup.select(selector):
            text = clean_text(
                element.get_text(" ", strip=True)
            )

            if text and len(text) >= min_length:
                values.append(text)

    return unique_values(values)


def visible_references(soup: BeautifulSoup) -> List[str]:
    return visible_texts(
        soup,
        [
            ".item.references .value p",
            ".item.references .value li",
            ".references p",
            ".references li",
            "#references p",
            "#references li",
            ".article-references p",
            ".article-references li",
            ".ref-list li",
            ".obj_article_details .references p",
            ".obj_article_details .references li",
        ],
        min_length=20,
    )


def extract_page_metadata(
    html: str,
    final_url: str,
    expected_title: Optional[str],
    content_type: str = "",
) -> Dict[str, Any]:
    soup = create_soup(
        html,
        content_type,
    )
    article = find_article_json_ld(soup)

    # Título e ano são usados principalmente para controle/fallback.
    title = (
        clean_text(
            article.get("headline")
            or article.get("name")
        )
        if article
        else None
    )
    title = title or meta_first(soup, ["citation_title"])
    title = title or meta_first(
        soup,
        ["dc.title", "DC.Title", "og:title"],
    )

    publication_date = (
        clean_text(article.get("datePublished"))
        if article
        else None
    )
    publication_date = publication_date or meta_first(
        soup,
        [
            "citation_publication_date",
            "article:published_time",
            "citation_date",
            "dc.date",
            "DC.Date",
        ],
    )

    if (
        expected_title
        and title
        and title_similarity(expected_title, title)
        < MIN_TITLE_SIMILARITY
    ):
        raise RuntimeError(
            "O título da página não corresponde ao artigo."
        )

    # Autores: página HTML tem prioridade sobre o Crossref.
    authors = json_ld_authors(article)
    authors = authors or meta_values(
        soup,
        ["citation_author"],
    )
    authors = authors or visible_texts(
        soup,
        [
            ".obj_article_details .authors .name",
            ".authors .name",
            ".article-authors .author",
            "[itemprop='author'] [itemprop='name']",
        ],
        min_length=2,
    )
    authors = authors or meta_values(
        soup,
        ["dc.creator", "DC.Creator"],
    )

    # Afiliações: página HTML tem prioridade.
    affiliations = json_ld_affiliations(article)
    affiliations = affiliations or meta_values(
        soup,
        [
            "citation_author_institution",
            "citation_affiliation",
        ],
    )
    affiliations = affiliations or visible_texts(
        soup,
        [
            ".obj_article_details .authors .affiliation",
            ".authors .affiliation",
            ".article-authors .affiliation",
            "[itemprop='affiliation']",
        ],
        min_length=3,
    )

    # Revista da página, usada apenas se o Crossref não tiver valor.
    journal = None

    if article:
        is_part_of = article.get("isPartOf")

        if isinstance(is_part_of, dict):
            journal = clean_text(is_part_of.get("name"))

    journal = journal or meta_first(
        soup,
        ["citation_journal_title"],
    )
    journal = journal or meta_first(
        soup,
        ["dc.source", "DC.Source"],
    )

    # Resumo: página HTML tem prioridade.
    abstract = (
        clean_text(
            article.get("abstract")
            or article.get("description")
        )
        if article
        else None
    )
    abstract = abstract or meta_first(
        soup,
        ["citation_abstract"],
    )

    if not abstract:
        values = visible_texts(
            soup,
            [
                ".item.abstract .value",
                ".abstract .value",
                "section.abstract",
                ".article-abstract",
                ".obj_article_details .abstract",
                "#abstract",
            ],
            min_length=40,
        )
        abstract = values[0] if values else None

    abstract = abstract or meta_first(
        soup,
        ["dc.description", "DC.Description"],
    )

    # Palavras-chave: somente a página.
    keywords: List[str] = []

    if article:
        raw_keywords = article.get("keywords")

        if isinstance(raw_keywords, str):
            keywords = split_keywords([raw_keywords])

        elif isinstance(raw_keywords, list):
            keywords = split_keywords(raw_keywords)

    keywords = keywords or split_keywords(
        visible_texts(
            soup,
            [
                ".item.keywords .value a",
                ".item.keywords .value span",
                ".keywords a",
                ".keywords li",
                ".article-keywords a",
                ".article-keywords li",
                ".item.keywords .value",
                ".keywords .value",
            ],
            min_length=2,
        )
    )
    keywords = keywords or split_keywords(
        meta_values(soup, ["citation_keywords"])
    )
    keywords = keywords or split_keywords(
        meta_values(soup, ["dc.subject", "DC.Subject"])
    )

    # Referências: página HTML tem prioridade.
    references = json_ld_references(article)
    references = references or visible_references(soup)
    references = references or meta_values(
        soup,
        ["citation_reference"],
    )

    return {
        "year_page": extract_year(publication_date),
        "title_page": title,
        "authors_page": join_unique(authors),
        "affiliations_page": join_unique(affiliations),
        "journal_page": journal,
        "abstract_page": abstract,
        "keywords_page": join_unique(keywords),
        "references_page": (
            "; ".join(references)
            if references
            else None
        ),
        "url_final": final_url,
    }


# ------------------------------------------------------------
# LOCALIZAÇÃO DA PÁGINA HTML
# ------------------------------------------------------------

def candidate_urls(work: Dict[str, Any]) -> List[str]:
    values = [
        doi_url(work.get("doi")),
        work.get("primary_url"),
        work.get("best_oa_url"),
        *(work.get("other_urls") or []),
    ]

    output: List[str] = []

    for value in values:
        url = clean_text(value)

        if (
            not url
            or url in output
            or is_aggregator(url)
        ):
            continue

        output.append(url)

    return output


def scrape_article_page(
    work: Dict[str, Any],
) -> Dict[str, Any]:
    for url in candidate_urls(work):
        try:
            response = request_get(
                url,
                accept=(
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9"
                ),
            )

            if response.status_code >= 400:
                continue

            content_type = (
                response.headers.get("content-type")
                or ""
            ).lower()

            # A versão simples não processa PDF, mas aceita
            # HTML, XHTML e XML que contenham metadados do artigo.
            is_supported_document = (
                "html" in content_type
                or "xml" in content_type
                or response.text.lstrip().startswith(
                    ("<html", "<!DOCTYPE html", "<?xml")
                )
            )

            if not is_supported_document:
                continue

            if is_aggregator(response.url):
                continue

            return extract_page_metadata(
                response.text,
                response.url,
                work.get("title_openalex"),
                content_type,
            )

        except Exception:
            continue

    return {
        "year_page": None,
        "title_page": None,
        "authors_page": None,
        "affiliations_page": None,
        "journal_page": None,
        "abstract_page": None,
        "keywords_page": None,
        "references_page": None,
        "url_final": None,
    }


# ------------------------------------------------------------
# CONSOLIDAÇÃO
# ------------------------------------------------------------

OUTPUT_COLUMNS = [
    "ano_publicacao",
    "titulo",
    "autores",
    "instituicao",
    "revista",
    "resumo",
    "palavras_chave",
    "references_page",
    "citation",
]


def build_record(
    work: Dict[str, Any],
    crossref: Dict[str, Any],
    page: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Prioridade final por campo:

    ano:          Crossref -> página -> OpenAlex
    título:       Crossref -> página -> OpenAlex
    autores:      página -> Crossref
    instituição:  página -> Crossref
    revista:      Crossref -> página -> OpenAlex
    resumo:       página -> Crossref
    palavras:     somente página
    referências:  página -> Crossref
    citation:     somente Crossref
    """
    return {
        "ano_publicacao": first_valid(
            crossref.get("year_crossref"),
            page.get("year_page"),
            work.get("year_openalex"),
        ),
        "titulo": first_valid(
            crossref.get("title_crossref"),
            page.get("title_page"),
            work.get("title_openalex"),
        ),
        "autores": first_valid(
            page.get("authors_page"),
            crossref.get("authors_crossref"),
        ),
        "instituicao": first_valid(
            page.get("affiliations_page"),
            crossref.get("affiliations_crossref"),
        ),
        "revista": first_valid(
            crossref.get("journal_crossref"),
            page.get("journal_page"),
            work.get("journal_openalex"),
        ),
        "resumo": first_valid(
            page.get("abstract_page"),
            crossref.get("abstract_crossref"),
        ),
        "palavras_chave": page.get("keywords_page"),
        "references_page": first_valid(
            page.get("references_page"),
            crossref.get("references_crossref"),
        ),
        "citation": crossref.get("citation_crossref"),
        "_doi": work.get("doi"),
    }


def deduplicate(dataframe: pd.DataFrame) -> pd.DataFrame:
    frame = dataframe.copy()

    frame["_title_key"] = (
        frame["titulo"]
        .fillna("")
        .map(normalize_key)
    )

    frame["_dedup_key"] = frame.apply(
        lambda row: (
            f"doi:{row['_doi']}"
            if row.get("_doi")
            else (
                f"title:{row['_title_key']}|"
                f"{row['ano_publicacao']}"
            )
        ),
        axis=1,
    )

    completeness_columns = [
        "autores",
        "instituicao",
        "revista",
        "resumo",
        "palavras_chave",
        "references_page",
    ]

    frame["_completeness"] = (
        frame[completeness_columns]
        .notna()
        .sum(axis=1)
    )

    return (
        frame
        .sort_values(
            "_completeness",
            ascending=False,
        )
        .drop_duplicates(
            "_dedup_key",
            keep="first",
        )
        .sort_values(
            ["ano_publicacao", "titulo"],
            ascending=[False, True],
            na_position="last",
        )
        .reset_index(drop=True)
        [OUTPUT_COLUMNS]
    )


# ------------------------------------------------------------
# API PARA APLICAÇÃO WEB
# ------------------------------------------------------------

from dataclasses import dataclass
from threading import Lock
from typing import Callable, Tuple

_PIPELINE_LOCK = Lock()


@dataclass(frozen=True)
class PipelineConfig:
    """Parâmetros de execução usados pela interface web."""

    author_id: str
    email: str
    openalex_api_key: str = ""
    request_timeout: int = 40
    request_retries: int = 3
    request_delay: float = 0.5
    min_title_similarity: float = 0.50
    max_articles: Optional[int] = None


ProgressCallback = Callable[[int, int, str], None]


def dataframe_to_csv_bytes(dataframe: pd.DataFrame) -> bytes:
    """Gera CSV compatível com Excel, mantendo a codificação UTF-8 BOM."""
    return dataframe.to_csv(
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_ALL,
        lineterminator="\n",
    ).encode("utf-8-sig")


def _configure_runtime(config: PipelineConfig) -> None:
    """Aplica parâmetros de uma execução ao motor legado de coleta."""
    global EMAIL, OPENALEX_API_KEY, REQUEST_TIMEOUT
    global REQUEST_RETRIES, REQUEST_DELAY, MIN_TITLE_SIMILARITY

    EMAIL = clean_text(config.email) or ""
    OPENALEX_API_KEY = clean_text(config.openalex_api_key) or ""
    REQUEST_TIMEOUT = int(config.request_timeout)
    REQUEST_RETRIES = int(config.request_retries)
    REQUEST_DELAY = float(config.request_delay)
    MIN_TITLE_SIMILARITY = float(config.min_title_similarity)

    SESSION.headers.update(
        {
            "User-Agent": f"MetaOJS-Web/1.0 (mailto:{EMAIL})",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
    )


def _coverage_flags(record: Dict[str, Any]) -> Dict[str, Any]:
    fields = [
        "autores",
        "instituicao",
        "revista",
        "resumo",
        "palavras_chave",
        "references_page",
        "citation",
    ]
    present = sum(first_valid(record.get(field)) is not None for field in fields)
    return {
        "campos_preenchidos": present,
        "campos_avaliados": len(fields),
        "percentual_preenchimento": round((present / len(fields)) * 100, 1),
    }


def run_pipeline(
    config: PipelineConfig,
    progress_callback: Optional[ProgressCallback] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
    """
    Executa o fluxo OpenAlex → Crossref → página do periódico.

    Retorna:
        dataframe final com os nove campos de exportação;
        perfil do pesquisador na OpenAlex;
        dataframe de auditoria por registro processado.
    """
    with _PIPELINE_LOCK:
        _configure_runtime(config)
        author_id = normalize_author_id(config.author_id)
        profile = fetch_author_profile(author_id)
        works = fetch_articles(author_id)

        if config.max_articles and int(config.max_articles) > 0:
            works = works[: int(config.max_articles)]

        if not works:
            raise RuntimeError(
                "Nenhum artigo classificado como type:article foi localizado "
                "para esse OpenAlex Author ID."
            )

        records: List[Dict[str, Any]] = []
        audit_rows: List[Dict[str, Any]] = []
        total = len(works)

        for index, work in enumerate(works, start=1):
            title = clean_text(work.get("title_openalex")) or "Artigo sem título"
            if progress_callback:
                progress_callback(index - 1, total, f"Processando: {title}")

            crossref = fetch_crossref_record(work.get("doi"))
            page = scrape_article_page(work)
            record = build_record(work, crossref, page)
            records.append(record)

            flags = _coverage_flags(record)
            audit_rows.append(
                {
                    "openalex_id": work.get("openalex_id"),
                    "doi": work.get("doi"),
                    "titulo": record.get("titulo"),
                    "ano_publicacao": record.get("ano_publicacao"),
                    "pagina_localizada": bool(page.get("url_final")),
                    "url_final": page.get("url_final"),
                    "crossref_localizado": bool(
                        crossref.get("title_crossref")
                        or crossref.get("authors_crossref")
                        or crossref.get("journal_crossref")
                    ),
                    "tem_resumo": bool(record.get("resumo")),
                    "tem_palavras_chave": bool(record.get("palavras_chave")),
                    "tem_referencias": bool(record.get("references_page")),
                    **flags,
                }
            )

            if progress_callback:
                progress_callback(index, total, f"Concluído: {title}")

        dataframe = pd.DataFrame(records)
        if dataframe.empty:
            raise RuntimeError("A execução terminou sem registros válidos.")

        dataframe = deduplicate(dataframe)
        dataframe["citation"] = pd.to_numeric(
            dataframe["citation"], errors="coerce"
        ).astype("Int64")

        audit = pd.DataFrame(audit_rows)
        if not audit.empty:
            audit = audit.sort_values(
                ["percentual_preenchimento", "ano_publicacao"],
                ascending=[True, False],
                na_position="last",
            ).reset_index(drop=True)

        return dataframe, profile, audit
