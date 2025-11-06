import streamlit as st
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.drawing.image import Image
from openpyxl.utils import get_column_letter
from io import BytesIO
from datetime import datetime, timedelta
import copy
import os
import re

# Configuration Streamlit
st.set_page_config(
    page_title="Gestionnaire d'Emploi du Temps - OFPPT",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded"
)

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
LOGO_FILE_NAME = "Logo_ofppt.png"  # keep this file in project root for Excel exports
LOGO_URL = "https://www.ofppt.ma/sites/default/files/logo.png"  # used for Streamlit display
LOGO_WIDTH_PIXELS = 70
LOGO_HEIGHT_PIXELS = 70

SEMAINES = ['S1', 'S2', 'S3', 'S4']
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

# Example holidays (edit as needed)
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

# --- UTILITIES: dates / holidays ---
def get_week_start_datetime(mois, semaine, annee=2025):
    if mois in ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet']:
        annee = 2026
    mois_num = MONTH_TO_NUMBER.get(mois)
    if not mois_num:
        return None
    first_day = datetime(annee, mois_num, 1)
    days_until_monday = (7 - first_day.weekday()) % 7
    first_monday = first_day + timedelta(days=days_until_monday) if first_day.weekday() != 0 else first_day
    semaine_num = int(semaine[1:]) - 1
    return first_monday + timedelta(weeks=semaine_num)

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

# --- PARSING EXCEL input ---
def extract_month_name_from_sheet(sheet_name):
    normalized = sheet_name.replace('Planning_', '').strip()
    for key, value in MONTH_NAMES.items():
        if key.lower() in normalized.lower():
            return value
    return None

def find_header_row(df):
    for idx, row in df.iterrows():
        vals = [str(x).strip() for x in row.values if pd.notna(x)]
        if any(v.lower() == 'formateur' or v.lower() == 'form' for v in vals) and any(c in vals for c in ['AM1','AM2','PM1','PM2']):
            return idx
    return None

@st.cache_data(show_spinner=False)
def parse_schedule_sheet(df, sheet_name):
    month_name = extract_month_name_from_sheet(sheet_name)
    if month_name is None:
        return None
    header_idx = find_header_row(df)
    if header_idx is None:
        return None
    header_row = df.iloc[header_idx]
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
    for s in SEMAINES:
        for j in JOURS:
            for c in CRENEAUX_JOUR:
                if cur < len(header_row):
                    col_map[f"{s}-{j}-{c}"] = cur
                    cur += 1
    for _, row in df_data.iterrows():
        form = str(row.iloc[col_form]).strip()
        salle = str(row.iloc[col_salle]).strip() if col_salle < len(row) else ''
        if not form or form.lower() in ('nan','none',''):
            continue
        schedule[form] = {'salle': salle, 'slots': {}}
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
    return {'month': month_name, 'schedule': schedule, 'formateurs': sorted(schedule.keys()), 'groupes': sorted(list(groupes)), 'salles': sorted(list(salles))}

@st.cache_data(show_spinner=False)
def process_uploaded_excel(uploaded_file):
    all_data = {}
    try:
        xls = pd.ExcelFile(uploaded_file)
        for sheet_name in xls.sheet_names:
            if sheet_name in IGNORED_SHEETS:
                continue
            df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            parsed = parse_schedule_sheet(df, sheet_name)
            if parsed:
                all_data[parsed['month']] = parsed
        sorted_data = {m: all_data[m] for m in MONTH_ORDER if m in all_data}
        return sorted_data
    except Exception as e:
        st.error(f"Erreur import: {e}")
        return {}

# --- CONFLICT RESOLUTION (kept similar) ---
@st.cache_data(show_spinner=False)
def resolve_salle_conflits(all_data):
    resolved = copy.deepcopy(all_data)
    log = []
    all_salles = set()
    for month in resolved.values():
        all_salles.update(month['salles'])
    HALF_DAY = [('AM1','AM2'), ('PM1','PM2')]
    for month_name, month_data in resolved.items():
        schedule = month_data['schedule']
        for semaine in SEMAINES:
            for jour in JOURS:
                for c1, c2 in HALF_DAY:
                    key1 = f"{semaine}-{jour}-{c1}"
                    key2 = f"{semaine}-{jour}-{c2}"
                    occ1 = set()
                    occ2 = set()
                    for f, fd in schedule.items():
                        s1 = fd['slots'].get(key1)
                        s2 = fd['slots'].get(key2)
                        if s1 and s1[0]:
                            occ1.add(fd['salle'])
                        if s2 and s2[0]:
                            occ2.add(fd['salle'])
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
                        if pref not in occupied:
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
                                assigned = f"{pref} (CONFLIT NON RESOLU)"
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

# --- UI helper tables (no dates in JOUR column) ---
def build_schedule_table_for_formateur(formateur_data, semaine, mois):
    week_start = get_week_start_datetime(mois, semaine)
    rows = []
    for i, jour in enumerate(JOURS):
        holiday = None
        if week_start:
            holiday = is_holiday((week_start + timedelta(days=i)).date())
        row = {'JOUR': jour}
        for c in CRENEAUX_JOUR:
            key = f"{semaine}-{jour}-{c}"
            if holiday:
                row[c] = ""
            else:
                slot = formateur_data['slots'].get(key, ('',''))
                grp, salle = slot
                row[c] = f"{grp}\n{salle}" if grp and salle else ""
        rows.append(row)
    return pd.DataFrame(rows)

def build_schedule_table_for_groupe(schedule_data, groupe, semaine, mois):
    week_start = get_week_start_datetime(mois, semaine)
    rows = []
    for i, jour in enumerate(JOURS):
        holiday = None
        if week_start:
            holiday = is_holiday((week_start + timedelta(days=i)).date())
        row = {'JOUR': jour}
        for c in CRENEAUX_JOUR:
            key = f"{semaine}-{jour}-{c}"
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

# --- Helpers for hours and logo ---
def compute_hours_for_formateur(formateur_data, semaine, mois):
    heures = 0.0
    week_start = get_week_start_datetime(mois, semaine)
    for jour_idx, jour in enumerate(JOURS):
        if week_start:
            day_dt = (week_start + timedelta(days=jour_idx)).date()
            if is_holiday(day_dt):
                continue
        for c in CRENEAUX_JOUR:
            slot_key = f"{semaine}-{jour}-{c}"
            if slot_key in formateur_data.get('slots', {}):
                heures += SLOT_DURATIONS.get(c, 0)
    return heures

def compute_hours_for_groupe(schedule_data, groupe, semaine, mois):
    heures = 0.0
    week_start = get_week_start_datetime(mois, semaine)
    for jour_idx, jour in enumerate(JOURS):
        if week_start:
            day_dt = (week_start + timedelta(days=jour_idx)).date()
            if is_holiday(day_dt):
                continue
        for c in CRENEAUX_JOUR:
            slot_key = f"{semaine}-{jour}-{c}"
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

# --- EXCEL export helpers ---
def excel_to_bytes(wb):
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()

def apply_border_rectangle(ws, start_row, start_col, end_row, end_col, border):
    for r in range(start_row, end_row+1):
        for c in range(start_col, end_col+1):
            ws.cell(row=r, column=c).border = border

# --- EXCEL create for formateur (header moved up by 2 lines across all sheets) ---
def create_excel_formateur_semaine(formateur, data, semaine, mois):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{formateur[:20]}-{semaine}"
    ws.sheet_view.showGridLines = False

    # page setup (ensure landscape)
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToHeight = 1
    ws.page_setup.fitToWidth = 1
    ws.print_options.horizontalCentered = True
    ws.print_options.verticalCentered = True

    border_thin = Border(left=Side(style='thin', color='000000'),
                         right=Side(style='thin', color='000000'),
                         top=Side(style='thin', color='000000'),
                         bottom=Side(style='thin', color='000000'))
    title_font = Font(bold=True, size=12, name='Calibri')
    meta_font = Font(bold=True, size=10, name='Calibri')
    header_font = Font(bold=True, size=11, name='Calibri')
    normal_font = Font(size=10, name='Calibri')
    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    left_align = Alignment(horizontal='left', vertical='center')

    # Add logo if exists (ensures individual file has logo)
    add_logo_if_exists(ws, 'A1')

    # Title moved up by 2 lines: now at B1:E2
    ws.merge_cells('B1:E2')
    ws['B1'] = 'EMPLOI DU TEMPS DE FORMATEUR : FORMATION HYBRIDE - V 1.0'
    ws['B1'].font = title_font
    ws['B1'].alignment = center_align
    ws.row_dimensions[1].height = 26
    ws.row_dimensions[2].height = 18

    # MASS HORAIRE centered under title: B3:E3 (moved up)
    heures = compute_hours_for_formateur(data, semaine, mois)
    ws.merge_cells('B3:E3')
    ws['B3'] = f'MASSE HORAIRE: {heures:.1f}H/SEMAINE'
    ws['B3'].font = meta_font
    ws['B3'].alignment = center_align

    # Date d'application (week range) centered under mass: B4:E4
    try:
        start_dt = get_week_start_datetime(mois, semaine)
        end_dt = start_dt + timedelta(days=5)
        periode_text = f"Du {start_dt.strftime('%d/%m/%Y')} au {end_dt.strftime('%d/%m/%Y')}"
    except Exception:
        periode_text = ""
    ws.merge_cells('B4:E4')
    ws['B4'] = f"Date d'application: {periode_text}" if periode_text else ""
    ws['B4'].font = meta_font
    ws['B4'].alignment = center_align

    # Meta lines on left (A5..A8) (moved up)
    ws['A5'] = 'CFP TLRA/IFMLT'
    ws['A5'].font = meta_font
    ws['A5'].alignment = left_align

    ws['A6'] = f'Formateur: {formateur}'
    ws['A6'].font = meta_font
    ws['A6'].alignment = left_align

    ws['A7'] = f'Semaine: {semaine} ({mois})'
    ws['A7'].font = meta_font
    ws['A7'].alignment = left_align

    ws['A8'] = 'Année de Formation: 2025/2026'
    ws['A8'].font = meta_font
    ws['A8'].alignment = left_align

    # Table header: now row 9 (shifted up by 2)
    header_row = 9
    headers = ['JOUR',
               f'AM1\n{HORAIRES["AM1"]}',
               f'AM2\n{HORAIRES["AM2"]}',
               f'PM1\n{HORAIRES["PM1"]}',
               f'PM2\n{HORAIRES["PM2"]}']
    for idx, txt in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=idx, value=txt)
        cell.font = header_font
        cell.alignment = center_align
        cell.border = border_thin
    ws.row_dimensions[header_row].height = 26

    # Fill rows starting row 10
    row = header_row + 1
    week_start = get_week_start_datetime(mois, semaine)
    for j_idx, jour in enumerate(JOURS):
        # Column A: centered day name
        ws.cell(row=row, column=1, value=jour).font = meta_font
        ws.cell(row=row, column=1).alignment = center_align
        ws.cell(row=row, column=1).border = border_thin

        holiday_label = None
        if week_start:
            daydt = (week_start + timedelta(days=j_idx)).date()
            holiday_label = is_holiday(daydt)

        if holiday_label:
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=5)
            ws.cell(row=row, column=2, value=holiday_label).font = meta_font
            ws.cell(row=row, column=2).alignment = center_align
            for c in range(2,6):
                cell = ws.cell(row=row, column=c)
                cell.fill = HOLIDAY_FILL
                cell.font = HOLIDAY_FONT
                cell.alignment = center_align
                cell.border = border_thin
        else:
            for ci, creneau in enumerate(CRENEAUX_JOUR, start=2):
                key = f"{semaine}-{jour}-{creneau}"
                slot = data['slots'].get(key, ('',''))
                grp, salle = slot
                text = f"{grp}\n{salle}" if grp and salle else ""
                cell = ws.cell(row=row, column=ci, value=text)
                cell.font = Font(size=10, name='Calibri')
                cell.alignment = center_align
                cell.border = border_thin

        ws.row_dimensions[row].height = 28
        row += 1

    end_table_row = row - 1
    # Ensure right border (column E) for all table rows (including header)
    for r in range(header_row, end_table_row+1):
        ws.cell(row=r, column=5).border = border_thin

    # Signature
    sig_row = end_table_row + 2
    ws.cell(row=sig_row, column=1, value='Directeur EFP').font = normal_font
    ws.cell(row=sig_row, column=1).alignment = Alignment(horizontal='left', vertical='center')

    # Column widths
    ws.column_dimensions['A'].width = 18
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 20
    ws.column_dimensions['D'].width = 20
    ws.column_dimensions['E'].width = 20

    return wb

# --- EXCEL create for groupe (header moved up by 2 lines across all sheets) ---
def create_excel_groupe_semaine(groupe, schedule_data, semaine, mois):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{groupe[:20]}-{semaine}"
    ws.sheet_view.showGridLines = False

    # ensure landscape
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToHeight = 1
    ws.page_setup.fitToWidth = 1
    ws.print_options.horizontalCentered = True
    ws.print_options.verticalCentered = True

    border_thin = Border(left=Side(style='thin', color='000000'),
                         right=Side(style='thin', color='000000'),
                         top=Side(style='thin', color='000000'),
                         bottom=Side(style='thin', color='000000'))
    title_font = Font(bold=True, size=12, name='Calibri')
    meta_font = Font(bold=True, size=10, name='Calibri')
    header_font = Font(bold=True, size=11, name='Calibri')
    normal_font = Font(size=10, name='Calibri')
    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    left_align = Alignment(horizontal='left', vertical='center')

    # Add logo if exists
    add_logo_if_exists(ws, 'A1')

    # Title: B1:E2 (moved up)
    ws.merge_cells('B1:E2')
    ws['B1'] = 'EMPLOI DU TEMPS PAR GROUPE : FORMATION HYBRIDE - V 1.0'
    ws['B1'].font = title_font
    ws['B1'].alignment = center_align
    ws.row_dimensions[1].height = 26
    ws.row_dimensions[2].height = 18

    # MASS HORAIRE centered under title: B3:E3
    heures = compute_hours_for_groupe(schedule_data, groupe, semaine, mois)
    ws.merge_cells('B3:E3')
    ws['B3'] = f'MASSE HORAIRE: {heures:.1f}H/SEMAINE'
    ws['B3'].font = meta_font
    ws['B3'].alignment = center_align

    # Date d'application centered under mass: B4:E4
    try:
        start_dt = get_week_start_datetime(mois, semaine)
        end_dt = start_dt + timedelta(days=5)
        periode_text = f"Du {start_dt.strftime('%d/%m/%Y')} au {end_dt.strftime('%d/%m/%Y')}"
    except Exception:
        periode_text = ""
    ws.merge_cells('B4:E4')
    ws['B4'] = f"Date d'application: {periode_text}" if periode_text else ""
    ws['B4'].font = meta_font
    ws['B4'].alignment = center_align

    # Meta lines on left (A5..A8)
    ws['A5'] = 'CFP TLRA/IFMLT'
    ws['A5'].font = meta_font
    ws['A5'].alignment = left_align

    ws['A6'] = f'Groupe: {groupe}'
    ws['A6'].font = meta_font
    ws['A6'].alignment = left_align

    ws['A7'] = f'Semaine: {semaine} ({mois})'
    ws['A7'].font = meta_font
    ws['A7'].alignment = left_align

    ws['A8'] = 'Année de Formation: 2025/2026'
    ws['A8'].font = meta_font
    ws['A8'].alignment = left_align

    # Table header row 9
    header_row = 9
    headers = ['JOUR',
               f'AM1\n{HORAIRES["AM1"]}',
               f'AM2\n{HORAIRES["AM2"]}',
               f'PM1\n{HORAIRES["PM1"]}',
               f'PM2\n{HORAIRES["PM2"]}']
    for idx, txt in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=idx, value=txt)
        cell.font = header_font
        cell.alignment = center_align
        cell.border = border_thin
    ws.row_dimensions[header_row].height = 26

    # Fill rows starting row 10
    row = header_row + 1
    week_start = get_week_start_datetime(mois, semaine)
    for j_idx, jour in enumerate(JOURS):
        ws.cell(row=row, column=1, value=jour).font = meta_font
        ws.cell(row=row, column=1).alignment = center_align
        ws.cell(row=row, column=1).border = border_thin

        holiday_label = None
        if week_start:
            holiday_label = is_holiday((week_start + timedelta(days=j_idx)).date())
        if holiday_label:
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=5)
            ws.cell(row=row, column=2, value=holiday_label).font = meta_font
            ws.cell(row=row, column=2).alignment = center_align
            for c in range(2,6):
                cell = ws.cell(row=row, column=c)
                cell.fill = HOLIDAY_FILL
                cell.font = HOLIDAY_FONT
                cell.alignment = center_align
                cell.border = border_thin
        else:
            for ci, creneau in enumerate(CRENEAUX_JOUR, start=2):
                key = f"{semaine}-{jour}-{creneau}"
                info = ""
                for f, fd in schedule_data.items():
                    s = fd['slots'].get(key)
                    if s and s[0] == groupe:
                        info = f"{f}\n{s[1].replace(' (CONFLIT NON RESOLU)',' (Conflit)')}"
                        break
                cell = ws.cell(row=row, column=ci, value=info)
                cell.font = Font(size=10, name='Calibri')
                cell.alignment = center_align
                cell.border = border_thin

        ws.row_dimensions[row].height = 28
        row += 1

    end_table = row - 1
    for r in range(header_row, end_table+1):
        ws.cell(row=r, column=5).border = border_thin

    sig_row = end_table + 2
    ws.cell(row=sig_row, column=1, value='Directeur EFP').font = normal_font
    ws.cell(row=sig_row, column=1).alignment = Alignment(horizontal='left', vertical='center')

    ws.column_dimensions['A'].width = 18
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 20
    ws.column_dimensions['D'].width = 20
    ws.column_dimensions['E'].width = 20

    return wb

# --- get_available_salles (simple) ---
@st.cache_data(show_spinner=False)
def get_available_salles(resolved_schedule, all_salles, semaine, jour, creneau):
    if not all_salles:
        return []
    slot_key = f"{semaine}-{jour}-{creneau}"
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
    st.image(LOGO_URL, width=200)
    st.markdown("---")
    st.markdown("### 📤 Import du Fichier")
    uploaded_file = st.file_uploader("Fichier Excel multi-onglets", type=['xlsx','xls'], accept_multiple_files=False, help="Sélectionnez le fichier contenant les onglets 'Planning_Mois'")
    if 'raw_data' not in st.session_state:
        st.session_state['raw_data'] = None
    if 'resolved_data' not in st.session_state:
        st.session_state['resolved_data'] = None
    if 'conflits_log' not in st.session_state:
        st.session_state['conflits_log'] = pd.DataFrame()
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
st.markdown(f"""
<div class="main-header">
    <img src="{LOGO_URL}" alt="Logo OFPPT" style="max-width:200px; margin-bottom:1rem;">
    <div class="ofppt-title">OFPPT</div>
    <div class="ofppt-subtitle">Office de la Formation Professionnelle et de la Promotion du Travail</div>
    <div style="font-size:1.1rem; margin:0.5rem 0;">CFP TLRA/IFMLT</div>
    <div style="font-size:1.5rem; margin-top:1rem; font-weight:600;">📅 Gestionnaire d'Emploi du Temps</div>
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
        st.markdown("### 📊 Structure\n- Colonnes: Formateur, Salle, créneaux\n- 4 semaines (S1-S4)\n- 6 jours × 4 créneaux")
else:
    resolved = st.session_state['resolved_data']
    st.markdown('<div class="section-header">⚙️ Sélection</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        selected_month = st.selectbox("📅 Mois", list(resolved.keys()))
    with col2:
        selected_semaine = st.selectbox("📆 Semaine", SEMAINES, index=0)
    parsed = resolved[selected_month]

    # show holidays summary (but JOUR column displays only names)
    week_start = get_week_start_datetime(selected_month, selected_semaine)
    holidays_week = []
    if week_start:
        for i, jour in enumerate(JOURS):
            d = (week_start + timedelta(days=i)).date()
            lbl = is_holiday(d)
            if lbl:
                holidays_week.append({'jour': jour, 'date': d.strftime('%d/%m/%Y'), 'label': lbl})
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

    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["👥 Formateurs","📚 Groupes","🚪 Salles & Conflits","📊 Salles Libres Semaine","📈 Charge par Groupe"])

    # Tab1: Formateurs
    with tab1:
        st.markdown('<div class="section-header">👥 Consultation / Export par Formateur</div>', unsafe_allow_html=True)
        selected_form = st.selectbox("Sélectionner un formateur", parsed['formateurs'], key="ui_form")
        if selected_form:
            fdata = parsed['schedule'][selected_form]
            df_view = build_schedule_table_for_formateur(fdata, selected_semaine, selected_month)
            st.dataframe(df_view, use_container_width=True)
            # preferred room and hours (excluding holidays)
            heures = compute_hours_for_formateur(fdata, selected_semaine, selected_month)
            coll, colr = st.columns([3,1])
            with coll:
                st.info(f"🏢 Salle préférée: {fdata['salle']}")
            with colr:
                st.metric("Heures (hors fériés)", f"{heures:.2f}h")
            st.markdown("### 📄 Export Excel")
            if st.button("📥 Générer Excel (Formateur)", key="btn_export_form"):
                wb = create_excel_formateur_semaine(selected_form, fdata, selected_semaine, selected_month)
                st.download_button("💾 Télécharger Excel", excel_to_bytes(wb), f"EDT_Formateur_{selected_form}_{selected_month}_{selected_semaine}.xlsx")

        st.markdown("---")
        if st.button("📥 Générer Pack Excel (Tous les formateurs)"):
            with st.spinner("Génération pack..."):
                wb_final = openpyxl.Workbook()
                # remove default sheet
                wb_final.remove(wb_final.active)
                for form in parsed['formateurs']:
                    wb_temp = create_excel_formateur_semaine(form, parsed['schedule'][form], selected_semaine, selected_month)
                    ws_temp = wb_temp.active
                    sheet_name = f"{form[:25]}_{selected_semaine}"
                    ws_new = wb_final.create_sheet(title=sheet_name)
                    ws_new.sheet_view.showGridLines = False

                    # ensure page setup is landscape on new sheet
                    ws_new.page_setup.orientation = ws_temp.page_setup.orientation
                    ws_new.page_setup.paperSize = ws_temp.page_setup.paperSize
                    ws_new.page_setup.fitToPage = True
                    ws_new.page_setup.fitToHeight = 1
                    ws_new.page_setup.fitToWidth = 1
                    ws_new.print_options.horizontalCentered = True
                    ws_new.print_options.verticalCentered = True

                    # Add logo explicitly to ensure presence in each sheet
                    add_logo_if_exists(ws_new, 'A1')

                    # Copy cells (value + style)
                    for row_idx in range(1, ws_temp.max_row + 1):
                        for col_idx in range(1, ws_temp.max_column + 1):
                            cell = ws_temp.cell(row=row_idx, column=col_idx)
                            new_cell = ws_new.cell(row=row_idx, column=col_idx, value=cell.value)
                            if cell.has_style:
                                try:
                                    new_cell.font = copy.copy(cell.font)
                                    new_cell.fill = copy.copy(cell.fill)
                                    new_cell.border = copy.copy(cell.border)
                                    new_cell.alignment = copy.copy(cell.alignment)
                                except Exception:
                                    pass

                    # Copy merged cells
                    for merged in ws_temp.merged_cells.ranges:
                        try:
                            ws_new.merge_cells(str(merged))
                        except Exception:
                            pass

                    # Copy column widths and row heights
                    for col_letter, col_dim in ws_temp.column_dimensions.items():
                        try:
                            ws_new.column_dimensions[col_letter].width = col_dim.width
                        except Exception:
                            pass
                    for rnum, rd in ws_temp.row_dimensions.items():
                        try:
                            ws_new.row_dimensions[rnum].height = rd.height
                        except Exception:
                            pass

                    # Re-add logo to A1 to be safe (idempotent)
                    add_logo_if_exists(ws_new, 'A1')

                st.download_button("💾 Télécharger Pack Excel (Formateurs)", excel_to_bytes(wb_final), f"Pack_Formateurs_{selected_month}_{selected_semaine}.xlsx")

    # Tab2: Groupes
    with tab2:
        st.markdown('<div class="section-header">📚 Consultation / Export par Groupe</div>', unsafe_allow_html=True)
        selected_grp = st.selectbox("Sélectionner un groupe", parsed['groupes'], key="ui_grp")
        if selected_grp:
            df_grp = build_schedule_table_for_groupe(parsed['schedule'], selected_grp, selected_semaine, selected_month)
            st.dataframe(df_grp, use_container_width=True)
            heures_g = compute_hours_for_groupe(parsed['schedule'], selected_grp, selected_semaine, selected_month)
            st.metric("Heures (hors fériés)", f"{heures_g:.2f}h")
            if st.button("📥 Générer Excel (Groupe)"):
                wb = create_excel_groupe_semaine(selected_grp, parsed['schedule'], selected_semaine, selected_month)
                st.download_button("💾 Télécharger Excel", excel_to_bytes(wb), f"EDT_Groupe_{selected_grp}_{selected_month}_{selected_semaine}.xlsx")

        st.markdown("---")
        if st.button("📥 Générer Pack Excel (Tous les groupes)"):
            with st.spinner("Génération pack..."):
                wb_final = openpyxl.Workbook()
                wb_final.remove(wb_final.active)
                for groupe in parsed['groupes']:
                    wb_temp = create_excel_groupe_semaine(groupe, parsed['schedule'], selected_semaine, selected_month)
                    ws_temp = wb_temp.active
                    sheet_name = f"{groupe[:25]}_{selected_semaine}"
                    ws_new = wb_final.create_sheet(title=sheet_name)
                    ws_new.sheet_view.showGridLines = False

                    # ensure page setup is landscape on new sheet
                    ws_new.page_setup.orientation = ws_temp.page_setup.orientation
                    ws_new.page_setup.paperSize = ws_temp.page_setup.paperSize
                    ws_new.page_setup.fitToPage = True
                    ws_new.page_setup.fitToHeight = 1
                    ws_new.page_setup.fitToWidth = 1
                    ws_new.print_options.horizontalCentered = True
                    ws_new.print_options.verticalCentered = True

                    add_logo_if_exists(ws_new, 'A1')

                    for row_idx in range(1, ws_temp.max_row + 1):
                        for col_idx in range(1, ws_temp.max_column + 1):
                            cell = ws_temp.cell(row=row_idx, column=col_idx)
                            new_cell = ws_new.cell(row=row_idx, column=col_idx, value=cell.value)
                            if cell.has_style:
                                try:
                                    new_cell.font = copy.copy(cell.font)
                                    new_cell.fill = copy.copy(cell.fill)
                                    new_cell.border = copy.copy(cell.border)
                                    new_cell.alignment = copy.copy(cell.alignment)
                                except Exception:
                                    pass

                    for merged in ws_temp.merged_cells.ranges:
                        try:
                            ws_new.merge_cells(str(merged))
                        except Exception:
                            pass
                    for col_letter, col_dim in ws_temp.column_dimensions.items():
                        try:
                            ws_new.column_dimensions[col_letter].width = col_dim.width
                        except Exception:
                            pass
                    for rnum, rd in ws_temp.row_dimensions.items():
                        try:
                            ws_new.row_dimensions[rnum].height = rd.height
                        except Exception:
                            pass

                    add_logo_if_exists(ws_new, 'A1')

                st.download_button("💾 Télécharger Pack Excel (Groupes)", excel_to_bytes(wb_final), f"Pack_Groupes_{selected_month}_{selected_semaine}.xlsx")

    # Tab3: Salles & Conflits
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

    # Tab4: Salles libres synthèse
    with tab4:
        st.markdown('<div class="section-header">📊 Synthèse Salles Libres</div>', unsafe_allow_html=True)
        synth = []
        week_start = get_week_start_datetime(selected_month, selected_semaine)
        for jour in JOURS:
            for c in CRENEAUX_JOUR:
                key = f"{selected_semaine}-{jour}-{c}"
                holiday = False
                if week_start and is_holiday((week_start + timedelta(days=JOURS.index(jour))).date()):
                    holiday = True
                occ = set()
                if not holiday:
                    for f, fd in parsed['schedule'].items():
                        s = fd['slots'].get(key)
                        if s and s[0]:
                            occ.add(s[1].replace(' (CONFLIT NON RESOLU)','').replace(' (Conflit)',''))
                libres = sorted(list(set(parsed['salles']) - occ))
                synth.append({'Jour': jour, 'Créneau': c, 'Horaire': HORAIRES[c], 'Nb Salles Libres': len(libres), 'Salles Disponibles': ', '.join(libres) if libres else 'Aucune'})
        st.dataframe(pd.DataFrame(synth), use_container_width=True)

    # Tab5: Charge par groupe (REPLACED WITH Plotly DETAILED GRAPH FROM 23.py)
    with tab5:
        st.markdown('<div class="section-header">📈 Analyse de la Charge par Groupe</div>', unsafe_allow_html=True)
        st.info(f"📅 Analyse pour : **{selected_month} - {selected_semaine}**")

        # Calculer la masse horaire pour chaque groupe
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

            charge_groupes.append({
                'Groupe': groupe,
                'Heures de Formation': heures_total,
                'Nombre de Créneaux': nb_creneaux
            })

        df_charge = pd.DataFrame(charge_groupes).sort_values('Heures de Formation', ascending=False)

        if df_charge.empty:
            st.info("Aucune donnée de charge disponible pour la semaine sélectionnée.")
        else:
            # Calcul de la moyenne
            moyenne_heures = df_charge['Heures de Formation'].mean()

            # Métriques globales
            col_met1, col_met2, col_met3, col_met4 = st.columns(4)
            with col_met1:
                st.metric("Groupes Total", len(df_charge))
            with col_met2:
                st.metric("Charge Moyenne", f"{moyenne_heures:.1f}h")
            with col_met3:
                st.metric("Charge Minimale", f"{df_charge['Heures de Formation'].min():.1f}h")
            with col_met4:
                st.metric("Charge Maximale", f"{df_charge['Heures de Formation'].max():.1f}h")

            st.markdown("---")

            # Graphique en barres avec catégorisation basée sur la moyenne
            st.markdown("### 📊 Graphique de la Charge Horaire (par rapport à la moyenne)")

            import plotly.graph_objects as go

            # Créer le graphique avec des couleurs basées sur la moyenne
            colors = []
            seuil_bas = moyenne_heures * 0.85  # 15% en dessous de la moyenne
            seuil_haut = moyenne_heures * 1.15  # 15% au dessus de la moyenne

            for heures in df_charge['Heures de Formation']:
                if heures > seuil_haut:
                    colors.append('#d32f2f')  # Rouge: Au-dessus de la moyenne (Trop chargé)
                elif heures >= seuil_bas and heures <= seuil_haut:
                    colors.append('#fbc02d')  # Jaune: Proche de la moyenne (Chargé)
                else:
                    colors.append('#388e3c')  # Vert: En bas de la moyenne (Normal)

            fig = go.Figure(data=[
                go.Bar(
                    x=df_charge['Groupe'],
                    y=df_charge['Heures de Formation'],
                    text=df_charge['Heures de Formation'].apply(lambda x: f"{x:.1f}h"),
                    textposition='outside',
                    marker=dict(
                        color=colors,
                        line=dict(color='#1e5631', width=1.5)
                    ),
                    hovertemplate='<b>%{x}</b><br>Heures: %{y:.1f}h<br><extra></extra>'
                )
            ])

            # Ajouter une ligne pour la moyenne
            fig.add_hline(
                y=moyenne_heures,
                line_dash="dash",
                line_color="#1e5631",
                line_width=2,
                annotation_text=f"Moyenne: {moyenne_heures:.1f}h",
                annotation_position="right"
            )

            # Ajouter des lignes pour les seuils
            fig.add_hline(
                y=seuil_haut,
                line_dash="dot",
                line_color="#d32f2f",
                line_width=1,
                opacity=0.5
            )

            fig.add_hline(
                y=seuil_bas,
                line_dash="dot",
                line_color="#388e3c",
                line_width=1,
                opacity=0.5
            )

            fig.update_layout(
                title={
                    'text': f'Charge Horaire par Groupe - {selected_month} {selected_semaine}',
                    'x': 0.5,
                    'xanchor': 'center',
                    'font': {'size': 18, 'color': '#1e5631', 'family': 'Arial Black'}
                },
                xaxis_title='Groupes',
                yaxis_title='Heures de Formation',
                plot_bgcolor='white',
                paper_bgcolor='#f8faf9',
                height=500,
                showlegend=False,
                xaxis=dict(
                    tickangle=-45,
                    gridcolor='lightgray'
                ),
                yaxis=dict(
                    gridcolor='lightgray'
                )
            )

            st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")

            # Tableau détaillé avec catégorisation basée sur la moyenne
            st.markdown("### 📋 Détail de la Charge par Groupe")

            def categoriser_charge_moyenne(heures, moyenne, seuil_bas, seuil_haut):
                if heures > seuil_haut:
                    return "🔴 Trop Chargé"
                elif heures >= seuil_bas and heures <= seuil_haut:
                    return "🟡 Chargé"
                else:
                    return "🟢 Normal"

            df_charge['Catégorie'] = df_charge['Heures de Formation'].apply(
                lambda x: categoriser_charge_moyenne(x, moyenne_heures, seuil_bas, seuil_haut)
            )

            # Ajouter l'écart par rapport à la moyenne
            df_charge['Écart/Moyenne'] = df_charge['Heures de Formation'] - moyenne_heures
            df_charge['Écart/Moyenne'] = df_charge['Écart/Moyenne'].apply(lambda x: f"{x:+.1f}h")

            st.dataframe(
                df_charge,
                use_container_width=True
            )

            st.markdown("---")

            # Statistiques par catégorie
            st.markdown("### 📊 Répartition par Niveau de Charge (basée sur la moyenne)")

            st.info(f"""
            **Légende:**
            - 🔴 **Trop Chargé**: > {seuil_haut:.1f}h (au-dessus de +15% de la moyenne)
            - 🟡 **Chargé**: {seuil_bas:.1f}h - {seuil_haut:.1f}h (proche de la moyenne ±15%)
            - 🟢 **Normal**: < {seuil_bas:.1f}h (inférieur de -15% de la moyenne - Pas chargé)
            """)

            col_stat1, col_stat2, col_stat3 = st.columns(3)

            with col_stat1:
                nb_trop_charge = len(df_charge[df_charge['Heures de Formation'] > seuil_haut])
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: #d32f2f;">
                    <div class="metric-value">{nb_trop_charge}</div>
                    <div class="metric-label">🔴 Trop Chargés<br/>(Au-dessus moyenne)</div>
                </div>
                """, unsafe_allow_html=True)

            with col_stat2:
                nb_charge = len(df_charge[(df_charge['Heures de Formation'] >= seuil_bas) & (df_charge['Heures de Formation'] <= seuil_haut)])
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: #fbc02d;">
                    <div class="metric-value">{nb_charge}</div>
                    <div class="metric-label">🟡 Chargés<br/>(Proche moyenne)</div>
                </div>
                """, unsafe_allow_html=True)

            with col_stat3:
                nb_normal = len(df_charge[df_charge['Heures de Formation'] < seuil_bas])
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: #388e3c;">
                    <div class="metric-value">{nb_normal}</div>
                    <div class="metric-label">🟢 Normaux<br/>(En bas moyenne - Pas chargé)</div>
                </div>
                """, unsafe_allow_html=True)

            # Export Excel
            st.markdown("---")
            if st.button("📥 Exporter l'Analyse de Charge (Excel)", key="btn_export_charge"):
                wb_charge = openpyxl.Workbook()
                ws = wb_charge.active
                ws.title = "Charge_Groupes"
                ws.sheet_view.showGridLines = False

                border_thin = Border(left=Side(style='thin'), right=Side(style='thin'),
                                    top=Side(style='thin'), bottom=Side(style='thin'))
                header_font = Font(bold=True, size=11, color="FFFFFF")
                title_font = Font(bold=True, size=14, color="1e5631")
                header_fill = PatternFill(start_color="2d8659", end_color="2d8659", fill_type="solid")
                center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)

                # Titre
                ws['A1'] = f'ANALYSE DE CHARGE PAR GROUPE - {selected_month} {selected_semaine}'
                ws.merge_cells('A1:E1')
                ws['A1'].font = title_font
                ws['A1'].alignment = center_align
                ws.row_dimensions[1].height = 25

                # Info moyenne
                ws['A2'] = f'Moyenne: {moyenne_heures:.1f}h | Seuils: Normal < {seuil_bas:.1f}h | Chargé: {seuil_bas:.1f}h-{seuil_haut:.1f}h | Trop Chargé > {seuil_haut:.1f}h'
                ws.merge_cells('A2:E2')
                ws['A2'].alignment = center_align
                ws.row_dimensions[2].height = 20

                # En-têtes
                ws['A4'] = 'Groupe'
                ws['B4'] = 'Heures de Formation'
                ws['C4'] = 'Nombre de Créneaux'
                ws['D4'] = 'Niveau de Charge'
                ws['E4'] = 'Écart/Moyenne'

                for col in ['A', 'B', 'C', 'D', 'E']:
                    ws[f'{col}4'].font = header_font
                    ws[f'{col}4'].fill = header_fill
                    ws[f'{col}4'].border = border_thin
                    ws[f'{col}4'].alignment = center_align
                    ws.column_dimensions[col].width = 25

                # Données
                row = 5
                for _, data_row in df_charge.iterrows():
                    ws[f'A{row}'] = data_row['Groupe']
                    ws[f'B{row}'] = data_row['Heures de Formation']
                    ws[f'C{row}'] = data_row['Nombre de Créneaux']
                    ws[f'D{row}'] = data_row['Catégorie']
                    ws[f'E{row}'] = data_row['Écart/Moyenne']

                    for col in ['A', 'B', 'C', 'D', 'E']:
                        ws[f'{col}{row}'].border = border_thin
                        ws[f'{col}{row}'].alignment = center_align

                    row += 1

                excel_bytes = excel_to_bytes(wb_charge)
                st.download_button(
                    "💾 Télécharger l'Analyse",
                    excel_bytes,
                    f"Charge_Groupes_{selected_month}_{selected_semaine}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

# Footer
st.markdown("---")
st.markdown("<div style='text-align:center;color:#666;padding:1rem;'>Développé par ISMAILI ALAOUI Mohamed — CFP TLRA/IFMLT</div>", unsafe_allow_html=True)
