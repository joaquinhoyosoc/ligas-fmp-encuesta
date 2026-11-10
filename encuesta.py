"""
=============================================================================
encuesta.py  (versión 1.0 · 2026-11-10 · T-164, entrega E1)
-----------------------------------------------------------------------------
Mini-app PÚBLICA de la encuesta postpartido (repo público «ligas-fmp-encuesta»).
Sin login: solo se entra con un enlace  …/?e=CODIGO  que genera el capitán.

Qué hace:
  1. «¿Quién eres?»: el jugador elige su nombre entre los de nuestra alineación.
  2. Su partido (pareja, compañero, rivales, resultado) y la CRÓNICA del partido.
  3. Para cada uno de sus dos rivales (y, si quiere, otros del cruce): lado,
     características (catálogo de la app) y un comentario.
  4. Enviar: queda PENDIENTE en el buzón. Nada pasa a la app sin la validación
     del capitán. Mientras esté pendiente, puede corregirla con el mismo enlace.

Solo conoce la base Turso del buzón ([buzon] url, token en los Secrets de ESTA app).
No lleva la BD de partidos ni el código de la app principal: todo lo que muestra
viene de la «foto» del cruce que guardó buzon.py.

Dependencias: streamlit 1.64.0 (st.pills, st.segmented_control), libsql 0.1.11.
Prueba en local:  $env:BUZON_URL / $env:BUZON_TOKEN  o  .streamlit\\secrets.toml
                  streamlit run encuesta.py   ->  http://localhost:8501/?e=CODIGO
=============================================================================
"""
import html
import json
import os
import re
from datetime import datetime, timezone

import streamlit as st

VERSION = "1.0"
MAX_CRONICA = 2000
MAX_COMENTARIO = 500
MAX_EDICIONES = 20
RE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
LADO_CORTO = {"D": "Derecha", "R": "Revés", "AD": "Ambos (D)", "AR": "Ambos (R)"}

st.set_page_config(page_title="Encuesta postpartido · Ligas FMP", page_icon="🎾",
                   layout="centered", initial_sidebar_state="collapsed")

st.markdown("""<style>
header[data-testid="stHeader"], #MainMenu, footer {display:none !important}
.block-container {padding-top:1.2rem; padding-bottom:4rem; max-width:640px}
html, body, [class*="css"] {font-family:-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif}
.enc-cab {background:#FFFFFF; border:1px solid #E7ECF2; border-radius:18px; padding:18px 18px 14px;
          box-shadow:0 1px 2px rgba(19,32,47,.04), 0 6px 18px rgba(19,32,47,.05); margin-bottom:14px}
.enc-eti {font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:#56677A; margin-bottom:8px}
.enc-marc {display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:10px}
.enc-eq {font-weight:600; font-size:16px; color:#13202F; line-height:1.25}
.enc-eq.der {text-align:right}
.enc-num {font-size:28px; font-weight:700; color:#13202F; font-variant-numeric:tabular-nums; white-space:nowrap}
.enc-sub {font-size:13px; color:#56677A; margin-top:10px}
.enc-part {background:#F2F5F9; border-radius:14px; padding:12px 14px; margin:6px 0 4px}
.enc-fila {display:flex; justify-content:space-between; align-items:center; gap:10px; font-size:15px; color:#13202F}
.enc-fila + .enc-fila {margin-top:6px}
.enc-ten {color:#56677A; font-size:13px}
.enc-sets {font-variant-numeric:tabular-nums; font-weight:600; letter-spacing:.02em}
.enc-badge {display:inline-block; min-width:22px; text-align:center; border-radius:7px; padding:2px 7px;
            font-size:12px; font-weight:700}
.enc-V {background:#DDF3E4; color:#1B6B38} .enc-P {background:#FBE2E2; color:#A92828}
.enc-ok {background:#FFFFFF; border:1px solid #B3E0C2; border-radius:18px; padding:22px; text-align:center}
.enc-ok h3 {margin:6px 0 4px; color:#1B6B38}
.enc-nombre {font-weight:650; font-size:17px; color:#13202F; margin-bottom:2px}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Buzón (Turso)
# ---------------------------------------------------------------------------
def _cfg():
    url = os.environ.get("BUZON_URL", "").strip()
    token = os.environ.get("BUZON_TOKEN", "").strip()
    if not (url and token):
        try:
            url, token = str(st.secrets["buzon"]["url"]).strip(), str(st.secrets["buzon"]["token"]).strip()
        except Exception:
            return None
    return (url, token) if url and token else None


def _conectar():
    cfg = _cfg()
    if not cfg:
        raise RuntimeError("Sin configuración del buzón")
    import libsql
    return libsql.connect(database=cfg[0], auth_token=cfg[1])


def _ahora(segundos=False):
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S" if segundos else "%Y-%m-%d %H:%M")


def _encuesta(token):
    """(id_encuesta, estado, caduca, foto dict) o None. Siempre fresco (se usa antes de guardar)."""
    c = _conectar()
    try:
        f = c.execute("SELECT id_encuesta, estado, caduca, foto FROM Encuestas WHERE token = ?", (token,)).fetchone()
    finally:
        c.close()
    return (int(f[0]), f[1], f[2], json.loads(f[3])) if f else None


@st.cache_data(ttl=60, show_spinner=False)
def _encuesta_cache(token):
    return _encuesta(token)


def _respuesta(id_enc, id_autor):
    c = _conectar()
    try:
        f = c.execute("""SELECT cronica, datos, estado, enviada, ediciones FROM Respuestas
                         WHERE id_encuesta = ? AND id_autor = ?""", (id_enc, id_autor)).fetchone()
    finally:
        c.close()
    if not f:
        return None
    return {"cronica": f[0] or "", "datos": json.loads(f[1] or "{}"), "estado": f[2], "enviada": f[3], "ediciones": f[4]}


def _guardar(id_enc, id_autor, autor_nombre, pareja, cronica, datos):
    """Inserta o corrige (solo si sigue pendiente y no supera MAX_EDICIONES). Devuelve True si quedó guardado."""
    marca = _ahora(segundos=True)
    texto = json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
    c = _conectar()
    try:
        c.execute("""INSERT INTO Respuestas (id_encuesta, id_autor, autor_nombre, pareja_num, cronica, datos, enviada)
                     VALUES (?, ?, ?, ?, ?, ?, ?)
                     ON CONFLICT(id_encuesta, id_autor) DO UPDATE SET
                         autor_nombre = excluded.autor_nombre, pareja_num = excluded.pareja_num,
                         cronica = excluded.cronica, datos = excluded.datos, enviada = excluded.enviada,
                         ediciones = Respuestas.ediciones + 1
                     WHERE Respuestas.estado = 'pendiente' AND Respuestas.ediciones < ?""",
                  (id_enc, id_autor, autor_nombre, pareja, cronica, texto, marca, MAX_EDICIONES))
        c.commit()
        f = c.execute("SELECT enviada, datos FROM Respuestas WHERE id_encuesta = ? AND id_autor = ?",
                      (id_enc, id_autor)).fetchone()
    finally:
        c.close()
    return bool(f) and f[0] == marca and f[1] == texto


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _limpio(txt, maximo):
    """Sin caracteres de control (salvo saltos de línea), sin más de una línea en blanco seguida, recortado."""
    s = "".join(ch for ch in str(txt or "") if ch == "\n" or ch >= " ")
    s = re.sub(r"\n{3,}", "\n\n", s.replace("\r", "")).strip()
    return s[:maximo]


def _e(x):
    return html.escape(str(x if x is not None else ""))


def _pantalla(icono, titulo, texto):
    st.markdown(f"<div class='enc-cab' style='text-align:center'><div style='font-size:34px'>{icono}</div>"
                f"<div class='enc-nombre'>{_e(titulo)}</div><div class='enc-ten'>{_e(texto)}</div></div>",
                unsafe_allow_html=True)
    st.stop()


def _sets(p):
    if p.get("tipo") == "WO":
        return "W.O."
    txt = " · ".join(f"{a}-{b}" for a, b in p.get("sets") or [])
    return (txt + (" (lesión)" if p.get("tipo") == "LESION" else "")) or "—"


def _badge(g):
    return "" if g is None else f"<span class='enc-badge enc-{'V' if g else 'P'}'>{'V' if g else 'P'}</span>"


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
token = str(st.query_params.get("e", "")).strip()
if not RE_TOKEN.match(token):
    _pantalla("🔗", "Enlace no válido", "Pide a tu capitán el enlace de la encuesta del cruce.")
if not _cfg():
    _pantalla("⚙️", "Encuesta no disponible", "Falta la configuración del buzón. Avisa a tu capitán.")
try:
    enc = _encuesta_cache(token)
except Exception:
    enc = "error"
if enc == "error":
    _pantalla("📡", "Sin conexión con el buzón", "Inténtalo de nuevo en unos minutos.")
if not enc:
    _pantalla("🔗", "Enlace no válido", "Pide a tu capitán el enlace de la encuesta del cruce.")
id_enc, estado, caduca, foto = enc
if estado != "abierta" or caduca < _ahora():
    _pantalla("🔒", "Encuesta cerrada", "Esta encuesta ya no admite respuestas.")

J = foto["jugadores"]
nombre = lambda j: J.get(str(j), {}).get("corto") or f"Jugador {j}"
marc = foto.get("marcador")
num = f"{marc[0]} – {marc[1]}" if marc else "vs"
lugar = "En casa" if foto.get("en_casa") else "Fuera"
st.markdown(f"""<div class='enc-cab'>
  <div class='enc-eti'>Encuesta postpartido</div>
  <div class='enc-marc'><div class='enc-eq'>{_e(foto['nuestro']['nombre'])}</div>
    <div class='enc-num'>{_e(num)}</div><div class='enc-eq der'>{_e(foto['rival']['nombre'])}</div></div>
  <div class='enc-sub'>J{_e(foto.get('jornada'))} · {_e(foto.get('division'))} · {_e(foto.get('fecha') or '')} · {lugar}</div>
</div>""", unsafe_allow_html=True)

# --- 1. ¿Quién eres? ---------------------------------------------------------
autor = st.pills("¿Quién eres?", options=foto["nuestros"], format_func=nombre, key="autor")
if autor is None:
    st.caption("Elige tu nombre para empezar. Tus respuestas las revisa el capitán antes de pasar a la app.")
    st.stop()
autor = int(autor)

if st.session_state.get("_pref") != autor:            # cambio de jugador: limpiar y cargar lo que ya envió
    for k in [k for k in st.session_state if k.startswith(("lado_", "r_", "com_")) or k in ("cronica", "extra", "hecho")]:
        del st.session_state[k]
    try:
        prev = _respuesta(id_enc, autor)
    except Exception:
        prev = "error"
    if prev == "error":
        _pantalla("📡", "Sin conexión con el buzón", "Inténtalo de nuevo en unos minutos.")
    st.session_state["_prev"] = prev
    if prev:
        st.session_state["cronica"] = prev["cronica"]
        ya = prev["datos"].get("jugadores") or {}
        suyos_partido = next((p["suyos"] for p in foto["partidos"] if autor in p["nuestros"]), [])
        st.session_state["extra"] = [int(j) for j in ya if int(j) not in suyos_partido and int(j) in foto["suyos"]]
        for j, d in ya.items():
            st.session_state[f"lado_{j}"] = d.get("lado") or None
            elegidos = set(d.get("rasgos") or [])
            for g in dict.fromkeys(r[1] for r in foto["rasgos"]):
                st.session_state[f"r_{j}_{g}"] = [r[0] for r in foto["rasgos"] if r[1] == g and r[0] in elegidos]
            st.session_state[f"com_{j}"] = d.get("comentario") or ""
    st.session_state["_pref"] = autor
prev = st.session_state.get("_prev")
if prev and prev["estado"] != "pendiente":
    _pantalla("✅", "Respuesta ya revisada", "El capitán ya revisó tu respuesta a este cruce. ¡Gracias!")

if st.session_state.get("hecho") == autor:
    st.markdown("<div class='enc-ok'><div style='font-size:34px'>✅</div><h3>¡Enviado!</h3>"
                "<div class='enc-ten'>El capitán lo revisará antes de pasarlo a la app. Puedes corregirlo "
                "con este mismo enlace mientras no lo haya revisado.</div></div>", unsafe_allow_html=True)
    if st.button("Corregir mi respuesta", use_container_width=True):
        del st.session_state["hecho"]
        st.rerun()
    st.stop()
if prev:
    st.info(f"Ya enviaste una respuesta ({prev['enviada'][:16]} UTC). Puedes corregirla y volver a enviar.")

# --- 2. Tu partido y crónica -------------------------------------------------
mio = next((p for p in foto["partidos"] if autor in p["nuestros"]), None)
if mio:
    comp = [j for j in mio["nuestros"] if j != autor]
    st.markdown(f"""<div class='enc-part'>
      <div class='enc-fila'><span class='enc-ten'>Pareja {mio['pareja']}</span><span>{_badge(mio.get('g'))}</span></div>
      <div class='enc-fila'><span>Tú{(' y ' + _e(nombre(comp[0]))) if comp else ''}</span>
        <span class='enc-sets'>{_e(_sets(mio))}</span></div>
      <div class='enc-fila'><span class='enc-ten'>contra</span>
        <span>{' y '.join(_e(nombre(j)) for j in mio['suyos']) or '—'}</span></div>
    </div>""", unsafe_allow_html=True)
    st.text_area("Crónica de tu partido", key="cronica", max_chars=MAX_CRONICA, height=150,
                 placeholder="Cómo fue: claves, momentos decisivos, qué funcionó y qué no, estado de la pista…")
else:
    st.caption("No apareces en el acta de este cruce: puedes opinar de los rivales, pero no escribir crónica.")

# --- 3. Rivales --------------------------------------------------------------
st.markdown("#### Tus rivales")
propios = list(mio["suyos"]) if mio else []
otros = [j for j in foto["suyos"] if j not in propios]
if otros:
    st.multiselect("Opinar también de otro rival del cruce", options=otros, format_func=nombre, key="extra")
rivales = propios + [int(j) for j in st.session_state.get("extra") or []]
grupos = []
for cod, grupo, _n, _d in foto["rasgos"]:
    if grupo not in grupos:
        grupos.append(grupo)
nom_rasgo = {r[0]: r[2] for r in foto["rasgos"]}
with st.expander("¿Qué significa cada característica?"):
    for g in grupos:
        st.markdown(f"**{g}**")
        st.markdown("\n".join(f"- **{_e(n)}**: {_e(d)}" for c_, g_, n, d in foto["rasgos"] if g_ == g))

for j in rivales:
    base = J.get(str(j), {})
    with st.container(border=True):
        st.markdown(f"<div class='enc-nombre'>{_e(nombre(j))}</div>", unsafe_allow_html=True)
        st.session_state.setdefault(f"lado_{j}", base.get("lado") or None)
        st.segmented_control("Lado", options=list(LADO_CORTO), format_func=LADO_CORTO.get, key=f"lado_{j}")
        marcados = set(base.get("rasgos") or [])
        for g in grupos:
            cods = [r[0] for r in foto["rasgos"] if r[1] == g]
            st.session_state.setdefault(f"r_{j}_{g}", [c_ for c_ in cods if c_ in marcados])
            st.pills(g, options=cods, format_func=nom_rasgo.get, selection_mode="multi", key=f"r_{j}_{g}")
        st.session_state.setdefault(f"com_{j}", "")
        st.text_area("Comentario sobre él", key=f"com_{j}", max_chars=MAX_COMENTARIO, height=90,
                     placeholder="Lo que conviene saber para la próxima vez que nos toque.")
if not rivales:
    st.caption("Elige arriba algún rival si quieres opinar.")

# --- 4. Enviar ---------------------------------------------------------------
if st.button("Enviar", type="primary", use_container_width=True):
    validos = {r[0] for r in foto["rasgos"]}
    jugadores = {}
    for j in rivales:
        if j not in foto["suyos"]:
            continue
        base = J.get(str(j), {})
        lado = st.session_state.get(f"lado_{j}") or ""
        lado = lado if lado in LADO_CORTO else ""
        rasgos = sorted({c_ for g in grupos for c_ in (st.session_state.get(f"r_{j}_{g}") or []) if c_ in validos})
        com = _limpio(st.session_state.get(f"com_{j}"), MAX_COMENTARIO)
        b_lado, b_ras = base.get("lado") or "", sorted(base.get("rasgos") or [])
        if lado != b_lado or rasgos != b_ras or com:
            jugadores[str(j)] = {"lado": lado, "base_lado": b_lado, "rasgos": rasgos, "base_rasgos": b_ras,
                                 "comentario": com}
    cronica = _limpio(st.session_state.get("cronica"), MAX_CRONICA) if mio else ""
    if not cronica and not jugadores:
        st.warning("No hay nada que enviar: escribe la crónica o cambia algo de algún rival.")
        st.stop()
    try:
        fresca = _encuesta(token)
    except Exception:
        fresca = "error"
    if fresca == "error":
        st.error("No se pudo guardar (sin conexión con el buzón). Inténtalo de nuevo.")
        st.stop()
    if not fresca or fresca[1] != "abierta" or fresca[2] < _ahora():
        _pantalla("🔒", "Encuesta cerrada", "Esta encuesta ya no admite respuestas.")
    try:
        ok = _guardar(id_enc, autor, J.get(str(autor), {}).get("nombre", ""), mio["pareja"] if mio else None,
                      cronica, {"v": 1, "jugadores": jugadores})
    except Exception:
        st.error("No se pudo guardar (sin conexión con el buzón). Inténtalo de nuevo.")
        st.stop()
    if not ok:
        st.error("No se pudo guardar: tu respuesta ya fue revisada o has superado el número de correcciones.")
        st.stop()
    st.session_state["_prev"] = _respuesta(id_enc, autor)
    st.session_state["hecho"] = autor
    st.rerun()

st.caption(f"Encuesta Ligas FMP · v{VERSION}")
