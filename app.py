#!/usr/bin/env python3
# Streamlit app dérivé du code partagé par l'utilisateur, modifié uniquement pour
# ne PAS présélectionner automatiquement le mois et la semaine (placeholder "-- Choisir --")
# et pour afficher les libellés de semaine sous la forme neutre "DD/MM/YYYY → DD/MM/YYYY".
# Le reste du code source principal est conservé (logique, exports, résolution de conflits).
#
# Usage: streamlit run app.py
#
# Dépendances: streamlit, pandas, openpyxl, plotly (facultatif pour graphiques existants)
# Placez Logo_ofppt.png dans le répertoire si vous voulez qu'il apparaisse dans les exports Excel et l'interface.

import streamlit as st
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.drawing.image import Image
from openpyxl.utils import get_column_letter
from io import BytesIO
from datetime import datetime, timedelta, date
import copy
import os
import re
import base64

# Configuration Streamlit
st.set_page_config(
    page_title="Gestionnaire d'Emploi du Temps - OFPPT (Dates exactes)",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- INITIALIZE SESSION STATE FIRST ---
if 'raw_data' not in st.session_state:
    st.session_state['raw_data'] = None
if 'resolved_data' not in st.session_state:
    st.session_state['resolved_data'] = None
if 'conflits_log' not in st.session_state:
    st.session_state['conflits_log'] = pd.DataFrame()
if 'niveau_global' not in st.session_state:
    st.session_state['niveau_global'] = "1ère Année"
if 'force_25_to_26' not in st.session_state:
    st.session_state['force_25_to_26'] = True

# --- STYLE CSS (interface) ---
st.markdown("""
<style>
    .main-header { background: linear-gradient(135deg,#1e5631 0%,#2d8659 50%,#1e5631 100%); padding: 2.5rem; border-radius: 15px; margin-bottom: 2rem; color: white; text-align:center; }
    .ofppt-title { font-size: 3rem; font-weight: bold; margin-bottom: 0.5rem; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
    .ofppt-subtitle { font-size: 1.3rem; margin-bottom: 1rem; opacity: 0.95; }
    .developer-info { font-size: 0.95rem; margin-top: 1rem; padding-top: 1rem; border-top: 1px solid rgba(255,255,255,0.3); font-style: italic; }
    .section-header { font-size: 1.8rem; color: #1e5631; font-weight: bold; margin: 2rem 0 1rem 0; padding-bottom: 0.5rem; border-bottom: 3px solid #2d8659; }
    .metric-card { background: white; padding: 1.2rem; border-radius: 10px; border-left: 4px solid #2d8659; text-align:center; box-shadow:0 2px 8px rgba(0,0,0,0.06); }
</style>
""", unsafe_allow_html=True)

# --- CONSTANTS ---
LOGO_FILE_NAME = "Logo_ofppt.png"
LOGO_URL = "https://www.ofppt.ma/sites/default/files/logo.png"
LOGO_WIDTH_PIXELS = 70
LOGO_HEIGHT_PIXELS = 70

FALLBACK_SEMAINES = ['S1', 'S2', 'S3', 'S4']

JOURS = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi']
CRENEAUX_JOUR = ['AM1', 'AM2', 'PM1', 'PM2']

HORAIRES = {
    'AM1': '08H30-11H00',
    'AM2': '11H00-13H30',
    'PM1': '13H30-16H00',
    'PM2': '16H00-18H30'
}

SLOT_DURATIONS = {'AM1': 2.5, 'AM2': 2.5, 'PM1': 2.5, 'PM2': 2.5}

MONTH_NAMES = {
    'Novembre': 'Novembre','Decembre': 'Décembre','Janvier':'Janvier','Février':'Février',
    'Mars':'Mars','Avril':'Avril','Mai':'Mai','Juin':'Juin','Juillet':'Juillet',
    'Aout':'Août','Août':'Août','Septembre':'Septembre','Octobre':'Octobre'
}
MONTH_ORDER = list(MONTH_NAMES.values())
IGNORED_SHEETS = ['Groupes', 'Feuil1', 'Sheet1']

MONTH_TO_NUMBER = {
    'Janvier':1,'Février':2,'Mars':3,'Avril':4,'Mai':5,'Juin':6,'Juillet':7,'Août':8,'Aout':8,
    'Septembre':9,'Octobre':10,'Novembre':11,'Décembre':12
}

HOLIDAYS = [
    {'date': datetime(2025,11,6).date(), 'label': 'La Marche Verte'},
    {'date': datetime(2025,11,18).date(), 'label': "Fête de l'Indépendance"},
    {'date': datetime(2026,1,1).date(), 'label': 'Nouvel an'},
    {'date': datetime(2026,1,11).date(), 'label': "Manifeste de l'independence"},
    {'date': datetime(2026,1,14).date(), 'label': 'Nouvel an Amazigh'},
    {'date': datetime(2026,5,1).date(), 'label': 'Fête du travail'},
]

HOLIDAY_FILL = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
HOLIDAY_FONT = Font(bold=True, color="000000")

# --- HELPER FUNCTION FOR LOGO ---
def get_logo_src():
    """Retourne le src du logo (base64 si fichier local existe, sinon URL)"""
    if os.path.exists(LOGO_FILE_NAME):
        try:
            with open(LOGO_FILE_NAME, "rb") as f:
                logo_base64 = base64.b64encode(f.read()).decode()
            return f"data:image/png;base64,{logo_base64}"
        except Exception:
            return LOGO_URL
    return LOGO_URL

# --- DATE PARSING HELPERS ---
ARROW_RE = re.compile(r'\s*(?:→|->|–|-)\s*')
DATE_FORMATS = [
    "%d/%m/%Y","%d/%m/%y","%d %b %Y","%d %B %Y","%d %b %y","%d %B %y","%Y-%m-%d","%d.%m.%Y",
]

def try_parse_date(s):
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    s = re.sub(r'[^\w\s\-/\.]', ' ', s).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    parts = re.split(r'[ \-\\/\.]+', s)
    if len(parts) >= 3:
        try:
            d = int(parts[0]); m = int(parts[1]); y = int(parts[2])
            if y < 100: y += 2000
            return datetime(y, m, d).date()
        except Exception:
            pass
    return None

def parse_date_range_cell(cell):
    if not cell or not isinstance(cell, str):
        return (None, None)
    if '→' in cell or '->' in cell or '–' in cell or '-' in cell:
        parts = ARROW_RE.split(cell)
        if len(parts) >= 2:
            d1 = try_parse_date(parts[0])
            d2 = try_parse_date(parts[1])
            return (d1, d2)
    return (None, None)

def day_date(week_start, offset_days):
    if week_start is None:
        return None
    d = week_start + timedelta(days=offset_days)
    if isinstance(d, datetime):
        return d.date()
    return d

def sanitize_sheet_title(s, max_len=31):
    if s is None:
        return "Sheet1"
    s = str(s)
    s = re.sub(r'[:\\\/\?\*\[\]]', '_', s)
    s = s.strip() or "sheet"
    if len(s) > max_len:
        s = s[:max_len]
    return s

def extract_month_name_from_sheet(sheet_name):
    normalized = sheet_name.replace('Planning_', '').strip()
    for key, value in MONTH_NAMES.items():
        if key.lower() in normalized.lower():
            return value
    return None

def find_header_row(df):
    for idx, row in df.iterrows():
        vals = [str(x).strip() for x in row.values if pd.notna(x)]
        lowvals = [v.lower() for v in vals]
        if any(v in ('formateur','form') for v in lowvals) and any(c in vals for c in ['AM1','AM2','PM1','PM2']):
            return idx
    return None

@st.cache_data(show_spinner=False)
def parse_schedule_sheet(df, sheet_name):
    month_name = extract_month_name_from_sheet(sheet_name)
    month_label = month_name if month_name else sheet_name

    header_idx = find_header_row(df)
    if header_idx is None:
        return None

    header_row = df.iloc[header_idx]
    search_top = max(0, header_idx - 10)
    found_map = {}
    for ridx in range(search_top, header_idx):
        row = df.iloc[ridx].astype(str).tolist()
        for cidx, cell in enumerate(row):
            txt = str(cell).strip()
            if not txt:
                continue
            a,b = parse_date_range_cell(txt)
            if a and b and cidx not in found_map:
                found_map[cidx] = (txt, a, b)
    ordered = [found_map[k] for k in sorted(found_map.keys())] if found_map else []
    if ordered:
        semaines = [it[0] for it in ordered]
        week_ranges = {it[0]: {'start': it[1], 'end': it[2]} for it in ordered}
    else:
        semaines = FALLBACK_SEMAINES.copy()
        week_ranges = {}

    col_form = -1
    for i, val in enumerate(header_row):
        if pd.notna(val) and str(val).strip().lower() in ('formateur','form'):
            col_form = i
            break
    if col_form == -1:
        return None
    col_salle = col_form + 1
    col_start = col_salle + 1

    df_data = df.iloc[header_idx+1:].reset_index(drop=True)

    schedule = {}
    groupes = set()
    salles = set()
    col_map = {}
    cur = col_start
    for s in semaines:
        for j in JOURS:
            for c in CRENEAUX_JOUR:
                col_map[f"{s}-{j}-{c}"] = cur
                cur += 1

    for _, row in df_data.iterrows():
        form = str(row.iloc[col_form]).strip() if col_form < len(row) else ''
        salle = str(row.iloc[col_salle]).strip() if col_salle < len(row) else ''
        if not form or form.lower() in ('nan','none',''):
            continue
        schedule.setdefault(form, {'salle': salle, 'slots': {}})
        if salle and salle.lower() not in ('nan','none',''):
            salles.add(salle)
        for key, ci in col_map.items():
            if ci < len(row):
                val = row.iloc[ci]
                if pd.notna(val) and str(val).strip():
                    grp = str(val).strip()
                    if grp and not grp.isdigit() and grp.lower() not in ('nan','none'):
                        schedule[form]['slots'][key] = (grp, salle)
                        groupes.add(grp)

    return {
        'month': month_label,
        'schedule': schedule,
        'formateurs': sorted(schedule.keys()),
        'groupes': sorted(list(groupes)),
        'salles': sorted(list(salles)),
        'semaines': semaines,
        'week_ranges': week_ranges,
        'header_idx': int(header_idx)
    }

@st.cache_data(show_spinner=False)
def process_uploaded_excel(uploaded_file):
    all_data = {}
    try:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            if sheet_name in IGNORED_SHEETS:
                continue
            df = pd.read_excel(xls, sheet_name=sheet_name, header=None, dtype=str)
            df = df.fillna('')
            parsed = parse_schedule_sheet(df, sheet_name)
            if parsed:
                all_data[parsed['month']] = parsed
        sorted_data = {m: all_data[m] for m in MONTH_ORDER if m in all_data}
        for k, v in all_data.items():
            if k not in sorted_data:
                sorted_data[k] = v
        return sorted_data
    except Exception as e:
        st.error(f"Erreur import: {e}")
        return {}

@st.cache_data(show_spinner=False)
def resolve_salle_conflits(all_data):
    resolved = copy.deepcopy(all_data)
    log = []
    all_salles = set()
    for month in resolved.values():
        all_salles.update(month['salles'])
    for month_name, month_data in resolved.items():
        schedule = month_data['schedule']
        semaines = month_data.get('semaines', FALLBACK_SEMAINES)
        HALF_DAY = [('AM1','AM2'), ('PM1','PM2')]
        for semaine in semaines:
            for jour in JOURS:
                for c1, c2 in HALF_DAY:
                    key1 = f"{semaine}-{jour}-{c1}"
                    key2 = f"{semaine}-{jour}-{c2}"
                    occ1 = set()
                    occ2 = set()
                    for f, fd in schedule.items():
                        s1 = fd['slots'].get(key1)
                        s2 = fd['slots'].get(key2)
                        if s1 and s1[1]:
                            occ1.add(s1[1])
                        if s2 and s2[1]:
                            occ2.add(s2[1])
                    libres = all_salles - occ1 - occ2
                    requests = []
                    for form, fd in schedule.items():
                        si1 = fd['slots'].get(key1, (None,None))
                        si2 = fd['slots'].get(key2, (None,None))
                        g1, g2 = si1[0], si2[0]
                        if g1 or g2:
                            requests.append({'formateur': form, 'g1': g1, 'g2': g2, 'pref': fd['salle']})
                    occupied = set()
                    for req in requests:
                        f = req['formateur']
                        pref = req['pref']
                        assigned = None
                        if pref and pref not in occupied:
                            assigned = pref
                        else:
                            candidates = libres - occupied
                            candidates = [s for s in candidates if not any(x in s.lower() for x in ['info','ent'])]
                            if candidates:
                                candidates.sort()
                                assigned = candidates[0]
                                for creneau, grp in [(c1, req['g1']), (c2, req['g2'])]:
                                    if grp:
                                        log.append({'Mois': month_name, 'Semaine': semaine, 'Jour_Creneau': f"{jour}-{creneau}", 'Heure': HORAIRES[creneau], 'Formateur': f, 'Groupe': grp, 'Salle_Initiale': pref, 'Salle_Attribuee': assigned})
                            else:
                                assigned = f"{pref or 'Aucune'} (CONFLIT NON RESOLU)"
                                for creneau, grp in [(c1, req['g1']), (c2, req['g2'])]:
                                    if grp:
                                        log.append({'Mois': month_name, 'Semaine': semaine, 'Jour_Creneau': f"{jour}-{creneau}", 'Heure': HORAIRES[creneau], 'Formateur': f, 'Groupe': grp, 'Salle_Initiale': pref, 'Salle_Attribuee': 'AUCUNE DISPO'})
                        if "CONFLIT NON RESOLU" not in assigned:
                            occupied.add(assigned)
                        if req['g1']:
                            resolved[month_name]['schedule'][f]['slots'][key1] = (req['g1'], assigned)
                        if req['g2']:
                            resolved[month_name]['schedule'][f]['slots'][key2] = (req['g2'], assigned)
    return resolved, pd.DataFrame(log)

def get_week_start_from_label(mois_label, semaine_label, week_ranges):
    if week_ranges and semaine_label in week_ranges:
        return week_ranges[semaine_label]['start']
    mnum = MONTH_TO_NUMBER.get(mois_label)
    if mnum:
        year = 2026 if mnum <= 7 else 2025
        first_day = datetime(year, mnum, 1)
        days_until_monday = (7 - first_day.weekday()) % 7
        first_monday = first_day + timedelta(days=days_until_monday) if first_day.weekday() != 0 else first_day
        m = re.match(r'S(\d+)', semaine_label, re.I)
        if m:
            idx = int(m.group(1)) - 1
            return (first_monday + timedelta(weeks=idx)).date()
    return None

# Minimal update: display only the date range "DD/MM/YYYY → DD/MM/YYYY" for weeks
def format_week_display_label(sem_label, week_ranges):
    """
    Affiche uniquement la plage de dates pour la semaine, par exemple:
    "01/12/2025 → 06/12/2025".
    Conserve les placeholders inchangés (ex: "-- Choisir --").
    """
    if not sem_label:
        return sem_label
    if isinstance(sem_label, str) and sem_label.strip().startswith("--"):
        return sem_label
    if week_ranges and sem_label in week_ranges:
        s = week_ranges[sem_label]['start']
        e = week_ranges[sem_label]['end']
        try:
            return f"{s.strftime('%d/%m/%Y')} → {e.strftime('%d/%m/%Y')}"
        except Exception:
            try:
                return f"{str(s)} → {str(e)}"
            except Exception:
                return sem_label
    return sem_label

def is_holiday(day_date):
    if day_date is None:
        return None
    if isinstance(day_date, datetime):
        d = day_date.date()
    else:
        d = day_date
    for h in HOLIDAYS:
        if h['date'] == d:
            return h['label']
    return None

def build_schedule_table_for_formateur(formateur_data, semaine_label, mois_label, week_ranges):
    week_start = get_week_start_from_label(mois_label, semaine_label, week_ranges)
    rows = []
    for i, jour in enumerate(JOURS):
        d = day_date(week_start, i)
        holiday = is_holiday(d) if d else None
        row = {'JOUR': jour}
        for c in CRENEAUX_JOUR:
            key = f"{semaine_label}-{jour}-{c}"
            if holiday:
                row[c] = ""
            else:
                slot = formateur_data['slots'].get(key, ('',''))
                grp, salle = slot
                row[c] = f"{grp}\n{salle}" if grp and salle else ""
        rows.append(row)
    return pd.DataFrame(rows)

def build_schedule_table_for_groupe(schedule_data, groupe, semaine_label, mois_label, week_ranges):
    week_start = get_week_start_from_label(mois_label, semaine_label, week_ranges)
    rows = []
    for i, jour in enumerate(JOURS):
        d = day_date(week_start, i)
        holiday = is_holiday(d) if d else None
        row = {'JOUR': jour}
        for c in CRENEAUX_JOUR:
            key = f"{semaine_label}-{jour}-{c}"
            if holiday:
                row[c] = ""
            else:
                info = ""
                for form, fd in schedule_data.items():
                    s = fd['slots'].get(key)
                    if s and s[0] == groupe:
                        info = f"{form}\n{s[1].replace(' (CONFLIT NON RESOLU)',' (Conflit)')}"
                        break
                row[c] = info
        rows.append(row)
    return pd.DataFrame(rows)

def compute_hours_for_formateur(formateur_data, semaine_label, mois_label, week_ranges):
    heures = 0.0
    week_start = get_week_start_from_label(mois_label, semaine_label, week_ranges)
    for jour_idx, jour in enumerate(JOURS):
        day_dt = day_date(week_start, jour_idx)
        if day_dt and is_holiday(day_dt):
            continue
        for c in CRENEAUX_JOUR:
            slot_key = f"{semaine_label}-{jour}-{c}"
            if slot_key in formateur_data.get('slots', {}):
                heures += SLOT_DURATIONS.get(c, 0)
    return heures

def compute_hours_for_groupe(schedule_data, groupe, semaine_label, mois_label, week_ranges):
    heures = 0.0
    week_start = get_week_start_from_label(mois_label, semaine_label, week_ranges)
    for jour_idx, jour in enumerate(JOURS):
        day_dt = day_date(week_start, jour_idx)
        if day_dt and is_holiday(day_dt):
            continue
        for c in CRENEAUX_JOUR:
            slot_key = f"{semaine_label}-{jour}-{c}"
            for fd in schedule_data.values():
                slot = fd['slots'].get(slot_key)
                if slot and slot[0] == groupe:
                    heures += SLOT_DURATIONS.get(c, 0)
                    break
    return heures

def add_logo_if_exists(ws, cell='A1'):
    try:
        if os.path.exists(LOGO_FILE_NAME):
            img = Image(LOGO_FILE_NAME)
            img.width = LOGO_WIDTH_PIXELS
            img.height = LOGO_HEIGHT_PIXELS
            ws.add_image(img, cell)
    except Exception:
        pass

def excel_to_bytes(wb):
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()

def clear_row_borders(ws, row_idx, start_col=1, end_col=5):
    empty_border = Border()
    for c in range(start_col, end_col + 1):
        try:
            ws.cell(row=row_idx, column=c).border = empty_border
        except Exception:
            pass

def clear_meta_borders(ws, meta_top_row=5, start_col=1, end_col=5):
    empty_border = Border()
    for r in range(1, meta_top_row + 1):
        for c in range(start_col, end_col + 1):
            try:
                ws.cell(row=r, column=c).border = empty_border
            except Exception:
                pass

def find_and_clear_signature_rows(ws, signature_text='Directeur EFP', start_col=1, end_col=5):
    try:
        sig_rows = []
        for r in range(1, ws.max_row + 1):
            v = ws.cell(row=r, column=1).value
            if isinstance(v, str) and signature_text.lower() in v.strip().lower():
                sig_rows.append(r)
        for r in sig_rows:
            clear_row_borders(ws, r, start_col, end_col)
            if r - 1 >= 1:
                clear_row_borders(ws, r - 1, start_col, end_col)
    except Exception:
        pass

def _apply_template_title(ws, title_text, heures_text, periode_text, left_meta, right_meta):
    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    title_font = Font(bold=True, size=14, name='Calibri')
    meta_font_bold = Font(bold=True, size=10, name='Calibri')
    ws.merge_cells('B1:E2')
    ws['B1'] = title_text
    ws['B1'].font = title_font
    ws['B1'].alignment = center_align

    ws.merge_cells('B3:E3')
    ws['B3'] = heures_text
    ws['B3'].font = meta_font_bold
    ws['B3'].alignment = center_align

    ws.merge_cells('B4:E4')
    ws['B4'] = periode_text
    ws['B4'].font = meta_font_bold
    ws['B4'].alignment = center_align

    for idx, (cell, value) in enumerate(left_meta, start=5):
        ws[cell] = value
        ws[cell].font = meta_font_bold
        ws[cell].alignment = Alignment(horizontal='left', vertical='center')

    for idx, val in enumerate(right_meta, start=5):
        ws[f'E{idx}'] = val
        ws[f'E{idx}'].font = meta_font_bold
        ws[f'E{idx}'].alignment = Alignment(horizontal='right', vertical='center')

def _draw_table_borders(ws, start_row, end_row, start_col=1, end_col=5, meta_top_row=5):
    thin_side = Side(style='thin', color='000000')
    border_all = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    for r in range(start_row, end_row + 1):
        for c in range(start_col, end_col + 1):
            try:
                ws.cell(row=r, column=c).border = border_all
            except Exception:
                pass

    for r in range(meta_top_row, end_row + 1):
        left_cell = ws.cell(row=r, column=start_col)
        try:
            existing = left_cell.border
            left_cell.border = Border(
                left=thin_side,
                right=existing.right if existing else thin_side,
                top=existing.top if existing else thin_side,
                bottom=existing.bottom if existing else thin_side
            )
        except Exception:
            left_cell.border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    for r in range(start_row, end_row + 1):
        right_cell = ws.cell(row=r, column=end_col)
        try:
            existing = right_cell.border
            right_cell.border = Border(
                left=existing.left if existing else thin_side,
                right=thin_side,
                top=existing.top if existing else thin_side,
                bottom=existing.bottom if existing else thin_side
            )
        except Exception:
            right_cell.border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    try:
        for m in ws.merged_cells.ranges:
            min_col, min_row, max_col, max_row = m.bounds
            if max_row >= start_row and min_row <= end_row and not (max_col < start_col or min_col > end_col):
                r1 = max(min_row, start_row)
                r2 = min(max_row, end_row)
                c1 = max(min_col, start_col)
                c2 = min(max_col, end_col)
                for rr in range(r1, r2 + 1):
                    for cc in range(c1, c2 + 1):
                        cell = ws.cell(row=rr, column=cc)
                        cell.border = border_all
    except Exception:
        pass

def copy_sheet(ws_src, ws_dest):
    from openpyxl.cell.cell import MergedCell
    import copy as _copy

    try:
        ws_dest.sheet_view.showGridLines = ws_src.sheet_view.showGridLines
    except Exception:
        pass

    try:
        for merged in ws_src.merged_cells.ranges:
            ws_dest.merge_cells(str(merged))
    except Exception:
        pass

    try:
        for col_letter, col_dim in ws_src.column_dimensions.items():
            try:
                ws_dest.column_dimensions[col_letter].width = col_dim.width
            except Exception:
                pass
    except Exception:
        pass

    try:
        for idx, row_dim in ws_src.row_dimensions.items():
            try:
                ws_dest.row_dimensions[idx].height = row_dim.height
            except Exception:
                pass
    except Exception:
        pass

    for row in ws_src.iter_rows():
        for cell in row:
            if isinstance(cell, MergedCell):
                continue
            new = ws_dest.cell(row=cell.row, column=cell.col_idx, value=cell.value)
            try:
                if getattr(cell, "has_style", False):
                    new.font = _copy.copy(cell.font)
                    new.border = _copy.copy(cell.border)
                    new.fill = _copy.copy(cell.fill)
                    new.number_format = cell.number_format
                    new.protection = _copy.copy(cell.protection)
                    new.alignment = _copy.copy(cell.alignment)
            except Exception:
                new.value = cell.value

    try:
        ws_dest.page_setup.orientation = ws_src.page_setup.orientation
        ws_dest.page_setup.paperSize = ws_src.page_setup.paperSize
        ws_dest.page_setup.fitToPage = ws_src.page_setup.fitToPage
        ws_dest.page_setup.fitToHeight = ws_src.page_setup.fitToHeight
        ws_dest.page_setup.fitToWidth = ws_src.page_setup.fitToWidth
    except Exception:
        pass

    add_logo_if_exists(ws_dest, 'A1')

    header_row = None
    try:
        for r in range(1, min(30, ws_dest.max_row) + 1):
            val = ws_dest.cell(row=r, column=1).value
            if isinstance(val, str) and val.strip().upper() == 'JOUR':
                header_row = r
                break
    except Exception:
        header_row = None

    if header_row:
        try:
            end_row = None
            for r in range(ws_dest.max_row, header_row - 1, -1):
                a_val = ws_dest.cell(row=r, column=1).value
                if (isinstance(a_val, str) and a_val.strip() in JOURS) or any([ws_dest.cell(row=r, column=c).value not in (None, '') for c in range(2,6)]):
                    end_row = r
                    break
            if end_row and end_row >= header_row:
                _draw_table_borders(ws_dest, header_row, end_row, 1, 5, meta_top_row=5)
            else:
                last_row = ws_dest.max_row
                _draw_table_borders(ws_dest, header_row, last_row, 1, 5, meta_top_row=5)
        except Exception:
            pass

    try:
        clear_meta_borders(ws_dest, meta_top_row=5, start_col=1, end_col=5)
    except Exception:
        pass
    try:
        find_and_clear_signature_rows(ws_dest, signature_text='Directeur EFP', start_col=1, end_col=5)
    except Exception:
        pass

def create_excel_formateur_semaine(formateur, data, semaine_label, mois_label, week_ranges, niveau="1ère Année", force_25_to_26=True):
    wb = openpyxl.Workbook()
    ws = wb.active
    raw_title = f"{formateur[:20]}-{mois_label[:10]}"
    ws.title = sanitize_sheet_title(raw_title)
    ws.sheet_view.showGridLines = False

    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToHeight = 1
    ws.page_setup.fitToWidth = 1

    add_logo_if_exists(ws, 'A1')

    try:
        start_dt = get_week_start_from_label(mois_label, semaine_label, week_ranges)
        end_dt = start_dt + timedelta(days=5) if start_dt else None
        periode_text = f"Date d'application: Du {start_dt.strftime('%d/%m/%Y')} au {end_dt.strftime('%d/%m/%Y')}" if start_dt and end_dt else ""
    except Exception:
        periode_text = ""

    title_text = 'EMPLOI DU TEMPS DE FORMATEUR : FORMATION HYBRIDE - V 1.0'

    heures_val_calc = compute_hours_for_formateur(data, semaine_label, mois_label, week_ranges)
    if force_25_to_26 and abs(heures_val_calc - 25.0) < 0.01:
        heures_val = 26.0
    else:
        heures_val = heures_val_calc

    heures_text = f'MASSE HORAIRE: {heures_val:.1f}H/SEMAINE'
    left_meta = [('A5', 'CFP TLRA/IFMLT'),
                 ('A6', f'Formateur: {formateur}'),
                 ('A7', f'Mois: {mois_label}'),
                 ('A8', 'Année de Formation: 2025/2026')]
    right_meta = ['', '', f'Niveau: {niveau}', '']
    _apply_template_title(ws, title_text, heures_text, periode_text, left_meta, right_meta)

    clear_meta_borders(ws, meta_top_row=5, start_col=1, end_col=5)

    header_row = 9
    header_font = Font(bold=True, size=10)
    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    border_thin = Border(left=Side(style='thin'), right=Side(style='thin'),
                         top=Side(style='thin'), bottom=Side(style='thin'))
    headers = ['JOUR'] + [f"{c}\n{HORAIRES[c]}" for c in CRENEAUX_JOUR]
    for idx, txt in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=idx, value=txt)
        cell.font = header_font
        cell.alignment = center_align
        cell.border = border_thin
    ws.row_dimensions[header_row].height = 26

    row = header_row + 1
    week_start = get_week_start_from_label(mois_label, semaine_label, week_ranges)
    for j_idx, jour in enumerate(JOURS):
        ws.cell(row=row, column=1, value=jour).font = Font(bold=True)
        ws.cell(row=row, column=1).alignment = Alignment(horizontal='center', vertical='center')
        ws.cell(row=row, column=1).border = border_thin
        d = day_date(week_start, j_idx)
        holiday_label = is_holiday(d) if d else None
        if holiday_label:
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=5)
            cell = ws.cell(row=row, column=2, value=holiday_label)
            cell.font = HOLIDAY_FONT
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.fill = HOLIDAY_FILL
            for c in range(2,6):
                ws.cell(row=row, column=c).border = border_thin
        else:
            for ci, creneau in enumerate(CRENEAUX_JOUR, start=2):
                key = f"{semaine_label}-{jour}-{creneau}"
                slot = data['slots'].get(key, ('',''))
                grp, salle = slot
                text = f"{grp}\n{salle}" if grp and salle else ""
                cell = ws.cell(row=row, column=ci, value=text)
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
                cell.font = Font(size=10, bold=True)
                cell.border = border_thin
        ws.row_dimensions[row].height = 28
        row += 1

    _draw_table_borders(ws, header_row, row-1, 1, 5, meta_top_row=5)
    clear_meta_borders(ws, meta_top_row=5, start_col=1, end_col=5)

    sig_row = row + 1
    ws.cell(row=sig_row, column=1, value='Directeur EFP').font = Font(size=10, bold=True)
    ws.cell(row=sig_row, column=1).alignment = Alignment(horizontal='left', vertical='center')
    try:
        clear_row_borders(ws, sig_row - 1, 1, 5)
    except Exception:
        pass
    try:
        clear_row_borders(ws, sig_row, 1, 5)
    except Exception:
        pass

    ws.column_dimensions['A'].width = 18
    for col in ['B','C','D','E']:
        ws.column_dimensions[col].width = 20

    return wb

def create_excel_groupe_semaine(groupe, schedule_data, semaine_label, mois_label, week_ranges, niveau="1ère Année"):
    wb = openpyxl.Workbook()
    ws = wb.active
    raw_title = f"{groupe[:20]}-{mois_label[:10]}"
    ws.title = sanitize_sheet_title(raw_title)
    ws.sheet_view.showGridLines = False

    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToHeight = 1
    ws.page_setup.fitToWidth = 1

    add_logo_if_exists(ws, 'A1')

    try:
        start_dt = get_week_start_from_label(mois_label, semaine_label, week_ranges)
        end_dt = start_dt + timedelta(days=5) if start_dt else None
        periode_text = f"Date d'application: Du {start_dt.strftime('%d/%m/%Y')} au {end_dt.strftime('%d/%m/%Y')}" if start_dt and end_dt else ""
    except Exception:
        periode_text = ""

    title_text = 'EMPLOI DU TEMPS PAR GROUPE : FORMATION HYBRIDE - V 1.0'
    heures_val = compute_hours_for_groupe(schedule_data, groupe, semaine_label, mois_label, week_ranges)
    heures_text = f'MASSE HORAIRE: {heures_val:.1f}H/SEMAINE'
    left_meta = [('A5', 'CFP TLRA/IFMLT'),
                 ('A6', f'Groupe: {groupe}'),
                 ('A7', f'Mois: {mois_label}'),
                 ('A8', 'Année de Formation: 2025/2026')]
    right_meta = ['', '', f'Niveau: {niveau}', '']
    _apply_template_title(ws, title_text, heures_text, periode_text, left_meta, right_meta)

    clear_meta_borders(ws, meta_top_row=5, start_col=1, end_col=5)

    header_row = 9
    header_font = Font(bold=True, size=10)
    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    border_thin = Border(left=Side(style='thin'), right=Side(style='thin'),
                         top=Side(style='thin'), bottom=Side(style='thin'))
    headers = ['JOUR'] + [f"{c}\n{HORAIRES[c]}" for c in CRENEAUX_JOUR]
    for idx, txt in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=idx, value=txt)
        cell.font = header_font
        cell.alignment = center_align
        cell.border = border_thin
    ws.row_dimensions[header_row].height = 26

    row = header_row + 1
    week_start = get_week_start_from_label(mois_label, semaine_label, week_ranges)
    for j_idx, jour in enumerate(JOURS):
        ws.cell(row=row, column=1, value=jour).font = Font(bold=True)
        ws.cell(row=row, column=1).alignment = Alignment(horizontal='center', vertical='center')
        d = day_date(week_start, j_idx)
        holiday_label = is_holiday(d) if d else None
        if holiday_label:
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=5)
            cell = ws.cell(row=row, column=2, value=holiday_label)
            cell.font = HOLIDAY_FONT
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.fill = HOLIDAY_FILL
            for c in range(2,6):
                ws.cell(row=row, column=c).border = border_thin
        else:
            for ci, creneau in enumerate(CRENEAUX_JOUR, start=2):
                key = f"{semaine_label}-{jour}-{creneau}"
                info = ""
                for f, fd in schedule_data.items():
                    s = fd['slots'].get(key)
                    if s and s[0] == groupe:
                        info = f"{f}\n{s[1].replace(' (CONFLIT NON RESOLU)',' (Conflit)')}"
                        break
                cell = ws.cell(row=row, column=ci, value=info)
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
                cell.font = Font(size=10, bold=True)
                cell.border = border_thin
        ws.row_dimensions[row].height = 28
        row += 1

    _draw_table_borders(ws, header_row, row-1, 1, 5, meta_top_row=5)
    clear_meta_borders(ws, meta_top_row=5, start_col=1, end_col=5)

    sig_row = row + 1
    ws.cell(row=sig_row, column=1, value='Directeur EFP').font = Font(size=10, bold=True)
    ws.cell(row=sig_row, column=1).alignment = Alignment(horizontal='left', vertical='center')
    try:
        clear_row_borders(ws, sig_row - 1, 1, 5)
    except Exception:
        pass
    try:
        clear_row_borders(ws, sig_row, 1, 5)
    except Exception:
        pass

    ws.column_dimensions['A'].width = 18
    for col in ['B','C','D','E']:
        ws.column_dimensions[col].width = 20

    return wb

@st.cache_data(show_spinner=False)
def get_available_salles(resolved_schedule, all_salles, semaine_label, jour, creneau):
    if not all_salles:
        return []
    slot_key = f"{semaine_label}-{jour}-{creneau}"
    occ = set()
    for fdata in resolved_schedule.values():
        slot = fdata['slots'].get(slot_key)
        if slot:
            s = slot[1]
            if "CONFLIT NON RESOLU" not in s:
                occ.add(s)
    return sorted(list(set(all_salles) - occ))

# --- SIDEBAR: Upload & processing ---
with st.sidebar:
    if os.path.exists(LOGO_FILE_NAME):
        st.image(LOGO_FILE_NAME, width=200)
    else:
        st.image(LOGO_URL, width=200)
    
    st.markdown("---")
    st.markdown("### 📤 Import du Fichier")
    uploaded_file = st.file_uploader("Fichier Excel multi-onglets", type=['xlsx','xls'], accept_multiple_files=False, help="Sélectionnez le fichier contenant les onglets 'Planning_Mois'")
    
    st.text_input("Niveau (valeur export)", key="niveau_global", help="Valeur affichée dans 'Niveau' sur les exports (ex: 1ère Année)")
    st.checkbox("Activer règle 25h -> 26h (masse horaire statutaire)", value=st.session_state['force_25_to_26'], key="force_25_to_26", help="Si coché, toute masse horaire calculée à 25.0 sera remplacée par 26.0 sur les exports formateur.")

    if uploaded_file:
        if st.session_state['raw_data'] is None or uploaded_file != st.session_state.get('uploaded_file_ref'):
            with st.spinner("Analyse et résolution des conflits..."):
                st.session_state['raw_data'] = process_uploaded_excel(uploaded_file)
                st.session_state['uploaded_file_ref'] = uploaded_file
                if st.session_state['raw_data']:
                    st.session_state['resolved_data'], st.session_state['conflits_log'] = resolve_salle_conflits(st.session_state['raw_data'])
                else:
                    st.session_state['resolved_data'] = None
                    st.session_state['conflits_log'] = pd.DataFrame()
                if st.session_state['resolved_data']:
                    st.success(f"✅ {len(st.session_state['resolved_data'])} mois chargés et conflits traités")
                    for month in st.session_state['resolved_data'].keys():
                        st.caption(f"📅 {month}")
                else:
                    st.error("❌ Aucune donnée valide ou erreur de traitement.")
    st.markdown("---")
    st.info(f"📅 {datetime.now().strftime('%d/%m/%Y')}\n\n🎓 Année 2025-2026")

# --- MAIN UI ---
logo_src = get_logo_src()

st.markdown(f"""
<div class="main-header">
    <img src="{logo_src}" alt="Logo OFPPT" style="max-width:200px; margin-bottom:1rem;">
    <div class="ofppt-title">OFPPT</div>
    <div class="ofppt-subtitle">Office de la Formation Professionnelle et de la Promotion du Travail</div>
    <div style="font-size:1.1rem; margin:0.5rem 0;">CFP TLRA/IFMLT</div>
    <div style="font-size:1.5rem; margin-top:1rem; font-weight:600;">📅 Gestionnaire d'Emploi du Temps (Dates exactes)</div>
    <div class="developer-info">⚡ Développé par <strong>ISMAILI ALAOUI Mohamed</strong></div>
</div>
""", unsafe_allow_html=True)

if st.session_state['resolved_data'] is None or not st.session_state['resolved_data']:
    st.markdown("""
    <div style="padding:1rem; border:2px dashed #2d8659; border-radius:10px; background:#f0f9f4;">
        <h3>📂 Bienvenue</h3>
        <p>Veuillez importer votre fichier Excel depuis le menu latéral pour commencer.</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<div class="section-header">📋 Instructions</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 📥 Format du fichier\n- Fichier Excel (.xlsx/.xls)\n- Onglets: Planning_Mois")
    with col2:
        st.markdown("### 📊 Structure\n- Colonnes: Formateur, Salle, créneaux\n- Plusieurs semaines (3/4/5) détectées automatiquement par plage de dates si présentes")
else:
    resolved = st.session_state['resolved_data']
    st.markdown('<div class="section-header">⚙️ Sélection</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)

    # --- Minimal non-intrusive change: no default proposal for the month selectbox ---
    with col1:
        months_list = ["-- Choisir un mois --"] + list(resolved.keys())
        selected_month = st.selectbox("📅 Mois", months_list, index=0)
        if selected_month == "-- Choisir un mois --":
            st.info("Aucun mois sélectionné — sélectionnez explicitement un mois importé pour continuer.")
            st.stop()

    # After explicit month selection proceed
    with col2:
        parsed = resolved[selected_month]
        semaines_list = parsed.get('semaines', FALLBACK_SEMAINES)
        week_ranges = parsed.get('week_ranges', {})

        # --- Minimal non-intrusive change: no default proposal for the week selectbox ---
        weeks_options = ["-- Choisir une semaine --"] + semaines_list
        selected_semaine = st.selectbox(
            "📆 Semaine (plage de dates)",
            weeks_options,
            index=0,
            format_func=lambda x: x if (isinstance(x, str) and x.startswith("--")) else format_week_display_label(x, week_ranges)
        )
        if selected_semaine == "-- Choisir une semaine --":
            st.info("Aucune semaine sélectionnée — sélectionnez explicitement une semaine pour continuer.")
            st.stop()

    week_ranges = parsed.get('week_ranges', {})

    week_start = get_week_start_from_label(selected_month, selected_semaine, week_ranges)
    holidays_week = []
    for i, jour in enumerate(JOURS):
        d = day_date(week_start, i)
        lbl = is_holiday(d) if d else None
        if lbl:
            holidays_week.append({'jour': jour, 'date': d.strftime('%d/%m/%Y') if d else '', 'label': lbl})
    if holidays_week:
        st.warning("⚠️ Jours fériés cette semaine (annulation des séances correspondantes dans les exports Excel):")
        for h in holidays_week:
            st.write(f"- {h['jour']} {h['date']} — {h['label']}")
    else:
        st.info("✅ Aucun jour férié pour la semaine sélectionnée.")

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"<div class='metric-card'><div style='font-size:1.4rem;font-weight:700;color:#1e5631'>{len(parsed['formateurs'])}</div><div>Formateurs</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='metric-card'><div style='font-size:1.4rem;font-weight:700;color:#1e5631'>{len(parsed['groupes'])}</div><div>Groupes</div></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='metric-card'><div style='font-size:1.4rem;font-weight:700;color:#1e5631'>{len(parsed['salles'])}</div><div>Salles</div></div>", unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["👥 Formateurs","📚 Groupes","🚪 Salles & Conflits","📊 Salles Libres Semaine","📈 Charge par Groupe"])

    with tab1:
        st.markdown('<div class="section-header">👥 Consultation / Export par Formateur</div>', unsafe_allow_html=True)
        selected_form = st.selectbox("Sélectionner un formateur", parsed['formateurs'], key="ui_form")
        if selected_form:
            fdata = parsed['schedule'][selected_form]
            df_view = build_schedule_table_for_formateur(fdata, selected_semaine, selected_month, week_ranges)
            st.dataframe(df_view, use_container_width=True)
            heures_calc = compute_hours_for_formateur(fdata, selected_semaine, selected_month, week_ranges)
            if st.session_state.get('force_25_to_26', True) and abs(heures_calc - 25.0) < 0.01:
                heures_display = 26.0
            else:
                heures_display = heures_calc
            coll, colr = st.columns([3,1])
            with coll:
                st.info(f"🏢 Salle préférée: {fdata['salle']}")
            with colr:
                st.metric("Heures (hors fériés)", f"{heures_display:.2f}h")
            st.markdown("### 📄 Export Excel")
            if st.button("📥 Générer Excel (Formateur)", key="btn_export_form"):
                wb = create_excel_formateur_semaine(selected_form, fdata, selected_semaine, selected_month, week_ranges, niveau=st.session_state.get('niveau_global','1ère Année'), force_25_to_26=st.session_state.get('force_25_to_26', True))
                filename = sanitize_sheet_title(f"EDT_Formateur_{selected_form}_{selected_month}", max_len=80) + ".xlsx"
                st.download_button("💾 Télécharger Excel", excel_to_bytes(wb), filename)

        st.markdown("---")
        if st.button("📥 Générer Pack Excel (Tous les formateurs)"):
            with st.spinner("Génération pack..."):
                wb_final = openpyxl.Workbook()
                wb_final.remove(wb_final.active)
                used_names = set()
                for form in parsed['formateurs']:
                    wb_temp = create_excel_formateur_semaine(form, parsed['schedule'][form], selected_semaine, selected_month, week_ranges, niveau=st.session_state.get('niveau_global','1ère Année'), force_25_to_26=st.session_state.get('force_25_to_26', True))
                    ws_temp = wb_temp.active
                    sheet_base = sanitize_sheet_title(f"{form[:25]}_{selected_month}", max_len=31)
                    sheet_name = sheet_base
                    i = 1
                    while sheet_name in used_names:
                        suffix = f"_{i}"
                        sheet_name = sanitize_sheet_title(sheet_base[:31-len(suffix)] + suffix)
                        i += 1
                    used_names.add(sheet_name)
                    ws_new = wb_final.create_sheet(title=sheet_name)
                    copy_sheet(ws_temp, ws_new)
                filename = sanitize_sheet_title(f"Pack_Formateurs_{selected_month}", max_len=80) + ".xlsx"
                st.download_button("💾 Télécharger Pack Excel (Formateurs)", excel_to_bytes(wb_final), filename)

    with tab2:
        st.markdown('<div class="section-header">📚 Consultation / Export par Groupe</div>', unsafe_allow_html=True)
        selected_grp = st.selectbox("Sélectionner un groupe", parsed['groupes'], key="ui_grp")
        if selected_grp:
            df_grp = build_schedule_table_for_groupe(parsed['schedule'], selected_grp, selected_semaine, selected_month, week_ranges)
            st.dataframe(df_grp, use_container_width=True)
            heures_g = compute_hours_for_groupe(parsed['schedule'], selected_grp, selected_semaine, selected_month, week_ranges)
            st.metric("Heures (hors fériés)", f"{heures_g:.2f}h")
            if st.button("📥 Générer Excel (Groupe)"):
                wb = create_excel_groupe_semaine(selected_grp, parsed['schedule'], selected_semaine, selected_month, week_ranges, niveau=st.session_state.get('niveau_global','1ère Année'))
                filename = sanitize_sheet_title(f"EDT_Groupe_{selected_grp}_{selected_month}", max_len=80) + ".xlsx"
                st.download_button("💾 Télécharger Excel", excel_to_bytes(wb), filename)

        st.markdown("---")
        if st.button("📥 Générer Pack Excel (Tous les groupes)"):
            with st.spinner("Génération pack..."):
                wb_final = openpyxl.Workbook()
                wb_final.remove(wb_final.active)
                used_names = set()
                for groupe in parsed['groupes']:
                    wb_temp = create_excel_groupe_semaine(groupe, parsed['schedule'], selected_semaine, selected_month, week_ranges, niveau=st.session_state.get('niveau_global','1ère Année'))
                    ws_temp = wb_temp.active
                    sheet_base = sanitize_sheet_title(f"{groupe[:25]}_{selected_month}", max_len=31)
                    sheet_name = sheet_base
                    i = 1
                    while sheet_name in used_names:
                        suffix = f"_{i}"
                        sheet_name = sanitize_sheet_title(sheet_base[:31-len(suffix)] + suffix)
                        i += 1
                    used_names.add(sheet_name)
                    ws_new = wb_final.create_sheet(title=sheet_name)
                    copy_sheet(ws_temp, ws_new)
                filename = sanitize_sheet_title(f"Pack_Groupes_{selected_month}", max_len=80) + ".xlsx"
                st.download_button("💾 Télécharger Pack Excel (Groupes)", excel_to_bytes(wb_final), filename)

    with tab3:
        st.markdown('<div class="section-header">🚪 Salles & Conflits</div>', unsafe_allow_html=True)
        colj, colc, cold = st.columns(3)
        with colj:
            sel_jour = st.selectbox("Jour", JOURS, key="salle_jour")
        with colc:
            sel_cr = st.selectbox("Créneau", CRENEAUX_JOUR, key="salle_cr")
        salles_libres = get_available_salles(parsed['schedule'], parsed['salles'], selected_semaine, sel_jour, sel_cr) if sel_jour and sel_cr else []
        st.metric("Salles disponibles", len(salles_libres))
        if salles_libres:
            st.write(", ".join(salles_libres))
        else:
            st.write("Aucune salle disponible")
        st.markdown("---")
        conflits = st.session_state['conflits_log']
        if conflits.empty:
            st.info("Aucun conflit détecté.")
        else:
            cs = conflits[(conflits['Mois']==selected_month) & (conflits['Semaine']==selected_semaine)]
            st.dataframe(cs, use_container_width=True)
            if not cs.empty:
                b = BytesIO()
                cs.to_excel(b, index=False, sheet_name='Conflits')
                b.seek(0)
                st.download_button("📥 Télécharger Conflits", b.getvalue(), f"Conflits_{selected_month}_{selected_semaine}.xlsx")

    with tab4:
        st.markdown('<div class="section-header">📊 Synthèse Salles Libres</div>', unsafe_allow_html=True)
        synth = []
        week_start = get_week_start_from_label(selected_month, selected_semaine, week_ranges)
        for jour in JOURS:
            for c in CRENEAUX_JOUR:
                key = f"{selected_semaine}-{jour}-{c}"
                d = day_date(week_start, JOURS.index(jour))
                holiday = True if (d and is_holiday(d)) else False
                occ = set()
                if not holiday:
                    for f, fd in parsed['schedule'].items():
                        s = fd['slots'].get(key)
                        if s and s[0]:
                            occ.add(s[1].replace(' (CONFLIT NON RESOLU)','').replace(' (Conflit)',''))
                libres = sorted(list(set(parsed['salles']) - occ))
                synth.append({'Jour': jour, 'Créneau': c, 'Horaire': HORAIRES[c], 'Nb Salles Libres': len(libres), 'Salles Disponibles': ', '.join(libres) if libres else 'Aucune'})
        st.dataframe(pd.DataFrame(synth), use_container_width=True)

    with tab5:
        st.markdown('<div class="section-header">📈 Analyse de la Charge par Groupe</div>', unsafe_allow_html=True)
        st.info(f"📅 Analyse pour : **{selected_month} - {selected_semaine}**")

        charge_groupes = []
        for groupe in parsed['groupes']:
            heures_total = 0
            nb_creneaux = 0
            for jour in JOURS:
                for creneau in CRENEAUX_JOUR:
                    slot_key = f"{selected_semaine}-{jour}-{creneau}"
                    for formateur, f_data in parsed['schedule'].items():
                        slot_data = f_data['slots'].get(slot_key)
                        if slot_data and slot_data[0] == groupe:
                            heures_total += SLOT_DURATIONS[creneau]
                            nb_creneaux += 1
                            break
            charge_groupes.append({'Groupe': groupe, 'Heures de Formation': heures_total, 'Nombre de Créneaux': nb_creneaux})

        if not charge_groupes:
            st.info("Aucune donnée de charge disponible pour la semaine sélectionnée.")
        else:
            df_charge = pd.DataFrame(charge_groupes)
            if 'Heures de Formation' not in df_charge.columns:
                st.warning("La colonne 'Heures de Formation' est manquante dans les données ; affichage interrompu.")
                st.dataframe(df_charge, use_container_width=True)
            else:
                df_charge = df_charge.sort_values('Heures de Formation', ascending=False)
                moyenne_heures = df_charge['Heures de Formation'].mean()
                col_met1, col_met2, col_met3, col_met4 = st.columns(4)
                with col_met1:
                    st.metric("Groupes Total", len(df_charge))
                with col_met2:
                    st.metric("Charge Moyenne", f"{moyenne_heures:.1f}h")
                with col_met3:
                    st.metric("Charge Minimale", f"{df_charge['Heures de Formation'].min():.1f}h")
                with col_met4:
                    st.metric("Charge Maximale", f"{df_charge['Heures de Formation'].max():.1f}h")

                import plotly.graph_objects as go
                colors = []
                seuil_bas = moyenne_heures * 0.85
                seuil_haut = moyenne_heures * 1.15
                for heures in df_charge['Heures de Formation']:
                    if heures > seuil_haut:
                        colors.append('#d32f2f')
                    elif heures >= seuil_bas and heures <= seuil_haut:
                        colors.append('#fbc02d')
                    else:
                        colors.append('#388e3c')
                fig = go.Figure(data=[go.Bar(x=df_charge['Groupe'], y=df_charge['Heures de Formation'], text=df_charge['Heures de Formation'].apply(lambda x: f"{x:.1f}h"), textposition='outside', marker=dict(color=colors, line=dict(color='#1e5631', width=1.5)), hovertemplate='<b>%{x}</b><br>Heures: %{y:.1f}h<br><extra></extra>')])
                fig.add_hline(y=moyenne_heures, line_dash="dash", line_color="#1e5631", annotation_text=f"Moyenne: {moyenne_heures:.1f}h", annotation_position="right")
                fig.add_hline(y=seuil_haut, line_dash="dot", line_color="#d32f2f", opacity=0.5)
                fig.add_hline(y=seuil_bas, line_dash="dot", line_color="#388e3c", opacity=0.5)
                fig.update_layout(title={'text': f'Charge Horaire par Groupe - {selected_month} {selected_semaine}', 'x': 0.5}, xaxis_title='Groupes', yaxis_title='Heures de Formation', plot_bgcolor='white', paper_bgcolor='#f8faf9', height=500, showlegend=False, xaxis=dict(tickangle=-45, gridcolor='lightgray'), yaxis=dict(gridcolor='lightgray'))
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("---")
                def categoriser_charge_moyenne(heures, moyenne, seuil_bas, seuil_haut):
                    if heures > seuil_haut:
                        return "🔴 Trop Chargé"
                    elif heures >= seuil_bas and heures <= seuil_haut:
                        return "🟡 Chargé"
                    else:
                        return "🟢 Normal"
                df_charge['Catégorie'] = df_charge['Heures de Formation'].apply(lambda x: categoriser_charge_moyenne(x, moyenne_heures, seuil_bas, seuil_haut))
                df_charge['Écart/Moyenne'] = df_charge['Heures de Formation'] - moyenne_heures
                df_charge['Écart/Moyenne'] = df_charge['Écart/Moyenne'].apply(lambda x: f"{x:+.1f}h")
                st.dataframe(df_charge, use_container_width=True)
                st.markdown("---")
                st.info(f"""
                **Légende:**
                - 🔴 **Trop Chargé**: > {seuil_haut:.1f}h (au-dessus de +15% de la moyenne)
                - 🟡 **Chargé**: {seuil_bas:.1f}h - {seuil_haut:.1f}h (proche de la moyenne ±15%)
                - 🟢 **Normal**: < {seuil_bas:.1f}h (inférieur de -15% de la moyenne - Pas chargé)
                """)
                col_stat1, col_stat2, col_stat3 = st.columns(3)
                with col_stat1:
                    nb_trop_charge = len(df_charge[df_charge['Heures de Formation'] > seuil_haut])
                    st.markdown(f"""<div class="metric-card" style="border-left-color: #d32f2f;"><div class="metric-value">{nb_trop_charge}</div><div class="metric-label">🔴 Trop Chargés<br/>(Au-dessus moyenne)</div></div>""", unsafe_allow_html=True)
                with col_stat2:
                    nb_charge = len(df_charge[(df_charge['Heures de Formation'] >= seuil_bas) & (df_charge['Heures de Formation'] <= seuil_haut)])
                    st.markdown(f"""<div class="metric-card" style="border-left-color: #fbc02d;"><div class="metric-value">{nb_charge}</div><div class="metric-label">🟡 Chargés<br/>(Proche moyenne)</div></div>""", unsafe_allow_html=True)
                with col_stat3:
                    nb_normal = len(df_charge[df_charge['Heures de Formation'] < seuil_bas])
                    st.markdown(f"""<div class="metric-card" style="border-left-color: #388e3c;"><div class="metric-value">{nb_normal}</div><div class="metric-label">🟢 Normaux<br/>(En bas de la moyenne - Pas chargé)</div></div>""", unsafe_allow_html=True)
                st.markdown("---")
                if st.button("📥 Exporter l'Analyse de Charge (Excel)", key="btn_export_charge"):
                    wb_charge = openpyxl.Workbook()
                    ws = wb_charge.active
                    ws.title = sanitize_sheet_title("Charge_Groupes")
                    ws.sheet_view.showGridLines = False
                    border_thin = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
                    header_font = Font(bold=True, size=11, color="FFFFFF")
                    title_font = Font(bold=True, size=14, color="1e5631")
                    header_fill = PatternFill(start_color="2d8659", end_color="2d8659", fill_type="solid")
                    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
                    ws['A1'] = f'ANALYSE DE CHARGE PAR GROUPE - {selected_month} {selected_semaine}'
                    ws.merge_cells('A1:E1'); ws['A1'].font = title_font; ws['A1'].alignment = center_align; ws.row_dimensions[1].height = 25
                    ws['A2'] = f'Moyenne: {moyenne_heures:.1f}h | Seuils: Normal < {seuil_bas:.1f}h | Chargé: {seuil_bas:.1f}h-{seuil_haut:.1f}h | Trop Chargé > {seuil_haut:.1f}h'
                    ws.merge_cells('A2:E2'); ws['A2'].alignment = center_align; ws.row_dimensions[2].height = 20
                    ws['A4'] = 'Groupe'; ws['B4'] = 'Heures de Formation'; ws['C4'] = 'Nombre de Créneaux'; ws['D4'] = 'Niveau de Charge'; ws['E4'] = 'Écart/Moyenne'
                    for col in ['A','B','C','D','E']:
                        ws[f'{col}4'].font = header_font; ws[f'{col}4'].fill = header_fill; ws[f'{col}4'].border = border_thin; ws[f'{col}4'].alignment = center_align; ws.column_dimensions[col].width = 25
                    row = 5
                    for _, data_row in df_charge.iterrows():
                        ws[f'A{row}'] = data_row['Groupe']; ws[f'B{row}'] = data_row['Heures de Formation']; ws[f'C{row}'] = data_row['Nombre de Créneaux']; ws[f'D{row}'] = data_row['Catégorie']; ws[f'E{row}'] = data_row['Écart/Moyenne']
                        for col in ['A','B','C','D','E']:
                            ws[f'{col}{row}'].border = border_thin; ws[f'{col}{row}'].alignment = center_align
                        row += 1
                    excel_bytes = excel_to_bytes(wb_charge)
                    st.download_button("💾 Télécharger l'Analyse", excel_bytes, f"Charge_Groupes_{selected_month}_{selected_semaine}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

st.markdown("---")
st.markdown("<div style='text-align:center;color:#666;padding:1rem;'>Développé par ISMAILI ALAOUI Mohamed — CFP TLRA/IFMLT</div>", unsafe_allow_html=True)
