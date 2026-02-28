import streamlit as st
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup, NavigableString
import time
import re
import traceback
import json
import os
import math
import streamlit.components.v1 as components

CACHE_DIR = "race_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def load_race_cache(race_id, mode):
    cache_file = os.path.join(CACHE_DIR, f"{race_id}_{mode}.json")
    if os.path.exists(cache_file):
        if time.time() - os.path.getmtime(cache_file) < 3600:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
    return None

def save_race_cache(race_id, mode, data):
    cache_file = os.path.join(CACHE_DIR, f"{race_id}_{mode}.json")
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Cache save error:", e)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

KEIBA_ID = st.secrets.get("keibabook", {}).get("login_id", "")
KEIBA_PASS = st.secrets.get("keibabook", {}).get("password", "")
DIFY_API_KEY = st.secrets.get("DIFY_API_KEY", st.secrets.get("keibabook", {}).get("DIFY_API_KEY", ""))

BASE_URL = "https://s.keibabook.co.jp"

# 競馬ブック PLACEコード → netkeiba/Yahoo 競馬場コード (共通)
KEIBABOOK_TO_NETKEIBA_PLACE = {
    "08": "01", "09": "02", "06": "03", "07": "04", "04": "05",
    "05": "06", "02": "07", "00": "08", "01": "09", "03": "10",
}

# ==================================================
# 馬場バイアス評価データ
# ==================================================
BABA_BIAS_DATA = {
    "中山ダート1200": {5: [6, 7, 8], 2: [5]},
    "中京ダート1400": {5: [6, 7, 8], 2: [3, 5]},
    "京都ダート1200": {5: [6, 7, 8]},
    "中山芝1200": {5: [1, 2, 3]},
    "阪神芝1600": {5: [1, 2, 3]},
    "阪神芝1400": {5: [1, 2, 3]},
    "阪神芝1200": {5: [1, 2, 3], 2: [4]},
    "函館芝1800": {5: [1, 2, 3]},
    "東京芝2000": {5: [5], 2: [1]},
    "新潟芝1000": {5: [7, 8], 3: [6]},
    "東京ダート1600": {5: [6, 8], 3: [7], 2: [5]},
    "東京芝1600": {5: [6, 8]},
    "札幌ダート1000": {5: [7, 8]},
    "阪神ダート1400": {5: [8], 3: [4, 6], 2: [4, 6]},
    "東京芝1400": {5: [8]},
    "京都芝1600内": {5: [6]},
    "中山ダート1800": {5: [7, 8], 2: [4, 5]},
    "中山芝2500": {5: [5], 3: [6, 8]},
    "中京芝1200": {5: [2, 3], 3: [1], 2: [4, 5]},
    "京都ダート1800": {5: [6]},
    "京都ダート1900": {5: [3]},
    "京都芝1200": {5: [7]},
    "京都芝2400": {5: [2, 4]},
    "小倉芝1200": {5: [7], 3: [8], 2: [6]},
    "新潟ダート1200": {5: [6, 7], 2: [4, 8]},
    "新潟芝1600": {5: [5, 7]},
    "東京ダート1400": {5: [6, 7], 3: [4, 8]},
    "阪神ダート1800": {5: [6, 7]},
    "阪神ダート1200": {5: [8], 3: [5, 6, 7], 2: [4]},
    "中京ダート1200": {3: [1, 6]},
    "中山芝1600": {5: [1], 3: [2, 3, 4]},
    "中京芝1400": {5: [3], 3: [1, 4]},
    "東京芝2400": {3: [1, 3]},
    "阪神芝1800": {5: [1, 3], 3: [2, 4]},
    "函館芝2000": {5: [2], 3: [1, 5], 2: [4, 6]},
    "札幌芝2000": {5: [1, 5], 3: [2, 3]},
    "札幌芝1200": {3: [1, 8], 2: [6, 7]},
}

# ==================================================
# ユーティリティ
# ==================================================
def _clean_text_ja(s: str) -> str:
    if not s: return ""
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _is_missing_marker(s: str) -> bool:
    t = _clean_text_ja(s)
    return t in {"－", "-", "—", "―", "‐", ""}

def _safe_int(s, default=0) -> int:
    try:
        if s is None: return default
        if isinstance(s, (int, float)): return int(s)
        ss = str(s).strip()
        ss = re.sub(r"[^0-9\-]", "", ss)
        if ss in {"", "-", "－"}: return default
        return int(ss)
    except: return default

def extract_distance_int(dist_str: str) -> int:
    match = re.search(r'(\d{3,4})', str(dist_str))
    if match: return int(match.group(1))
    return 0

def parse_dify_evaluation(ai_text: str) -> dict:
    """ DifyのMarkdownテーブルから {馬名: 評価ランク} の辞書を作成 """
    eval_map = {}
    for line in ai_text.split('\n'):
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) >= 3:
            name_cell = cells[1].replace('**', '').strip()
            name = re.sub(r'[(（].*?[)）]', '', name_cell).strip()
            grade_cell = cells[2].replace('**', '').strip()
            if grade_cell in ["S", "A", "B", "C", "D", "E", "F", "G"]:
                eval_map[name] = grade_cell
    return eval_map

def format_dify_md_to_html(md_text: str) -> str:
    import re
    import html
    
    def repl_rank(m):
        rank = m.group(1)
        colors = {"S": "linear-gradient(135deg, #FFD700, #FFA500)", "A": "#FF69B4", "B": "#FF0000", "C": "#FFA500", "D": "#8B4513", "E": "#808080", "F": "#34495e"}
        bg = colors.get(rank, "#7f8c8d")
        return f"<span style='background: {bg}; color: white; padding: 2px 10px; border-radius: 12px; font-weight: bold; font-size: 0.9em; display: inline-block; text-align: center; min-width: 20px;'>{rank}</span>"
        
    def safe_html(text):
        return html.escape(text).replace('&lt;br&gt;', '<br>').replace('&lt;br/&gt;', '<br/>').replace('&lt;br /&gt;', '<br/>')

    lines = md_text.split('\n')
    html_lines = ["<div style='font-family: inherit;'>"]
    
    in_table = False
    in_blockquote = False
    
    for line in lines:
        stripped = line.strip()
        
        # 水平線
        if stripped == '---':
            if in_blockquote:
                html_lines.append("</div>")
                in_blockquote = False
            html_lines.append("<hr style='border: 0; height: 1px; background-image: linear-gradient(to right, rgba(0,0,0,0), rgba(0,0,0,0.15), rgba(0,0,0,0)); margin: 25px 0;'>")
            continue
            
        # Blockquote (引用) - 各馬詳細カードとして扱う
        if stripped.startswith('>'):
            if not in_blockquote:
                html_lines.append("<div style='background-color: #f8fafc; border-left: 4px solid #3b82f6; padding: 12px 16px; margin: 0 0 20px 0; border-radius: 0 8px 8px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); color: #334155;'>")
                in_blockquote = True
            
            content = stripped[1:].strip()
            if not content:
                html_lines.append("<div style='height: 8px;'></div>")
                continue
                
            content = safe_html(content)
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong style="color: #0f172a;">\1</strong>', content)
            html_lines.append(f"<div style='margin-bottom: 6px; line-height: 1.6; font-size: 0.95em;'>{content}</div>")
            continue
        else:
            if in_blockquote:
                html_lines.append("</div>")
                in_blockquote = False

        # Table
        if stripped.startswith('|'):
            if not in_table:
                # Add sorting buttons before the table
                html_lines.append("""
                <div style='margin: 15px 0 5px 0; text-align: right;'>
                    <button onclick='sortAiTable(0)' style='margin-right: 5px; padding: 4px 8px; font-size: 0.8em; border: 1px solid #cbd5e1; border-radius: 4px; background: #fff; cursor: pointer; color: #475569;'>↕️ 馬番で並び替え</button>
                    <button onclick='sortAiTable(2)' style='padding: 4px 8px; font-size: 0.8em; border: 1px solid #cbd5e1; border-radius: 4px; background: #fff; cursor: pointer; color: #475569;'>↕️ 評価順で並び替え</button>
                </div>
                """)
                html_lines.append("<div style='overflow-x: auto; margin: 0 0 25px 0;'><table id='ai-eval-table' style='width: 100%; border-collapse: collapse; font-size: 0.9em; box-shadow: 0 1px 3px rgba(0,0,0,0.05); min-width: 400px;'>")
                in_table = True
            
            if '|---' in stripped or '|:-' in stripped:
                continue
                
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            is_th = ("<table" in html_lines[-1])
            
            tr_bg = "#ffffff" if len(html_lines) % 2 == 0 else "#f8fafc"
            tr_style = f"background-color: {tr_bg}; border-bottom: 1px solid #e2e8f0;"
            if is_th:
                tr_style = "background-color: #f1f5f9; border-bottom: 2px solid #cbd5e1;"
                
            html_lines.append(f"<tr style='{tr_style}'>")
            
            for i, cell in enumerate(cells):
                cell = safe_html(cell)
                cell = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', cell)
                
                # Extract clean rank for data attribute before adding span tags
                raw_rank = cell
                if i == 2: # 評価列
                    if re.match(r'^[SABCDEFGH]$', raw_rank) or re.match(r'^<strong>[SABCDEFGH]</strong>$', raw_rank):
                        raw_rank = raw_rank.replace('<strong>', '').replace('</strong>', '')
                    else:
                        raw_rank = "Z" # Fallback for sorting
                        
                    cell = re.sub(r'<strong>([SABCDEFGH])</strong>', repl_rank, cell)
                    cell = re.sub(r'^([SABCDEFGH])$', repl_rank, cell)
                    
                tag = "th" if is_th else "td"
                
                if is_th:
                    style = "padding: 12px 10px; text-align: left; color: #334155; font-weight: bold; white-space: nowrap;"
                    html_lines.append(f"<{tag} style='{style}'>{cell}</{tag}>")
                else:
                    style = "padding: 10px; color: #475569; vertical-align: middle;"
                    if i in [0, 2]:
                        style += " text-align: center;"
                    if i == 3:
                        style += " text-align: left;"
                    
                    # Add data attributes to cells for easier sorting
                    attr = ""
                    if i == 0: # Uma-ban
                        try:
                            num = int(re.sub(r'\D', '', cell))
                            attr = f" data-sort-val='{num}'"
                        except:
                            attr = " data-sort-val='999'"
                    elif i == 2: # Rank
                        rank_order = {"S": 1, "A": 2, "B": 3, "C": 4, "D": 5, "E": 6, "F": 7, "G": 8, "H": 9}
                        order = rank_order.get(raw_rank, 99)
                        attr = f" data-sort-val='{order}'"
                        
                    html_lines.append(f"<{tag} style='{style}'{attr}>{cell}</{tag}>")
            html_lines.append("</tr>")
            continue
        else:
            if in_table:
                html_lines.append("</table></div>")
                in_table = False

        # Headers
        if stripped.startswith('### '):
            text = stripped[4:].strip()
            text = safe_html(text)
            if '【評価:' in text:
                text = re.sub(r'【評価:\s*([SABCDEFGH])】', lambda m: f"<span style='display: inline-block; margin-left: auto; font-size: 0.85em; background: rgba(255,255,255,0.2); padding: 2px 8px; border-radius: 12px;'>評価: {repl_rank(m)}</span>", text)
            
            html_lines.append(f"<h4 style='background: linear-gradient(90deg, #1e293b, #334155); color: #f8fafc; padding: 10px 14px; border-radius: 6px; margin: 25px 0 10px 0; font-size: 1.05em; display: flex; align-items: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>{text}</h4>")
            continue
            
        elif stripped.startswith('## '):
            text = stripped[3:].strip()
            text = safe_html(text)
            html_lines.append(f"<h3 style='color: #0f172a; border-left: 5px solid #3b82f6; padding-left: 10px; margin: 30px 0 15px 0; font-size: 1.25em;'>{text}</h3>")
            continue
            
        elif stripped.startswith('# '):
            text = stripped[2:].strip()
            text = safe_html(text)
            html_lines.append(f"<h2 style='color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin: 20px 0 15px 0; font-size: 1.4em; font-weight: bold;'>{text}</h2>")
            continue
            
        # Normal text
        if stripped:
            stripped = safe_html(stripped)
            stripped = re.sub(r'\*\*(.*?)\*\*', r'<strong style="color: #1e293b;">\1</strong>', stripped)
            html_lines.append(f"<p style='margin: 0 0 8px 0; color: #475569; line-height: 1.6;'>{stripped}</p>")
        else:
            html_lines.append("<div style='height: 8px;'></div>")
            
    if in_table:
        html_lines.append("</table></div>")
    if in_blockquote:
        html_lines.append("</div>")
        
    html_lines.append("</div>")
    return "\n".join(html_lines)

def render_copy_button(text: str, label: str, dom_id: str):
    safe_text = json.dumps(text)
    html = f"""
    <div style="margin:5px 0;">
    <button onclick="copyToClipboard_{dom_id}()" 
            style="padding:6px 12px; background:#4CAF50; color:white; border:none; 
                   border-radius:4px; cursor:pointer; font-size:12px;">
        {label}
    </button>
    </div>
    <script>
    function copyToClipboard_{dom_id}() {{
        const text = {safe_text};
        navigator.clipboard.writeText(text).then(() => {{
        }}).catch(err => {{
        }});
    }}
    </script>
    """
    components.html(html, height=40)



# JRA全10場
JRA_VENUES = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]

# ==========================================
# 1. ペース解析・展開予想のコアロジック
# ==========================================

def calculate_early_pace_speed(row, current_dist):
    if pd.isna(row.get('early_3f')):
        return np.nan
    
    raw_speed = 600.0 / row['early_3f']
    
    # 地方競馬のテン時計割引（過剰にならないよう -0.3 に調整）
    if row['venue'] not in JRA_VENUES:
        raw_speed -= 0.3

    condition_mod = 0.0
    if row['track_type'] == "芝":
        if row['track_condition'] in ["重", "不良"]: condition_mod = +0.15 
        elif row['track_condition'] == "稍": condition_mod = +0.05
    elif row['track_type'] == "ダート":
        if row['track_condition'] in ["重", "不良"]: condition_mod = -0.15 
        elif row['track_condition'] == "稍": condition_mod = -0.05

    course_mod = 0.0
    turf_start_dirt = [("東京", 1600), ("中山", 1200), ("阪神", 1400), ("京都", 1400), ("新潟", 1200), ("中京", 1400)]
    if row['track_type'] == "ダート" and (row['venue'], row['distance']) in turf_start_dirt:
        course_mod += -0.15
        
    uphill_starts = [("中山", 2000, "芝"), ("阪神", 2000, "芝"), ("中京", 2000, "芝")]
    if (row['venue'], row['distance'], row['track_type']) in uphill_starts:
        course_mod += +0.15

    downhill_starts = [("京都", 1400, "芝"), ("京都", 1600, "芝"), ("新潟", 1000, "芝")]
    if (row['venue'], row['distance'], row['track_type']) in downhill_starts:
        course_mod += -0.15

    # 距離バイアスの「隠し味化」（極端な補正を緩和）
    dist_diff = row['distance'] - current_dist
    distance_mod = 0.0
    if dist_diff > 0:
        # 距離短縮: 追走苦労のマイナス補正をマイルドに (-0.05)
        distance_mod = -(dist_diff / 100.0) * 0.05
    elif dist_diff < 0:
        # 距離延長: スピードの過大評価を防ぐ補正をマイルドに (-0.10)
        distance_mod = -(abs(dist_diff) / 100.0) * 0.10

    return raw_speed + condition_mod + course_mod + distance_mod

def determine_running_style(past_df: pd.DataFrame) -> str:
    if past_df.empty: return "不明"
    
    is_good_run = (past_df['finish_position'] <= 3) | ((past_df['popularity'] > past_df['finish_position']) & (past_df['finish_position'] <= 5))
    good_runs = past_df[is_good_run]
    
    if good_runs.empty: return "不明"
        
    good_positions = good_runs['first_corner_pos'].tolist()
    
    if all(pos == 1 for pos in good_positions):
        return "ハナ絶対"
        
    if any(2 <= pos <= 5 for pos in good_positions):
        return "控えOK"
        
    return "差し追込"

def extract_jockey_target_position(past_races_df: pd.DataFrame, current_venue: str) -> float:
    if past_races_df.empty: return 9.5 
    
    is_success = (past_races_df['finish_position'] <= 3) | (past_races_df['popularity'] > past_races_df['finish_position'])
    is_same_venue = past_races_df['venue'] == current_venue
    
    # Use the most recent successful race (last in chronological order)
    venue_success_races = past_races_df[is_success & is_same_venue]
    if not venue_success_races.empty:
        return float(venue_success_races.iloc[-1]['first_corner_pos'])
    
    success_races = past_races_df[is_success]
    if not success_races.empty:
        return float(success_races.iloc[-1]['first_corner_pos'])
        
    # Weight recent races more in the fallback mean calculation
    weights = [i + 1 for i in range(len(past_races_df))]
    weighted_mean = (past_races_df['first_corner_pos'] * weights).sum() / sum(weights)
    return float(weighted_mean)

def calculate_pace_score(horse, current_dist, current_venue, current_track, total_horses):
    past_df = pd.DataFrame(horse['past_races'])
    
    if past_df.empty: 
        horse['condition_mod'] = 0.0
        horse['special_flag'] = "❓データ不足"
        horse['max_early_speed'] = 16.0
        horse['running_style'] = "不明"
        return 10.0 + ((horse['horse_number'] - 1) * 0.05) 
    
    horse['running_style'] = determine_running_style(past_df)
    
    past_df['early_speed'] = past_df.apply(lambda row: calculate_early_pace_speed(row, current_dist), axis=1)
    max_speed = past_df['early_speed'].max()
    horse['max_early_speed'] = max_speed if not pd.isna(max_speed) else 16.0
    
    speed_multiplier = 4.0 if (current_track == "ダート" and current_dist <= 1400) else 3.0
    speed_advantage = 0.0
    if not pd.isna(max_speed):
        speed_advantage = (16.8 - max_speed) * speed_multiplier 

    jockey_target = extract_jockey_target_position(past_df, current_venue)
    
    # Check for running style change after a long layoff (>90 days)
    if len(past_df) >= 2:
        last_race = past_df.iloc[-1]
        prev_race = past_df.iloc[-2]
        if pd.notna(last_race.get('date')) and pd.notna(prev_race.get('date')):
            days_gap = (last_race['date'] - prev_race['date']).days
            
            if days_gap >= 90:
                recent_pos = last_race['first_corner_pos']
                old_avg_pos = past_df.iloc[:-1]['first_corner_pos'].mean()
                
                # Drastic change in position supported by early speed
                if recent_pos <= 3 and old_avg_pos >= 5.0 and last_race['early_3f'] > 0:
                    raw_speed = 600.0 / last_race['early_3f']
                    if raw_speed >= 16.0:  # Fast enough early speed
                        horse['running_style'] = "ハナ絶対" if recent_pos == 1 else ("控えOK" if horse['running_style'] != "ハナ絶対" else horse['running_style'])
                        horse['special_flag'] = "🔄休養明け脚質転換"
                        jockey_target = float(recent_pos)  # Overwrite target position

    base_position = (jockey_target * 0.6) + speed_advantage
    
    # Use the most recent race for weight modifier
    last_race = past_df.iloc[-1]
    weight_modifier = (horse['current_weight'] - last_race['weight']) * 0.25
    
    base_mod = (horse['horse_number'] - 1) * 0.05 
    outside_adv_courses = [("中山", 1200, "ダート"), ("東京", 1600, "ダート"), ("阪神", 1400, "ダート"), ("京都", 1400, "ダート")]
    if (current_venue, current_dist, current_track) in outside_adv_courses:
        base_mod = (total_horses - horse['horse_number']) * 0.02 - 0.15

    late_start_penalty = 0.0
    
    # 前走地方競馬ペナルティ（+2.5 → +1.0へ緩和）
    if last_race['venue'] not in JRA_VENUES:
        late_start_penalty += 1.0
        prefix = horse.get('special_flag', '') + " " if horse.get('special_flag', '') else ""
        horse['special_flag'] = (prefix + "⚠️前走地方").strip()

    # 距離延長（過剰なペナルティを撤廃し、+0.5の微調整に）
    if last_race['distance'] < current_dist and horse['running_style'] != "ハナ絶対":
        late_start_penalty += 0.5
        prefix = horse['special_flag'] + " " if horse['special_flag'] else ""
        horse['special_flag'] = (prefix + "🐎距離延長(控える可能性)").strip()

    # 距離短縮（過剰なペナルティを撤廃し、+0.3の微調整に）
    if last_race['distance'] > current_dist:
        late_start_penalty += 0.3
        prefix = horse['special_flag'] + " " if horse['special_flag'] else ""
        horse['special_flag'] = (prefix + "🐢距離短縮(追走注意)").strip()

    if last_race.get('is_late_start', False):
        late_start_penalty += 1.0 
        if last_race['first_corner_pos'] <= 5:
            is_past_outside = last_race['past_frame'] >= 5
            is_current_inside = horse['horse_number'] <= (total_horses / 2) 
            
            if is_past_outside and is_current_inside:
                late_start_penalty += 1.5
                prefix = horse['special_flag'] + " " if horse['special_flag'] else ""
                horse['special_flag'] = (prefix + "⚠️内枠包まれ懸念").strip()
            elif is_past_outside and not is_current_inside:
                late_start_penalty -= 0.5
                prefix = horse['special_flag'] + " " if horse['special_flag'] else ""
                horse['special_flag'] = (prefix + "🐎外枠リカバー警戒").strip()

    # 外枠（外から5頭くらい）の様子見・控えるロジック
    is_outer_5 = horse['horse_number'] > (total_horses - 5)
    weight_diff = horse['current_weight'] - last_race['weight']
    
    # 馬体重が2kg以上減っていない（= 大幅減量で勝負気配、ではない）かつ、絶対に逃げたい馬ではない場合
    if is_outer_5 and weight_diff > -2.0 and horse['running_style'] != "ハナ絶対":
        late_start_penalty += 0.7  # 様子見で位置を下げるペナルティ加算
        prefix = horse['special_flag'] + " " if horse['special_flag'] else ""
        horse['special_flag'] = (prefix + "👁️外枠様子見(控える)").strip()

    final_score = base_position + weight_modifier + base_mod + late_start_penalty
    return max(1.0, min(18.0, final_score))

def apply_give_up_synergy(horses, current_venue, current_dist, current_track):
    outside_adv_courses = [("中山", 1200, "ダート"), ("東京", 1600, "ダート"), ("阪神", 1400, "ダート"), ("京都", 1400, "ダート")]
    is_outside_adv = (current_venue, current_dist, current_track) in outside_adv_courses

    for h in horses:
        if h.get('running_style') == "ハナ絶対":
            give_up = False
            for other in horses:
                if other['horse_number'] == h['horse_number']: continue
                diff = h['score'] - other['score']
                
                if diff >= 1.0:
                    give_up = True
                    break
                
                if 0 <= diff < 1.0:
                    if is_outside_adv:
                        if other['horse_number'] > h['horse_number']:
                            give_up = True
                            break
                    else:
                        if other['horse_number'] < h['horse_number']:
                            give_up = True
                            break
                    
            if give_up:
                penalty = 1.0 if (is_outside_adv and h['horse_number'] >= len(horses)/2) else 1.5
                h['score'] += penalty 
                prefix = h['special_flag'] + " " if h['special_flag'] else ""
                h['special_flag'] = (prefix + "📉枠差・控える可能性").strip()
                h['running_style'] = "先行（控える）" 
                
    return horses

def format_formation(sorted_horses):
    if not sorted_horses: return ""
    leaders, chasers, mid, backs = [], [], [], []
    top_score = sorted_horses[0]['score']
    for h in sorted_horses:
        num_str = chr(9311 + h['horse_number']) 
        score = h['score']
        if score <= top_score + 1.2 and len(leaders) < 3: leaders.append(num_str)
        elif score <= top_score + 4.5: chasers.append(num_str)
        elif score <= top_score + 9.5: mid.append(num_str)
        else: backs.append(num_str)
    
    parts = []
    if leaders: parts.append(f"({''.join(leaders)})")
    if chasers: parts.append("".join(chasers))
    if mid: parts.append("".join(mid))
    if backs: parts.append("".join(backs))
    return " ".join(parts)

def generate_pace_and_spread_comment(sorted_horses, current_track):
    if len(sorted_horses) < 3: return "データ不足"
    
    top_score = sorted_horses[0]['score']
    leaders = [h for h in sorted_horses if h['score'] <= top_score + 1.2][:3]
    leader_nums = "、".join([chr(9311 + h['horse_number']) for h in leaders])
    
    # Runaway risk check: Is the 1st horse significantly far ahead of the 2nd?
    second_score = sorted_horses[1]['score']
    runaway_gap = second_score - top_score
    runaway_warning = ""
    if runaway_gap >= 1.5:
        runaway_horse_num = chr(9311 + sorted_horses[0]['horse_number'])
        runaway_warning = f"\n\n🚨 **逃げ残り注意**\n{runaway_horse_num}が単騎で思い切って逃げた場合、後続を引き離したままそのまま押し切るリスクがあります。"
    
    mid_idx = min(len(sorted_horses)-1, int(len(sorted_horses) * 0.6))
    spread_gap = sorted_horses[mid_idx]['score'] - top_score
    
    if spread_gap >= 5.0:
        spread_text = "隊列は【縦長】"
        spread_reason = "テンが速い馬と遅い馬のスピード差が激しく、ばらけた展開になりそうです。"
    elif spread_gap <= 2.5:
        spread_text = "馬群は【一団】"
        spread_reason = "各馬の前半スピードが拮抗しており、密集した塊のまま進む展開が濃厚です。コース取りの差が出やすくなります。"
    else:
        spread_text = "【標準的な隊列】"
        spread_reason = "極端にばらけることもなく、標準的なペース配分になりそうです。"
        
    top3_speeds = [h.get('max_early_speed', 16.1) for h in leaders]
    avg_top_speed = sum(top3_speeds) / len(top3_speeds) if top3_speeds else 16.1
    high_pace_threshold = 16.7 if current_track == "芝" else 16.5
    slow_pace_threshold = 16.3 if current_track == "芝" else 16.1

    must_lead_count = sum(1 for h in leaders if h.get('running_style') == "ハナ絶対")
    can_wait_count = sum(1 for h in leaders if h.get('running_style') == "控えOK")

    if must_lead_count >= 2 and avg_top_speed >= high_pace_threshold:
        base_cmt = f"🔥 ハイペース必至\n「何がなんでも逃げたい」馬が複数おり、{leader_nums}の激しい先行争いでテンは速くなりそうです。"
    elif must_lead_count >= 2:
        base_cmt = f"🏃 乱ペース想定\n絶対的なスピードは平凡ですが、{leader_nums}が意地でもハナを主張し合い、競り合いによる消耗戦になりそうです。"
    elif must_lead_count == 1 and avg_top_speed >= high_pace_threshold:
        base_cmt = f"🏃 ややハイペース想定\n逃げ主張馬がペースを作り、{leader_nums}が引っ張る淀みない流れになりそうです。"
    elif must_lead_count == 0 and can_wait_count >= 2:
        base_cmt = f"🚶 ややスローペース想定\n{leader_nums}が前に行きますが、「控えても結果を出せる」馬たちなので互いに牽制し合い、ペースは落ち着きそうです。"
    elif avg_top_speed < slow_pace_threshold:
        base_cmt = f"🐢 スローペース想定\n全体的にテンのダッシュ力が控えめで、{leader_nums}が楽に主導権を握る展開。後続は折り合い重視になりそうです。"
    else:
        if spread_gap >= 5.0:
            base_cmt = f"🏃 前が引っ張るペース想定\n前に行く{leader_nums}と後続との間に差が開きやすく、平均よりやや締まった展開になりそうです。"
        else:
            base_cmt = f"🐎 平均ペース想定\n{leader_nums}が並んで先行しますが、無理のない標準的なペース配分になりそうです。"

    final_cmt = f"**{spread_text}**\n{spread_reason}\n\n**{base_cmt}**{runaway_warning}"
    return final_cmt


# ==========================================
# 厩舎話・コメントによる展開スコア微調整ロジック
# ==========================================
def adjust_score_by_danwa(danwa: str, horse_score: float, horse_flag: str, running_style: str):
    if not danwa:
        return horse_score, horse_flag, running_style
        
    danwa_check = danwa.replace(" ", "").replace("　", "")
    
    # Extract context snippet from original text
    def get_context(match_word: str, text: str, pre=8, post=15):
        idx = text.find(match_word)
        if idx == -1: return ""
        start = max(0, idx - pre)
        end = min(len(text), idx + len(match_word) + post)
        snippet = text[start:end]
        if start > 0: snippet = "…" + snippet
        if end < len(text): snippet = snippet + "…"
        return snippet.replace("\n", "").replace("\r", "")

    # 前方への意図
    front_intent = ["ハナ", "逃げ", "前へ", "先行", "前進気勢", "前につけ", "積極的に", "主導権", "外目に付けて", "外目につけて"]
    # 後方への意図
    back_intent = ["控える", "砂被り", "砂を被", "じっくり", "末脚", "折り合い", "溜める", "タメて", "後ろから", "番手", "後方", "脚をタメる"]
    
    # 特別条件: 芝→ダや初ダートで極端な競馬
    extreme_intent = ["初ダート", "芝からダート"]
    is_extreme = any(w in danwa_check for w in extreme_intent)
    
    front_match = [w for w in front_intent if w in danwa_check]
    back_match = [w for w in back_intent if w in danwa_check]
    
    if is_extreme:
        if running_style in ["ハナ絶対", "控えOK"] or front_match:
            horse_score -= 1.5
            horse_flag = (horse_flag + " 🗣️厩舎:[初ダート前目]").strip()
            running_style = "ハナ絶対"
        else:
            horse_score += 1.5
            horse_flag = (horse_flag + " 🗣️厩舎:[初ダート砂被り嫌気]").strip()
            running_style = "差し追込"
    else:
        if front_match and not back_match:
            horse_score -= 1.0
            word = front_match[0]
            ctx = get_context(word, danwa)
            horse_flag = (horse_flag + f" 🗣️厩舎:[{word}]「{ctx}」").strip()
            if running_style != "ハナ絶対" and ("ハナ" in front_match or "逃げ" in front_match):
                running_style = "ハナ絶対"
        elif back_match:
            horse_score += 1.0
            word = back_match[0]
            ctx = get_context(word, danwa)
            horse_flag = (horse_flag + f" 🗣️厩舎:[{word}]控「{ctx}」").strip()
            if running_style == "ハナ絶対" and ("控える" in back_match or "番手" in back_match):
                running_style = "先行（控える）"
            
    return horse_score, horse_flag, running_style


def compute_speed_metrics(cpu_data: dict) -> dict:
    # 重み設定 (合計 10.0)
    W_RECENT_MAX = 4.0  # 近3走のMAX
    W_LAST = 3.0        # 前走
    W_BEST = 2.0        # 自己ベスト
    W_AVG = 1.0         # 平均

    raw_scores = {}

    for umaban, d in cpu_data.items():
        # 1. データの取り出し
        val_last = _safe_int(d.get("sp_last"), 0)
        val_2 = _safe_int(d.get("sp_2"), 0)
        val_3 = _safe_int(d.get("sp_3"), 0)
        val_best = _safe_int(d.get("sp_best"), 0)

        # 有効な近走スコア (0より大きいもの)
        recent_valid = [v for v in [val_last, val_2, val_3] if v > 0]

        # データが全くない場合はスキップ
        if not recent_valid and val_best == 0:
            continue

        # 2. 各指標の算出
        # 近3走MAX
        recent_max = max(recent_valid) if recent_valid else val_best
        # 近3走平均
        recent_avg = sum(recent_valid) / len(recent_valid) if recent_valid else val_best
        # 前走 (データ欠けの場合は平均で補完)
        last_score = val_last if val_last > 0 else recent_avg
        # 自己ベスト (データ欠けの場合は近3走MAXで代用)
        lifetime_best = val_best if val_best > 0 else recent_max

        # ★重要補正: 「最高」が古すぎる場合のリスクヘッジ
        # 「自己ベスト」が「近3走MAX」より異常に高い(15以上乖離)場合、
        # 過去の栄光である可能性が高いため、評価を割り引く
        if lifetime_best > recent_max + 15:
            lifetime_best = (lifetime_best + recent_max) / 2

        # 3. 加重平均の計算
        numerator = (
            (recent_max * W_RECENT_MAX) +
            (last_score * W_LAST) +
            (lifetime_best * W_BEST) +
            (recent_avg * W_AVG)
        )
        denominator = W_RECENT_MAX + W_LAST + W_BEST + W_AVG
        
        raw_score = numerator / denominator
        
        # ボーナス加点: 「上昇気配」
        # (3走前 < 2走前 < 前走) と右肩上がりの場合、2%ボーナス
        if (val_last > val_2 > val_3 > 0):
            raw_score *= 1.02

        raw_scores[umaban] = raw_score

    if not raw_scores:
        return {}

    # 4. 相対評価 (レース内トップを35点満点とする)
    max_raw = max(raw_scores.values())
    out = {}
    for umaban, raw in raw_scores.items():
        score_35 = (raw / max_raw) * 35.0 if max_raw > 0 else 0.0
        out[umaban] = {"raw_ability": round(raw, 2), "speed_index": round(score_35, 1)}
    
    return out

def extract_race_info(race_title: str) -> dict:
    result = {"place": None, "distance": None, "track_type": None, "day": None, "course_variant": ""}
    p_match = re.search(r'(\d+)回([^0-9]+?)(\d+)日目', race_title)
    if p_match:
        result["place"] = p_match.group(2).strip()
        result["day"] = int(p_match.group(3))
    d_match = re.search(r'(\d{3,4})m', race_title)
    if d_match: result["distance"] = d_match.group(1)
    if 'ダート' in race_title: result["track_type"] = "dirt"
    elif '芝' in race_title: result["track_type"] = "turf"
    if '内' in race_title: result["course_variant"] = "内"
    elif '外' in race_title: result["course_variant"] = "外"
    return result

def calculate_baba_bias(waku: int, race_title: str) -> dict:
    kaisai_bias, course_bias = 0, 0
    info = extract_race_info(race_title)
    if info["track_type"] == "turf" and info["day"] in [1, 2]:
        if waku == 1: kaisai_bias = 5
        elif waku == 2: kaisai_bias = 3
        elif waku == 3: kaisai_bias = 2
    if info["place"] and info["distance"] and info["track_type"]:
        track_str = "芝" if info["track_type"] == "turf" else "ダート"
        course_key = f"{info['place']}{track_str}{info['distance']}{info['course_variant']}"
        if course_key in BABA_BIAS_DATA:
            bias_data = BABA_BIAS_DATA[course_key]
            for points in [5, 3, 2]:
                if points in bias_data and waku in bias_data[points]:
                    course_bias = points; break
    return {"kaisai_bias": kaisai_bias, "course_bias": course_bias, "total": kaisai_bias + course_bias}

# ==================================================
# Selenium Setup
# ==================================================
def build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,2200")
    options.page_load_strategy = 'eager'
    options.add_argument("--lang=ja-JP")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30) 
    return driver

def login_keibabook(driver: webdriver.Chrome) -> None:
    if not KEIBA_ID or not KEIBA_PASS: return
    driver.get(f"{BASE_URL}/login/login")
    try:
        WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.NAME, "login_id"))).send_keys(KEIBA_ID)
        WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='password']"))).send_keys(KEIBA_PASS)
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='submit'], .btn-login"))).click()
        time.sleep(1.0)
    except: pass

# ==================================================
# スクレイピング関数の各機能
# ==================================================
def fetch_keibabook_danwa(driver, race_id: str):
    url = f"{BASE_URL}/cyuou/danwa/0/{race_id}"
    driver.get(url)
    try: WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.default.danwa")))
    except: pass
    soup = BeautifulSoup(driver.page_source, "html.parser")
    racetitle = soup.find("div", class_="racetitle")
    header_info = {"header_text": "\n".join([p.get_text(strip=True) for p in racetitle.find_all("p")]) if racetitle else ""}
    table = soup.find("table", class_=lambda c: c and "danwa" in str(c))
    horses = {}
    if table and table.tbody:
        current_umaban, current_waku = None, None
        for tr in table.tbody.find_all("tr", recursive=False):
            if "spacer" in tr.get("class", []): continue
            waku_td, umaban_td, bamei_td = tr.find("td", class_="waku"), tr.find("td", class_="umaban"), tr.find("td", class_="left")
            if waku_td and umaban_td and bamei_td:
                waku_p = waku_td.find("p")
                if waku_p:
                    for cls in waku_p.get("class", []):
                        if cls.startswith("waku"): current_waku = re.sub(r"\D", "", cls); break
                current_umaban = re.sub(r"\D", "", umaban_td.get_text(strip=True))
                horses[current_umaban] = {"name": _clean_text_ja(bamei_td.get_text(strip=True)), "waku": current_waku or "?", "danwa": ""}
                continue
            danwa_td = tr.find("td", class_="danwa")
            if danwa_td and current_umaban:
                txt = _clean_text_ja(danwa_td.get_text("\n", strip=True))
                horses[current_umaban]["danwa"] = (horses[current_umaban]["danwa"] + " " + txt).strip()
    return header_info, horses

def fetch_keibabook_chokyo(driver, race_id: str):
    url = f"{BASE_URL}/cyuou/cyokyo/0/{race_id}"
    driver.get(url)
    try: WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "cyokyo")))
    except: pass
    soup = BeautifulSoup(driver.page_source, "html.parser")
    data = {}
    for tbl in soup.find_all("table", class_="cyokyo"):
        umaban_td = tbl.find("td", class_="umaban")
        if not umaban_td: continue
        umaban = re.sub(r"\D", "", umaban_td.get_text(strip=True))
        tanpyo = _clean_text_ja(tbl.find("td", class_="tanpyo").get_text(strip=True)) if tbl.find("td", class_="tanpyo") else "なし"
        details_parts, detail_cell = [], tbl.find("td", colspan="5")
        if detail_cell:
            header_info = ""
            for child in detail_cell.children:
                if isinstance(child, NavigableString): continue
                if child.name == 'dl' and 'dl-table' in child.get('class', []):
                    header_info = " ".join([dt.get_text(" ", strip=True) for dt in child.find_all('dt')])
                elif child.name == 'table' and 'cyokyodata' in child.get('class', []):
                    time_tr, awase_tr = child.find('tr', class_='time'), child.find('tr', class_='awase')
                    time_str = "-".join([td.get_text(strip=True) for td in time_tr.find_all('td')]) if time_tr else ""
                    awase_str = f" (併せ: {_clean_text_ja(awase_tr.get_text(strip=True))})" if awase_tr else ""
                    if header_info or time_str: details_parts.append(f"[{header_info}] {time_str}{awase_str}")
                    header_info = ""
        data[umaban] = {"tanpyo": tanpyo, "details": "\n".join(details_parts) if details_parts else "詳細なし"}
    return data

def fetch_zenkoso_interview(driver, race_id: str):
    url = f"{BASE_URL}/cyuou/syoin/{race_id}"
    driver.get(url)
    try: WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.default.syoin")))
    except: pass
    soup = BeautifulSoup(driver.page_source, "html.parser")
    interview_data, table = {}, soup.find("table", class_=lambda c: c and "syoin" in str(c))
    if table and table.tbody:
        current_umaban = None
        for tr in table.tbody.find_all("tr", recursive=False):
            umaban_td = tr.find("td", class_="umaban")
            if umaban_td: current_umaban = re.sub(r"\D", "", umaban_td.get_text(strip=True)); continue
            syoin_td = tr.find("td", class_="syoin")
            if syoin_td and current_umaban:
                meta = syoin_td.find("div", class_="syoindata")
                if meta: meta.decompose()
                txt = _clean_text_ja(syoin_td.get_text(" ", strip=True))
                if not _is_missing_marker(txt): interview_data[current_umaban] = txt
    return interview_data

def fetch_keibabook_cpu_data(driver, race_id: str, is_shinba: bool = False):
    url = f"{BASE_URL}/cyuou/cpu/{race_id}"
    driver.get(url)
    try: WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "main")))
    except: pass
    
    soup = BeautifulSoup(driver.page_source, "html.parser")
    data = {}
    
    # --- スピード指数テーブルの解析 ---
    speed_tbl = soup.find("table", id="cpu_speed_sort_table")
    if speed_tbl and speed_tbl.tbody:
        for tr in speed_tbl.tbody.find_all("tr"):
            umaban_td = tr.find("td", class_="umaban")
            if not umaban_td: continue
            
            umaban = re.sub(r"\D", "", umaban_td.get_text(strip=True))
            tds = tr.find_all("td")
            
            # 列数が足りない場合はスキップ (通常8列以上あるはず)
            if len(tds) < 8: continue
            
            def get_val(idx):
                txt = tds[idx].get_text(strip=True)
                # 数値以外を除去してint化
                val = int(re.sub(r"\D", "", txt)) if re.sub(r"\D", "", txt) else 0
                return val

            data[umaban] = {
                "sp_best": get_val(4), # 最高
                "sp_3":    get_val(5), # 3走前
                "sp_2":    get_val(6), # 2走前
                "sp_last": get_val(7)  # 前走
            }

    factor_tbl = None
    for t in soup.find_all("table"):
        cap = t.find("caption")
        if cap and "ファクター" in cap.get_text(): factor_tbl = t; break
    
    if factor_tbl and factor_tbl.tbody:
        for tr in factor_tbl.tbody.find_all("tr"):
            umaban_td = tr.find("td", class_="umaban")
            if not umaban_td: continue
            umaban = re.sub(r"\D", "", umaban_td.get_text(strip=True))
            
            tds = tr.find_all("td")
            if len(tds) < 6: continue
            
            def get_m(idx):
                p = tds[idx].find("p")
                return p.get_text(strip=True) if p else "-"
            
            if umaban not in data: data[umaban] = {}
            
            # 新馬戦かどうかで取得する列を変える
            if is_shinba:
                data[umaban].update({"fac_deashi": get_m(5), "fac_kettou": get_m(6), "fac_ugoki": get_m(8)})
            else:
                data[umaban].update({"fac_crs": get_m(5), "fac_dis": get_m(6), "fac_zen": get_m(7)})
                
    return data
# ==================================================
# Netkeiba & 近走指数
# ==================================================
def calculate_passing_order_bonus(pass_str: str, final_rank: int) -> float:
    if not pass_str or pass_str == "-": return 0.0
    clean_pass = re.sub(r"\(.*?\)", "", pass_str).strip()
    parts = clean_pass.split("-")
    positions = []
    for p in parts:
        try: positions.append(int(p))
        except: pass
    if len(positions) < 2: return 0.0
    max_bonus = 0.0
    for i in range(1, len(positions)):
        drop = positions[i] - positions[i-1]
        if drop > 0:
            if drop >= 4 and final_rank < positions[i]: return 8.0
            if drop >= 2 and final_rank < positions[i]: max_bonus = max(max_bonus, 5.0)
    return max_bonus

def fetch_netkeiba_data(driver, year, kai, place, day, race_num):
    nk_place = KEIBABOOK_TO_NETKEIBA_PLACE.get(place, "")
    if not nk_place: return {}
    nk_race_id = f"{year}{nk_place}{kai.zfill(2)}{day.zfill(2)}{race_num.zfill(2)}"
    url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id={nk_race_id}"
    try:
        driver.get(url)
        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "Shutuba_Past5_Table")))
    except Exception as e:
        print(f"Netkeiba timeout: {e}")
        return {}
    soup = BeautifulSoup(driver.page_source, "html.parser")
    data = {}
    for tr in soup.find_all("tr", class_="HorseList"):
        umaban_tds, umaban = tr.find_all("td", class_="Waku"), ""
        for td in umaban_tds:
            txt = re.sub(r"\D", "", td.get_text(strip=True))
            if txt: umaban = txt; break
        if not umaban: continue
        
        # --- ★修正: 騎手名を<a>タグから正確に取得 ---
        jockey_td = tr.find("td", class_="Jockey")
        jockey = "不明"
        if jockey_td:
            a_tag = jockey_td.find("a")
            if a_tag:
                jockey = _clean_text_ja(a_tag.get_text(strip=True))
            else:
                # aタグが無い場合のフォールバック（テキスト全体から抽出）
                # 通常はaタグがあるはずだが、万が一のため
                full_text = jockey_td.get_text(strip=True)
                # 斤量や性別を除去する簡易処理（数字や特定の文字を除く）
                jockey = re.sub(r'[0-9\.]+|牡|牝|セ|栗|鹿|芦|黒', '', full_text).strip()
        # ---------------------------------------------
        
        past_str_list, valid_runs = [], []
        prev_jockey = None # 前走騎手格納用

        # Pastカラムを走査 (最新が右側にあるため反転させて最大3走を取得)
        past_tds = tr.find_all("td", class_="Past")
        valid_tds = [td for td in past_tds if td.get_text(strip=True)]
        past_tds_recent = valid_tds[::-1][:3]
        
        for idx, td in enumerate(past_tds_recent):
            if "Rest" in td.get("class", []): 
                past_str_list.append("(放牧/休養)")
            else:
                d01, d02 = td.find("div", class_="Data01"), td.find("div", class_="Data02")
                date_place = _clean_text_ja(d01.get_text(strip=True)) if d01 else ""
                race_name_dist = _clean_text_ja(d02.get_text(strip=True)) if d02 else ""
                rank_tag = td.find("span", class_="Num") or td.find("div", class_="Rank")
                rank = rank_tag.get_text(strip=True) if rank_tag else "?"
                passing_order, d06 = "", td.find("div", class_="Data06")
                if d06:
                    match = re.match(r'^([\d\-]+)', d06.get_text(strip=True))
                    if match: passing_order = match.group(1)
                
                # 前走(index 0)のData03から騎手名を抽出
                if idx == 0:
                    d03 = td.find("div", class_="Data03")
                    if d03:
                        d03_text = _clean_text_ja(d03.get_text(strip=True))
                        # Data03形式例: "18頭 2番 14人 坂井瑠星 58.0"
                        j_match = re.search(r'\d+人\s+(.+?)\s+\d+\.\d', d03_text)
                        if j_match:
                            prev_jockey = j_match.group(1).strip()
                        else:
                            parts = d03_text.split()
                            if len(parts) >= 2: prev_jockey = parts[-2]

                past_str_list.append(f"[{date_place} {race_name_dist} {passing_order}→{rank}着]")
                try:
                    rank_int = int(re.sub(r"\D", "", rank))
                    valid_runs.append({"rank_int": rank_int, "bonus": calculate_passing_order_bonus(passing_order, rank_int)})
                except: pass
        
        base_score = sum(1.0 for r in valid_runs if r["rank_int"] <= 5)
        max_bonus = max([r["bonus"] for r in valid_runs], default=0.0)
        
        data[umaban] = {
            "jockey": jockey, 
            "prev_jockey": prev_jockey, 
            "past": past_str_list, 
            "kinsou_index": float(min(base_score + max_bonus, 10.0))
        }
    return data

# ==================================================
# Yahooスポーツナビ 対戦表取得ロジック（★評価ランク対応版）
# ==================================================
def fetch_yahoo_matrix_data(driver, year, place, kai, day, race_num, current_distance_str, horse_evals=None, current_venue=""):
    nk_place = KEIBABOOK_TO_NETKEIBA_PLACE.get(place, "")
    if not nk_place: return "場所コードエラー"
    y_year, y_id = year[-2:], f"{year[-2:]}{nk_place}{kai.zfill(2)}{day.zfill(2)}{race_num.zfill(2)}"
    url = f"https://sports.yahoo.co.jp/keiba/race/matrix/{y_id}"
    driver.get(url)
    try: WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "hr-tableLeftTop--matrix")))
    except: return "対戦データ取得タイムアウト"
    soup = BeautifulSoup(driver.page_source, "html.parser")
    table = soup.find("table", class_="hr-tableLeftTop--matrix")
    if not table or not table.thead: return "対戦データなし"
    past_races, header_th_list = [], table.thead.find_all("th")[1:]
    for th in header_th_list:
        link_tag = th.find("a")
        if not link_tag: past_races.append(None); continue
        items = th.find_all("span", class_="hr-tableLeftTop__item")
        dist_str = next((item.get_text(strip=True) for item in items if "m" in item.get_text()), "")
        past_races.append({"id": link_tag.get("href").split("/")[-1], "name": link_tag.get_text(strip=True), "date": th.find("span", class_="hr-tableLeftTop__item--date").get_text(" ", strip=True), "dist_str": dist_str})
    matrix_data = {}
    for tr in table.tbody.find_all("tr"):
        th_horse = tr.find("th")
        if not th_horse or not th_horse.find("a"): continue
        horse_name = th_horse.find("a").get_text(strip=True)
        for idx, td in enumerate(tr.find_all("td")):
            if idx >= len(past_races) or not past_races[idx]: continue
            txt = td.get_text(strip=True)
            if "-" in txt and len(txt) < 5: continue
            rid, rank = past_races[idx]["id"], td.find("span").get_text(strip=True) if td.find("span") else "?"
            if rid not in matrix_data: matrix_data[rid] = {"info": past_races[idx], "results": []}
            matrix_data[rid]["results"].append({"name": horse_name, "rank": rank})
    valid_battles = sorted([d for d in matrix_data.values() if len(d["results"]) >= 2], key=lambda x: x["info"]["id"], reverse=True)
    if not valid_battles: return "対戦データなし（該当レースなし）"
    current_dist_int = extract_distance_int(current_distance_str)
    output_lines_plain = ["\n【対戦表】"]
    output_lines_html = ["<div style='margin-bottom: 20px;'><h4 style='color: #4b5563; border-bottom: 2px solid #e5e7eb; padding-bottom: 5px;'>⚔️ 対戦表</h4>"]
    nk_codes_to_names = {
        "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
        "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"
    }
    left_venues = ["東京", "中京", "新潟"]
    right_venues = ["中山", "阪神", "京都", "札幌", "函館", "福島", "小倉"]

    for battle in valid_battles:
        info = battle["info"]
        results = battle["results"]
        results.sort(key=lambda r: int(re.sub(r"\D", "", r["rank"])) if re.sub(r"\D", "", r["rank"]) else 999)
        diff = extract_distance_int(info["dist_str"]) - current_dist_int
        
        info_place_code = info['id'][2:4] if len(info['id']) >= 4 else ""
        venue_name = nk_codes_to_names.get(info_place_code, "")
        
        venue_style = ""
        if current_venue and venue_name == current_venue:
            venue_style = "color: #EF4444; font-weight: bold;"
        elif current_venue:
            if (current_venue in left_venues and venue_name in left_venues) or (current_venue in right_venues and venue_name in right_venues):
                venue_style = "font-weight: bold; color: #111827;"
            
        styled_dist_str = f"<span style='{venue_style}'>{venue_name}</span>{info['dist_str']}"
        plain_dist_str = f"{venue_name}{info['dist_str']}"
        
        res_str_list = []
        res_html_list = []
        for r in results:
            grade = horse_evals.get(r['name'], "") if horse_evals else ""
            
            # Plain text part
            suffix_plain = f"({grade})" if grade else ""
            res_str_list.append(f"{r['rank']}着{r['name']}{suffix_plain}")
            
            # HTML part (color coding grade)
            if grade == "S": g_color = "#FFD700"
            elif grade == "A": g_color = "#FF69B4"
            elif grade == "B": g_color = "#FF0000"
            elif grade == "C": g_color = "#FFA500"
            else: g_color = "#6b7280"
            
            suffix_html = f"(<span style='color:{g_color};font-weight:bold;'>{grade}</span>)" if grade else ""
            res_html_list.append(f"{r['rank']}着{r['name']}{suffix_html}")
            
        url = f"https://race.netkeiba.com/race/result.html?race_id=20{info['id']}"
        
        # Plain text
        output_lines_plain.extend([
            f"・{info['date'].replace(' ', '')} {info['name']} {plain_dist_str}({diff:+}m)", 
            f"URL：{url}", 
            "着順：" + "　".join(res_str_list), 
            ""
        ])
        
        # HTML 
        output_lines_html.append(f"<div style='background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; margin-bottom: 10px;'>")
        output_lines_html.append(f"<div style='font-weight: bold; margin-bottom: 4px; color: #4b5563;'>{info['date'].replace(' ', '')} {info['name']} {styled_dist_str}({diff:+}m)</div>")
        output_lines_html.append(f"<div style='margin-bottom: 6px;'><a href='{url}' target='_blank' style='color: #3b82f6; text-decoration: none;'>📄 レース結果を見る</a></div>")
        output_lines_html.append(f"<div style='font-size: 0.9em; color: #374151;'><strong>着順：</strong>{'　'.join(res_html_list)}</div>")
        output_lines_html.append("</div>")

    output_lines_html.append("</div>")
    
    return "\n".join(output_lines_plain), "".join(output_lines_html)

# ==================================================
# Dify Streaming
# ==================================================
def stream_dify_workflow(full_text: str):
    if not DIFY_API_KEY: yield "⚠️ DIFY_API_KEY 未設定"; return
    payload = {"inputs": {"text": full_text}, "response_mode": "streaming", "user": "keiba-bot"}
    headers = {"Authorization": f"Bearer {DIFY_API_KEY}", "Content-Type": "application/json"}
    try:
        res = requests.post("https://api.dify.ai/v1/workflows/run", headers=headers, json=payload, stream=True, timeout=90)
        for line in res.iter_lines():
            if not line: continue
            decoded = line.decode("utf-8").replace("data: ", "")
            try:
                data = json.loads(decoded)
                if data.get("event") == "workflow_finished":
                    for val in data.get("data", {}).get("outputs", {}).values():
                        if isinstance(val, str): yield val
                elif "answer" in data: yield data.get("answer", "")
            except: pass
    except Exception as e: yield f"Error: {e}"



# ==========================================
# 2. 競馬ブック スクレイピングロジック（キャッシュ化）
# ==========================================
@st.cache_data(ttl=60, show_spinner=False)
def fetch_real_data(race_id: str):
    import datetime
    url = f"https://s.keibabook.co.jp/cyuou/nouryoku_html_detail/{race_id}.html"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers)
        response.encoding = 'utf-8' 
        time.sleep(1) 
        soup = BeautifulSoup(response.text, 'html.parser')
        
        basyo_elem = soup.select_one('td.basyo')
        current_venue = basyo_elem.text.strip() if basyo_elem else "不明"
        if current_venue == "不明": return None, 1600, "", "芝", "出馬表データが見つかりません。"
        
        kyori_elem = soup.select_one('span.kyori')
        course_elem = soup.select_one('span.course')
        
        current_dist = int(re.search(r'\d+', kyori_elem.text).group()) if kyori_elem else 1600
        current_track = "ダート" if course_elem and "ダ" in course_elem.text else "芝"

        horses_data = []
        trs = soup.select('table.noryoku tr[class^="js-umaban"]')
        if not trs:
            return None, current_dist, current_venue, current_track, "出走馬データが見つかりません。"

        for tr in trs:
            umaban_elem = tr.select_one('td.umaban span')
            if not umaban_elem: continue
            horse_num = int(umaban_elem.text.strip())
            
            bamei_elem = tr.select_one('td.bamei span.kbamei a')
            horse_name = bamei_elem.text.strip() if bamei_elem else "不明"
            
            past_races = []
            current_weight = 480.0 
            
            for td in tr.select('td.zensou'):
                if not td.select_one('.kyori'): continue
                
                k_text = td.select_one('.kyori').text
                dist_m = re.search(r'\d+', k_text)
                dist = int(dist_m.group()) if dist_m else current_dist
                track = "ダート" if "ダ" in k_text else "芝"
                
                baba_img = td.select_one('.baba img')
                baba_cond = "良"
                if baba_img:
                    src = baba_img.get('src', '')
                    if 'ryo' in src: baba_cond = '良'
                    elif 'yaya' in src: baba_cond = '稍'
                    elif 'omo' in src: baba_cond = '重'
                    elif 'huryo' in src: baba_cond = '不良'
                
                early_3f_span = td.select_one('.uzenh3')
                early_3f = np.nan
                if early_3f_span:
                    e3f_text = early_3f_span.text.strip()
                    e3f_match = re.search(r'[\d\.]+', e3f_text)
                    if e3f_match:
                        try:
                            val = float(e3f_match.group())
                            if 25.0 <= val <= 60.0:
                                early_3f = val
                        except:
                            pass
                
                tuka_imgs = td.select('.tuka img')
                first_corner = 7
                is_late_start = False
                if tuka_imgs:
                    src = tuka_imgs[0].get('src', '')
                    m = re.search(r'(\d+)\.gif', src)
                    if m: first_corner = int(m.group(1))
                    if 'maru' in src: is_late_start = True 
                        
                umaban_span = td.select_one('.umaban')
                past_frame = 4
                if umaban_span:
                    frame_m = re.search(r'(\d+)枠', umaban_span.text)
                    if frame_m: past_frame = int(frame_m.group(1))

                cyaku_span = td.select_one('span[class^="cyaku"]')
                finish_pos = int(re.search(r'\d+', cyaku_span.text).group()) if cyaku_span and re.search(r'\d+', cyaku_span.text) else 5
                
                ninki_span = td.select_one('.ninki')
                popularity = int(re.search(r'\d+', ninki_span.text).group()) if ninki_span and re.search(r'\d+', ninki_span.text) else 5
                
                negahi_spans = td.select('.negahi')
                p_venue = current_venue
                if negahi_spans:
                    v_text = negahi_spans[0].text
                    venue_map = {"東":"東京", "中":"中山", "京":"京都", "阪":"阪神", "名":"中京", "新":"新潟", "福":"福島", "小":"小倉", "札":"札幌", "函":"函館"}
                    local_venue_map = {"盛":"盛岡", "水":"水沢", "浦":"浦和", "船":"船橋", "大":"大井", "川":"川崎", "金":"金沢", "笠":"笠松", "園":"園田", "姫":"姫路", "高":"高知", "佐":"佐賀"}
                    for v_key, v_val in venue_map.items():
                        if v_key in v_text:
                            p_venue = v_val
                            break
                    for v_key, v_val in local_venue_map.items():
                        if v_key in v_text:
                            p_venue = v_val
                            break
                
                batai_span = td.select_one('.batai')
                weight = float(batai_span.text.strip()) if batai_span else 480.0
                
                date_str = ""
                negahi_all = td.select('.negahi')
                for span in negahi_all:
                    if '･' in span.text:
                        date_str = span.text.strip()
                
                past_races.append({
                    'venue': p_venue, 'track_type': track, 'distance': dist,
                    'track_condition': baba_cond, 'finish_position': finish_pos,
                    'popularity': popularity, 'early_3f': early_3f,
                    'first_corner_pos': first_corner, 'is_late_start': is_late_start,
                    'past_frame': past_frame, 'weight': weight,
                    'date_str': date_str, 'date': None
                })

            if past_races:
                current_weight = past_races[-1]['weight']
                
            # Parse dates backwards to ensure correct year mapping
            last_dt = datetime.date.today()
            for rp in reversed(past_races):
                date_str = rp.get('date_str', '')
                d_val = None
                if date_str:
                    m2 = re.search(r'(?:(\d+)[\.\/])?(\d+)･(\d+)', date_str)
                    if m2:
                        y_str, mon, day = m2.groups()
                        if y_str:
                            y = 2000 + int(y_str) if len(y_str) <= 2 else int(y_str)
                            try:
                                d_val = datetime.date(y, int(mon), int(day))
                            except: pass
                        else:
                            y = last_dt.year
                            while True:
                                try:
                                    d_val = datetime.date(y, int(mon), int(day))
                                    if d_val <= last_dt:
                                        break
                                except ValueError: pass
                                y -= 1
                        last_dt = d_val
                rp['date'] = d_val

            horses_data.append({
                'horse_number': horse_num, 'horse_name': horse_name,
                'current_weight': current_weight, 'past_races': past_races,
                'score': 0.0, 'special_flag': ""
            })

        if not horses_data: return None, 1600, "", "芝", "馬データが取得できませんでした。"
        
        return horses_data, current_dist, current_venue, current_track, None
        
    except Exception as e:
        return None, 1600, "", "芝", f"エラー: {e}\n{traceback.format_exc()}"

# ==========================================
# 3. スマホ対応UI
# ==========================================
st.set_page_config(page_title="AI競馬 展開&能力予想", page_icon="🏇", layout="wide")

st.title("🏇 AI競馬 展開 & 能力予想")
st.markdown("展開（ペース・隊列）と能力（スピード指数・AI分析）を統合したハイブリッド予想を行います。")

with st.container(border=True):
    st.subheader("⚙️ レース設定")
    
    st.markdown("[🔗 競馬ブックはこちら](https://s.keibabook.co.jp/cyuou/top)")
    
    if "input_url" not in st.session_state:
        st.session_state["input_url"] = "https://s.keibabook.co.jp/cyuou/nouryoku_html_detail/202601040703.html"
        
    base_url_input = st.text_input("🔗 競馬ブックの出馬表URLを貼り付け", key="input_url")
    
    st.markdown("**🎯 予想したいレースを選択（複数可）**")
    if "races_sel" not in st.session_state:
        st.session_state["races_sel"] = [9, 10]
    
    def select_all_races():
        st.session_state["races_sel"] = list(range(1, 13))
    def deselect_all_races():
        st.session_state["races_sel"] = []
    
    c_sa, c_sd, _ = st.columns([2, 2, 6])
    c_sa.button("☑️ 全選択", on_click=select_all_races)
    c_sd.button("🔲 全解除", on_click=deselect_all_races)
    
    try:
        selected_races = st.pills("レース番号", options=list(range(1, 13)), key="races_sel", format_func=lambda x: f"{x}R", selection_mode="multi")
    except TypeError:
        selected_races = st.multiselect("レース番号", options=list(range(1, 13)), key="races_sel", format_func=lambda x: f"{x}R")

    if not isinstance(selected_races, list):
        selected_races = [selected_races] if selected_races else []

    col1, col2, col3 = st.columns(3)
    with col1:
        execute_both_btn = st.button("🚀展開＆AI予想", type="primary", use_container_width=True)
    with col2:
        execute_tenkai_btn = st.button("🤸‍♂️展開のみ", type="secondary", use_container_width=True)
    with col3:
        execute_ai_btn = st.button("🤖AI予想のみ", type="secondary", use_container_width=True)

# 実行トリガーの判定
run_inference = False
run_mode = "both"
target_races = []
base_race_id = ""

if execute_both_btn:
    run_inference = True
    run_mode = "both"
elif execute_tenkai_btn:
    run_inference = True
    run_mode = "tenkai"
elif execute_ai_btn:
    run_inference = True
    run_mode = "ai"

if run_inference:
    if not selected_races:
        st.warning("レース番号を選択してください。")
        run_inference = False
    else:
        target_races = selected_races
        match = re.search(r'\d{10,12}', base_url_input)
        base_race_id = match.group()[:10] if match else ""

# ==========================================
# 推論・描画の実行
# ==========================================
if run_inference:
    if not base_race_id:
        st.error("有効な競馬ブックのレースIDが見つかりません。")
    else:
        # Selenium Driver 起動
        driver = None
        try:
            with st.spinner("Seleniumブラウザを起動・ログインしています..."):
                driver = build_driver()
                login_keibabook(driver)
        except Exception as e:
            st.warning(f"ログインに失敗しました: {e}")
            if driver: driver.quit()
            driver = None

        full_output_log = ""
        full_html_log = ""
        full_html_tabs_buttons = ""
        full_html_tabs_content = ""

        # 各レースのループ
        for race_num in sorted(target_races):
            # re-initialize if crashed
            if not driver:
                with st.spinner(f"ブラウザを再起動しています..."):
                    driver = build_driver()
                    login_keibabook(driver)

            target_race_id = f"{base_race_id}{race_num:02d}"
            
            st.markdown(f"## 🏁 {race_num}R")
            
            cached_data = load_race_cache(target_race_id, run_mode)
            if cached_data:
                st.success("⚡ 1時間以内のキャッシュから瞬時に読み込みました！")
                current_dist = cached_data.get("current_dist", "")
                current_venue = cached_data.get("current_venue", "")
                current_track = cached_data.get("current_track", "")
                race_title = cached_data.get("race_title", "")
                total_horses = cached_data.get("total_horses", 0)
                sorted_horses = cached_data.get("sorted_horses", [])
                formation_text = cached_data.get("formation_text", "")
                pace_comment = cached_data.get("pace_comment", "")
                horse_evals = cached_data.get("horse_evals", {})
                html_ai_output = cached_data.get("html_ai_output", "")
                final_output = cached_data.get("final_output", "")
                battle_matrix_text = cached_data.get("battle_matrix_text", "")
                matrix_html = cached_data.get("matrix_html", "")
                
                st.info(f"📏 条件: **{current_venue} {current_track}{current_dist}m** ({total_horses}頭立て)  \n" + race_title)
                
                if run_mode in ("both", "tenkai"):
                    st.markdown(f"<h4 style='text-align: center; letter-spacing: 2px;'>◀(進行方向)</h4>", unsafe_allow_html=True)
                    st.markdown(f"<h3 style='text-align: center; color: #FF4B4B;'>{formation_text}</h3>", unsafe_allow_html=True)
                    st.markdown("---")
                    st.write(pace_comment)
                    with st.expander(f"📊 {race_num}R の展開データ・ポジションスコア"):
                        df_rows = []
                        for h in sorted_horses:
                            past = h.get('past_races', [])
                            zenso = str(past[-1]['first_corner_pos']) if len(past) >= 1 and 'first_corner_pos' in past[-1] else "-"
                            ni_so = str(past[-2]['first_corner_pos']) if len(past) >= 2 and 'first_corner_pos' in past[-2] else "-"
                            san_so = str(past[-3]['first_corner_pos']) if len(past) >= 3 and 'first_corner_pos' in past[-3] else "-"
                            df_rows.append({
                                "馬番": h['horse_number'], "馬名": h['horse_name'], "スコア": round(h.get('score', 0), 2),
                                "戦法": h.get('running_style', ''), "前走1角": zenso, "2走前1角": ni_so, "3走前1角": san_so, "特記事項": h.get('special_flag', '')
                            })
                        if df_rows:
                            st.dataframe(pd.DataFrame(df_rows), use_container_width=True, hide_index=True)
                
                if run_mode in ("both", "ai"):
                    st.markdown(f"### 🤖 AI総合評価 ({race_num}R)")
                    st.markdown(final_output)

            if not cached_data:
                with st.spinner(f"{race_num}R のデータ収集中..."):
                    # --- [1] app.py側のデータ取得 (requests版) ---
                    horses, current_dist, current_venue, current_track, error_msg = fetch_real_data(target_race_id)
                    if error_msg:
                        st.warning(f"{error_msg}")
                        continue
                        
                    total_horses = len(horses)
                    
                    # --- [2] ability_prediction側のデータ取得 (Selenium版) ---
                    header_info, danwa_data = fetch_keibabook_danwa(driver, target_race_id)
                    race_title = header_info.get("header_text", "")
                    is_shinba = any(x in race_title for x in ["新馬", "メイクデビュー"])
                    
                    cpu_data, speed_metrics, interview_data, chokyo_data, nk_data = {}, {}, {}, {}, {}
                    year_str = target_race_id[:4]
                    kai_str = target_race_id[4:6]
                    place_str = target_race_id[6:8]
                    day_str = target_race_id[8:10]
    
                    if run_mode in ("both", "ai"):
                        cpu_data = fetch_keibabook_cpu_data(driver, target_race_id, is_shinba=is_shinba)
                        speed_metrics = compute_speed_metrics(cpu_data)
                        interview_data = fetch_zenkoso_interview(driver, target_race_id)
                        chokyo_data = fetch_keibabook_chokyo(driver, target_race_id)
                        nk_data = fetch_netkeiba_data(driver, year_str, kai_str, place_str, day_str, f"{race_num:02d}")
                    
                    # --- [3] 展開スコア計算 & 厩舎話微調整 ---
                    for horse in horses:
                        # 基本スコア計算
                        horse['score'] = calculate_pace_score(horse, current_dist, current_venue, current_track, total_horses)
                        
                        # 厩舎話による微調整
                        umaban_str = str(horse['horse_number'])
                        if danwa_data and umaban_str in danwa_data:
                            danwa_text = danwa_data[umaban_str].get('danwa', '')
                            score, special_flag, running_style = adjust_score_by_danwa(
                                danwa_text, 
                                horse['score'], 
                                horse.get('special_flag', ''), 
                                horse.get('running_style', '')
                            )
                            horse['score'] = score
                            horse['special_flag'] = special_flag
                            horse['running_style'] = running_style
    
                    horses = apply_give_up_synergy(horses, current_venue, current_dist, current_track)
                    sorted_horses = sorted(horses, key=lambda x: x['score'])
                    formation_text = format_formation(sorted_horses)
                    pace_comment = generate_pace_and_spread_comment(sorted_horses, current_track)
    
                # --- [4] 展開予想の表示 (app.py) ---
                st.info(f"📏 条件: **{current_venue} {current_track}{current_dist}m** ({total_horses}頭立て)  \n" + race_title)
                
                if run_mode in ("both", "tenkai"):
                    # 展開パネル
                    st.markdown(f"<h4 style='text-align: center; letter-spacing: 2px;'>◀(進行方向)</h4>", unsafe_allow_html=True)
                    st.markdown(f"<h3 style='text-align: center; color: #FF4B4B;'>{formation_text}</h3>", unsafe_allow_html=True)
                    st.markdown("---")
                    st.write(pace_comment)
                    
                    with st.expander(f"📊 {race_num}R の展開データ・ポジションスコア"):
                        df_rows = []
                        for h in sorted_horses:
                            past = h.get('past_races', [])
                            zenso = str(past[-1]['first_corner_pos']) if len(past) >= 1 and 'first_corner_pos' in past[-1] else "-"
                            ni_so = str(past[-2]['first_corner_pos']) if len(past) >= 2 and 'first_corner_pos' in past[-2] else "-"
                            san_so = str(past[-3]['first_corner_pos']) if len(past) >= 3 and 'first_corner_pos' in past[-3] else "-"
                            
                            df_rows.append({
                                "馬番": h['horse_number'],
                                "馬名": h['horse_name'],
                                "スコア": round(h['score'], 2),
                                "戦法": h.get('running_style', ''),
                                "前走1角": zenso,
                                "2走前1角": ni_so,
                                "3走前1角": san_so,
                                "特記事項": h.get('special_flag', '')
                            })
                        st.dataframe(pd.DataFrame(df_rows), use_container_width=True, hide_index=True)
                
                horse_evals = {}
                html_ai_output = ""
                final_output = ""
                
                if run_mode in ("both", "ai"):
                    # --- [5] 能力予想 & Dify実行 (ability_prediction.py) ---
                    st.markdown(f"### 🤖 AI総合評価 ({race_num}R)")
                    
                    # Dify用プロンプトのコンパイル
                    lines = []
                    for horse in sorted_horses:
                        umaban = horse['horse_number']
                        umaban_str = str(umaban)
                        
                        # 展開スコアや特記事項を能力データと結合する
                        d = danwa_data.get(umaban_str, {"waku": "?", "name": horse['horse_name'], "danwa": "なし"})
                        sm = speed_metrics.get(umaban_str, {})
                        n = nk_data.get(umaban_str, {})
                        c = cpu_data.get(umaban_str, {})
                        k = chokyo_data.get(umaban_str, {"tanpyo": "-", "details": "-"})
                        
                        bias = calculate_baba_bias(int(d["waku"]) if isinstance(d["waku"], str) and d["waku"].isdigit() else 0, race_title)
                        
                        sp_val = sm.get("speed_index", "-")
                        sp_str = f"スピード指数:{sp_val}/35点"
                        kinsou_idx = n.get("kinsou_index", 0.0)
                        fac_str = f"F:{c.get('fac_deashi','-')}/{c.get('fac_kettou','-')}" if is_shinba else f"F:{c.get('fac_crs','-')}/{c.get('fac_dis','-')}"
                        
                        current_jockey = n.get('jockey', '-')
                        prev_jockey = n.get('prev_jockey', None)
                        
                        def is_same_jockey(prev_full, curr_abbr):
                            if not prev_full or not curr_abbr: return False
                            p = prev_full.replace(" ", "").replace("　", "")
                            c = curr_abbr.replace(" ", "").replace("　", "")
                            if p == c: return True
                            if len(c) > 0 and p.startswith(c): return True
                            return False
        
                        jockey_disp = f"騎手:{current_jockey}←{prev_jockey}" if (prev_jockey and not is_same_jockey(prev_jockey, current_jockey)) else f"騎手:{current_jockey}"
                        
                        line = (
                            f"▼{d['waku']}枠{umaban}番 {d['name']} ({jockey_disp})\n"
                            f"【データ】{sp_str} バイアス:{bias['total']} 近走指数:{kinsou_idx:.1f} {fac_str}\n"
                            f"【厩舎】{d.get('danwa', '')}\n"
                            f"【前走】{interview_data.get(umaban_str, 'なし')}\n"
                            f"【調教】{k.get('tanpyo', '')} \n{k.get('details', '')}\n"
                            f"【近走】{' / '.join(n.get('past', []))}\n"
                        )
                        lines.append(line)
        
                    # レース情報と各馬詳細のみ（展開予想に関する見解はAIへ渡さない）
                    raw_data_block = f"■レース情報\n{race_title}\n\n■各馬詳細\n" + "\n".join(lines)
                    
                    result_area = st.empty()
                    ai_output = ""
                    
                    with st.spinner("Dify AIプロンプト分析中..."):
                        for chunk in stream_dify_workflow(raw_data_block):
                            ai_output += chunk
                            result_area.markdown(ai_output + "▌")
                        
                        horse_evals = parse_dify_evaluation(ai_output)
                        
                        matrix_html = ""
                        battle_matrix_raw = fetch_yahoo_matrix_data(
                            driver, year_str, place_str, kai_str, day_str, f"{race_num:02d}", 
                            str(current_dist), 
                            horse_evals=horse_evals, current_venue=current_venue
                        )
                        
                        if isinstance(battle_matrix_raw, tuple):
                            battle_matrix_text = battle_matrix_raw[0]
                            matrix_html = battle_matrix_raw[1]
                        else:
                            battle_matrix_text = battle_matrix_raw
                            matrix_html = ""
        
                    final_output = ai_output
                    result_area.markdown(final_output)
                    
                    import html
                    html_ai_output = format_dify_md_to_html(final_output)
                    
                    if not cached_data:
                        save_race_cache(target_race_id, run_mode, {
                            "current_dist": current_dist,
                            "current_venue": current_venue,
                            "current_track": current_track,
                            "race_title": race_title,
                            "total_horses": total_horses,
                            "sorted_horses": sorted_horses,
                            "formation_text": formation_text,
                            "pace_comment": pace_comment,
                            "horse_evals": horse_evals,
                            "html_ai_output": html_ai_output,
                            "final_output": final_output,
                            "battle_matrix_text": battle_matrix_text,
                            "matrix_html": matrix_html
                        })
                    
            log_parts = [f"\n【{race_num}R】 {race_title}"]
            if run_mode in ("both", "tenkai"):
                log_parts.append(f"■展開予想\n{formation_text}\n{pace_comment}")
            if run_mode in ("both", "ai"):
                log_parts.append(f"■AI総合評価\n{final_output}")
            log_parts.append("==========================\n")
            full_output_log += "\n\n".join(log_parts)
            
            # --- スマホ対応 HTML 生成 ---
            colored_formation = formation_text
            if horse_evals:
                for h_name, grade in horse_evals.items():
                    h_num = next((h['horse_number'] for h in sorted_horses if h['horse_name'] == h_name), None)
                    if h_num:
                        circled_num = chr(9311 + h_num)
                        g_color = ""
                        if grade == "S": g_color = "#FFD700"
                        elif grade == "A": g_color = "#FF69B4"
                        elif grade == "B": g_color = "#FF0000"
                        elif grade == "C": g_color = "#FFA500"
                        
                        if g_color:
                            colored_formation = colored_formation.replace(circled_num, f"<span style='color: {g_color}; font-weight: bold;'>{circled_num}</span>")
            
            details_html = ""
            if run_mode in ("both", "tenkai"):
                details_html = "<details><summary style='cursor: pointer; font-weight: bold; color: #4F46E5;'>📊 展開予測の詳細を開く</summary><div style='overflow-x: auto; padding-bottom: 10px;'><table style='width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; white-space: nowrap;'>"
                details_html += "<tr style='background-color: #f0f2f6; border-bottom: 2px solid #d1d5db;'><th>馬番</th><th>馬名</th><th>スコア</th><th>戦法</th><th>前走1角</th><th>2走前1角</th><th>3走前1角</th><th style='min-width: 200px;'>特記事項</th></tr>"
                for h in sorted_horses:
                    past = h.get('past_races', [])
                    zenso = str(past[-1]['first_corner_pos']) if len(past) >= 1 and 'first_corner_pos' in past[-1] else "-"
                    ni_so = str(past[-2]['first_corner_pos']) if len(past) >= 2 and 'first_corner_pos' in past[-2] else "-"
                    san_so = str(past[-3]['first_corner_pos']) if len(past) >= 3 and 'first_corner_pos' in past[-3] else "-"
                    flag = h.get('special_flag', '')
                    details_html += f"<tr style='border-bottom: 1px solid #e5e7eb;'><td style='text-align:center;'>{h['horse_number']}</td><td>{h['horse_name']}</td><td style='text-align:center;'>{round(h['score'], 2)}</td><td style='text-align:center;'>{h.get('running_style', '')}</td><td style='text-align:center;'>{zenso}</td><td style='text-align:center;'>{ni_so}</td><td style='text-align:center;'>{san_so}</td><td style='white-space: normal; font-size: 0.9em; color: #d97706;'>{flag}</td></tr>"
                details_html += "</table></div></details>"

            eval_html = ""
            if run_mode in ("both", "ai"):
                grade_dict = {"S": [], "A": [], "B": [], "C": [], "D": [], "E": [], "F": [], "G": []}
                if horse_evals:
                    for n, g in horse_evals.items():
                        hn = next((h['horse_number'] for h in sorted_horses if h['horse_name'] == n), "")
                        if g in grade_dict:
                            grade_dict[g].append(f"{hn}番 {n}")
                
                eval_html = "<h4 style='margin-bottom: 10px;'>🏆 AI総合評価</h4>"
                for g in ["S", "A", "B", "C", "D", "E"]:
                    if grade_dict[g]:
                        bcolor = ""
                        if g == "S": bcolor = "background: linear-gradient(to right, #FFD700, #FFA500); color: white; text-shadow: 0 1px 1px rgba(0,0,0,0.5);"
                        elif g == "A": bcolor = "background-color: #FF69B4; color: white;"
                        elif g == "B": bcolor = "background-color: #FF0000; color: white;"
                        elif g == "C": bcolor = "background-color: #FFA500; color: white;"
                        else: bcolor = "background-color: #e5e7eb; color: #374151;"
                        eval_html += f"<div style='margin-bottom: 5px; padding: 4px 8px; border-radius: 4px; {bcolor}'><strong>{g}評価：</strong> {' / '.join(grade_dict[g])}</div>"

            import html
            safe_title = html.escape(race_title.split()[0] if race_title else "")
            
            race_html_parts = [f"<div style='margin-bottom: 30px; font-family: sans-serif;'><h3 style='border-left: 4px solid #FF4B4B; padding-left: 8px;'>🏁 {race_num}R {safe_title}</h3>"]
            
            if run_mode in ("both", "tenkai"):
                safe_pace = html.escape(pace_comment).replace('**', '<b>').replace('🐢', '🐢 ').replace('🔥', '🔥 ')
                race_html_parts.append(f"""
                  <div style='background-color: #f9fafb; padding: 12px; border-radius: 8px; margin-bottom: 15px;'>
                    <p style='text-align: center; margin: 0; color: #6b7280; font-size: 12px;'>◀(進行方向)</p>
                    <p style='text-align: center; font-size: 20px; margin: 10px 0;'>{colored_formation}</p>
                    <p style='font-size: 14px; color: #4b5563; margin-top: 10px; white-space: pre-wrap; line-height: 1.5;'>{safe_pace}</p>
                    {details_html}
                  </div>
                """)
                
            if run_mode in ("both", "ai"):
                race_html_parts.append(eval_html)
                if matrix_html:
                    race_html_parts.append(matrix_html)
                race_html_parts.append(f"""
                  <details style='margin-top: 15px;'><summary style='cursor: pointer; font-weight: bold; color: #4F46E5; background-color: #e0e7ff; padding: 10px; border-radius: 6px;'>📝 AI見解詳細を読む（タップで開閉）</summary>
                    <div style='font-family: inherit; font-size: 13px; color: #374151; background: #ffffff; border: 1px solid #e5e7eb; padding: 12px; border-radius: 0 0 6px 6px; border-top: none;'>
                       {html_ai_output}
                    </div>
                  </details>
                """)
            
            race_html_parts.append("</div>")
            race_html = "".join(race_html_parts)
            full_html_tabs_buttons += f"<button class='umai-tablinks' onclick='umaiOpenTab(event, \"umai-race-{race_num}\")' data-target='umai-race-{race_num}' style='padding: 10px 15px; border: none; background: #e5e7eb; cursor: pointer; border-radius: 4px 4px 0 0; margin-right: 2px; font-weight: bold; color: #374151;'>{race_num}R</button>"
            full_html_tabs_content += f"<div id='umai-race-{race_num}' class='umai-tabcontent' style='display:none;'>{race_html}</div>"
            
            st.markdown("<br><hr><br>", unsafe_allow_html=True)

        if driver:
            driver.quit()

        full_html_log = f"""
        <style>
        .umai-tablinks.active {{ background: #4F46E5 !important; color: white !important; }}
        </style>
        <div class="umai-tabs-container" style="max-width: 800px; margin: auto;">
            <div class="umai-tab-header" style="border-bottom: 2px solid #4F46E5; margin-bottom: 20px;">
                {full_html_tabs_buttons}
            </div>
            {full_html_tabs_content}
        </div>
        <script>
        // Sort AI Table
        function sortAiTable(colIdx) {{
            var table = document.getElementById("ai-eval-table");
            if (!table) return;
            var tbody = table.querySelector("tbody") || table;
            var rows = Array.from(tbody.querySelectorAll("tr")).slice(1);
            
            var currentDir = table.getAttribute("data-sort-dir-" + colIdx);
            var isAsc = currentDir !== "asc";
            table.setAttribute("data-sort-dir-" + colIdx, isAsc ? "asc" : "desc");

            rows.sort(function(a, b) {{
                var cellA = a.children[colIdx];
                var cellB = b.children[colIdx];
                if (!cellA || !cellB) return 0;
                
                var valA = parseInt(cellA.getAttribute("data-sort-val") || "999");
                var valB = parseInt(cellB.getAttribute("data-sort-val") || "999");
                
                return isAsc ? (valA - valB) : (valB - valA);
            }});

            rows.forEach(function(row) {{ tbody.appendChild(row); }});
            
            rows.forEach(function(row, idx) {{
                row.style.backgroundColor = (idx % 2 === 0) ? "#ffffff" : "#f8fafc";
            }});
        }}

        function umaiOpenTab(evt, raceId) {{
            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("umai-tabcontent");
            for (i = 0; i < tabcontent.length; i++) {{
                tabcontent[i].style.display = "none";
            }}
            tablinks = document.getElementsByClassName("umai-tablinks");
            for (i = 0; i < tablinks.length; i++) {{
                tablinks[i].className = tablinks[i].className.replace(" active", "");
            }}
            var targetObj = document.getElementById(raceId);
            if(targetObj) targetObj.style.display = "block";
            if(evt && evt.currentTarget) evt.currentTarget.className += " active";
            try {{ localStorage.setItem("umai_active_race_tab", raceId); }} catch(e){{}}
        }}

        (function() {{
            var activeTab = null;
            try {{ activeTab = localStorage.getItem("umai_active_race_tab"); }} catch(e){{}}
            var tabBtn = document.querySelector('.umai-tablinks[data-target="' + activeTab + '"]');
            if(tabBtn) {{
                tabBtn.click();
            }} else {{
                var firstBtn = document.querySelector('.umai-tablinks');
                if(firstBtn) firstBtn.click();
            }}
        }})();
        </script>
        """

        st.session_state["full_output_log"] = full_output_log
        st.session_state["full_html_log"] = full_html_log

if "full_html_log" in st.session_state and st.session_state["full_html_log"]:
    st.markdown("## 📋 一括出力結果")
    tab1, tab2 = st.tabs(["📝 プレーンテキスト", "🌐 ブログ用HTML"])
    with tab1:
        st.text_area("コピペ用テキスト", st.session_state["full_output_log"], height=300)
        render_copy_button(st.session_state["full_output_log"], "全文コピー", "txt_copy_all")
    with tab2:
        st.markdown("### HTMLプレビュー")
        components.html(st.session_state["full_html_log"], height=800, scrolling=True)
        
        st.download_button(
            label="📥 HTMLファイルをダウンロードする",
            data=st.session_state["full_html_log"],
            file_name="race_prediction.html",
            mime="text/html",
            use_container_width=True,
            type="primary"
        )

if __name__ == '__main__':
    pass
