"""Genera un análisis agregado y un tablero estático de casos COVID-19.

Ejemplo (desde la raíz del repositorio):
    python modulo-01/proyectos/demo-covid/analisis.py \
        --inicio 2021-01-01 --fin 2021-12-31

El CSV original no se copia a ``docs`` ni se muestran registros individuales.
"""

from __future__ import annotations

import argparse
import html
import sys
import unicodedata
from pathlib import Path

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    import pandas as pd
except ImportError as exc:
    raise SystemExit(
        "Falta una dependencia requerida. Activa el entorno RAGLAB o instala "
        "pandas y matplotlib (por ejemplo: pip install pandas matplotlib)."
    ) from exc


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CSV = (
    ROOT
    / "modulo-01"
    / "Proyectos"
    / "Casos_positivos_de_COVID-19_en_Colombia._20261109.csv"
)
OUTPUT_DIR = ROOT / "modulo-01" / "Proyectos" / "demo-covid"
CHART_DIR = OUTPUT_DIR / "graficos"
SOURCE_URL = (
    "https://www.datos.gov.co/Salud-y-Protecci-n-Social/"
    "Casos-positivos-de-COVID-19-en-Colombia-/gt2j-8ykr/about_data"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Ruta al CSV de origen.")
    parser.add_argument("--departamento", default="Boyacá", help="Departamento a analizar.")
    parser.add_argument("--inicio", help="Inicio del periodo inclusivo (AAAA-MM-DD).")
    parser.add_argument("--fin", help="Fin del periodo inclusivo (AAAA-MM-DD).")
    return parser.parse_args()


def find_column(columns: list[str], *candidates: str) -> str:
    normalized = {" ".join(str(col).strip().casefold().split()): col for col in columns}
    for candidate in candidates:
        key = " ".join(candidate.strip().casefold().split())
        if key in normalized:
            return normalized[key]
    raise ValueError(
        "No se encontró ninguna columna requerida: " + ", ".join(candidates)
    )


def parse_boundary(value: str | None, option: str) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        return pd.to_datetime(value, format="%Y-%m-%d", errors="raise")
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"--{option} debe tener formato AAAA-MM-DD.") from exc


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value).strip().casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def main() -> int:
    args = parse_args()
    if not args.csv.is_file():
        raise SystemExit(f"No se encontró el CSV: {args.csv}")

    try:
        # Los archivos del portal suelen ser UTF-8; cp1252 queda como alternativa.
        # El CSV localizado contiene algunos bytes no válidos para UTF-8 y cp1252;
        # reemplazarlos permite preservar las columnas ASCII usadas en el análisis.
        data = pd.read_csv(
            args.csv,
            encoding="utf-8-sig",
            encoding_errors="replace",
            low_memory=False,
        )
        date_col = find_column(data.columns.tolist(), "fecha reporte web")
        department_col = find_column(data.columns.tolist(), "Nombre departamento")
        case_id_col = find_column(data.columns.tolist(), "ID de caso")
        municipality_col = find_column(data.columns.tolist(), "Nombre municipio")
    except (UnicodeError, pd.errors.ParserError, ValueError) as exc:
        raise SystemExit(f"No fue posible leer o reconocer el esquema del CSV: {exc}") from exc

    # Normaliza textos y fechas; fechas/IDs inválidos se excluyen y se cuantifican.
    data[department_col] = data[department_col].astype("string").str.strip()
    data[case_id_col] = data[case_id_col].astype("string").str.strip()
    data[date_col] = pd.to_datetime(
        data[date_col], format="mixed", errors="coerce", dayfirst=True
    )
    valid = data[date_col].notna() & data[case_id_col].notna() & data[case_id_col].ne("")
    invalid_rows = int((~valid).sum())
    clean = data.loc[valid].copy()

    start = parse_boundary(args.inicio, "inicio")
    end = parse_boundary(args.fin, "fin")
    if start is not None and end is not None and start > end:
        raise SystemExit("--inicio no puede ser posterior a --fin.")

    requested_department = args.departamento.strip()
    dept_mask = clean[department_col].map(normalize_text) == normalize_text(requested_department)
    filtered = clean.loc[dept_mask].copy()
    if filtered.empty:
        available = sorted(clean[department_col].dropna().unique().tolist())
        matches = [name for name in available if normalize_text(name) == normalize_text(requested_department)]
        if not matches:
            raise SystemExit(
                f"No hay casos para {requested_department!r}; revise el nombre del departamento."
            )
    actual_department = str(filtered[department_col].iloc[0])

    period_mask = pd.Series(True, index=filtered.index)
    if start is not None:
        period_mask &= filtered[date_col] >= start
    if end is not None:
        period_mask &= filtered[date_col] <= end + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    filtered = filtered.loc[period_mask].copy()
    if filtered.empty:
        raise SystemExit("El filtro de departamento y periodo no contiene casos válidos.")

    # El ID identifica el caso en el esquema; usar nunique evita contar filas repetidas
    # del mismo caso. Las filas duplicadas exactas se informan como limitación/calidad.
    exact_duplicate_rows = int(data.duplicated().sum())
    monthly = filtered.assign(mes=filtered[date_col].dt.to_period("M")).groupby("mes")[case_id_col].nunique()
    monthly.index = monthly.index.to_timestamp()
    monthly = monthly.sort_index()
    total_cases = int(filtered[case_id_col].nunique())
    month_count = int(monthly.size)
    average_per_month = total_cases / month_count if month_count else 0.0
    first_month, first_count = monthly.index[0], int(monthly.iloc[0])
    last_month, last_count = monthly.index[-1], int(monthly.iloc[-1])
    if first_count:
        change = (last_count - first_count) / first_count * 100
        change_text = f"{change:+.1f}% entre el primer y el último mes con datos"
    else:
        change_text = "no calculable: el primer mes tiene cero casos"

    CHART_DIR.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax = plt.subplots(figsize=(11, 5.5))
    years = sorted(monthly.index.year.unique())
    year_palette = plt.get_cmap("Pastel1", max(len(years), 1))
    year_colors = {year: year_palette(i) for i, year in enumerate(years)}
    for year in years:
        months_in_year = monthly.index[monthly.index.year == year]
        left = months_in_year[0]
        right = months_in_year[-1] + pd.offsets.MonthBegin(1)
        ax.axvspan(
            left,
            right,
            color=year_colors[year],
            alpha=0.32,
            zorder=0,
        )
    ax.plot(monthly.index, monthly.values, color="#176b87", marker="o", linewidth=2)
    ax.set(title="Casos reportados por mes", xlabel="", ylabel="Casos (ID únicos)")
    ax.set_xticks(monthly.index)
    spanish_months = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    ax.set_xticklabels([spanish_months[date.month - 1] for date in monthly.index])
    ax.tick_params(
        axis="x", labelsize=7, pad=5, labelrotation=90,
        labeltop=False, labelbottom=True, top=False, bottom=True,
    )
    year_legend = [
        Patch(facecolor=year_colors[year], edgecolor="none", alpha=0.75, label=str(year))
        for year in years
    ]
    ax.legend(
        handles=year_legend,
        title="Año",
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
        borderaxespad=0,
        frameon=True,
    )
    fig.subplots_adjust(right=0.84, bottom=0.22)
    ax.margins(x=0.01)
    fig.tight_layout()
    fig.savefig(CHART_DIR / "casos-mensuales.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    municipality = filtered[municipality_col].astype("string").str.strip()
    municipality = municipality.replace("", pd.NA).dropna()
    municipality_counts = (
        filtered.loc[municipality.index].assign(_municipio=municipality)
        .groupby("_municipio")[case_id_col]
        .nunique()
        .sort_values(ascending=False)
        .head(15)
        .sort_values()
    )
    if municipality_counts.empty:
        raise SystemExit("No hay nombres de municipio válidos para generar el segundo gráfico.")
    fig, ax = plt.subplots(figsize=(10, max(5, len(municipality_counts) * 0.34)))
    ax.barh(municipality_counts.index.astype(str), municipality_counts.values, color="#4b9b78")
    ax.set(title="Casos por municipio (15 con mayor conteo)", xlabel="Casos (ID únicos)", ylabel="Municipio")
    fig.tight_layout()
    fig.savefig(CHART_DIR / "casos-por-municipio.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    period_label = f"{start.date() if start is not None else filtered[date_col].min().date()} — {end.date() if end is not None else filtered[date_col].max().date()}"
    limitations = [
        "El conteo usa IDs de caso únicos; interpreta cada ID como un caso reportado según el campo disponible, no como medida de infección real o incidencia poblacional.",
        "La fecha usada es «fecha reporte web» (publicación), no necesariamente fecha de diagnóstico, inicio de síntomas o contagio.",
        "El archivo es una extracción local: puede no coincidir con revisiones posteriores de la fuente. La ficha menciona actualizaciones y fe de erratas.",
        f"Se excluyeron {invalid_rows:,} filas con fecha inválida o ID vacío; se detectaron {exact_duplicate_rows:,} filas duplicadas exactas en el origen.",
        "Los municipios con valor faltante no aparecen en el gráfico municipal. Los gráficos describen conteos, no tasas ajustadas por población.",
    ]
    html_content = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Casos reportados de COVID-19 — {esc(actual_department)}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.55;color:#20303a;background:#f4f7f8;margin:0}}
main{{max-width:1080px;margin:2rem auto;padding:0 1rem}} header,.card{{background:white;border-radius:14px;padding:1.4rem 1.6rem;margin:1rem 0;box-shadow:0 2px 12px #18313b12}}
h1,h2{{color:#124e66}} .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}} .metric strong{{display:block;font-size:1.8rem;color:#176b87}}
figure{{background:white;border-radius:14px;padding:1rem;margin:1rem 0}} img{{display:block;width:100%;height:auto}} .muted{{color:#5a6970}} li{{margin:.45rem 0}}
</style></head><body><main>
<header><h1>Evolución de casos reportados de COVID-19</h1><p><strong>Departamento:</strong> {esc(actual_department)} &nbsp;·&nbsp; <strong>Periodo:</strong> {esc(period_label)}</p>
<p>La serie agrupa por mes la fecha de reporte web y cuenta identificadores únicos de caso.</p></header>
<section class="metrics"><article class="card metric"><span>Casos (ID únicos)</span><strong>{total_cases:,}</strong><span class="muted">en el filtro seleccionado</span></article>
<article class="card metric"><span>Promedio mensual</span><strong>{average_per_month:,.1f}</strong><span class="muted">casos por mes calendario con datos</span></article></section>
<section class="card"><h2>Hallazgo</h2><p>Entre {esc(first_month.strftime('%B %Y'))} ({first_count:,}) y {esc(last_month.strftime('%B %Y'))} ({last_count:,}), el conteo cambió {esc(change_text)}. Este resumen se calcula automáticamente a partir de la serie mensual; no implica causalidad.</p></section>
<figure><h2>Casos reportados por mes</h2><img src="graficos/casos-mensuales.png" alt="Gráfico de línea de casos mensuales"></figure>
<figure><h2>Distribución por municipio</h2><img src="graficos/casos-por-municipio.png" alt="Gráfico de barras con los 15 municipios con más casos"></figure>
<section class="card"><h2>Limitaciones</h2><ul>{''.join(f'<li>{esc(item)}</li>' for item in limitations)}</ul>
<p>Fuente: <a href="{SOURCE_URL}" target="_blank" rel="noopener noreferrer">Casos positivos de COVID-19 en Colombia — Datos Abiertos</a> (Instituto Nacional de Salud).</p>
<p class="muted">CSV analizado: {esc(args.csv.name)}. No se publican registros individuales.</p></section>
</main></body></html>"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "index.html").write_text(html_content, encoding="utf-8")
    print(f"Tablero generado: {OUTPUT_DIR / 'index.html'}")
    print(f"Departamento: {actual_department}; periodo: {period_label}")
    print(f"Casos (ID únicos): {total_cases:,}; promedio mensual: {average_per_month:,.1f}")
    print(f"Filas inválidas excluidas: {invalid_rows:,}; duplicados exactos: {exact_duplicate_rows:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())