import streamlit as st
import streamlit.components.v1 as components
import math
import re
import json
from datetime import datetime

# ================= 核心算法 =================
def find_best_plan(orders, ordered_sizes, min_layers, max_layers, max_overage_pct, max_shortage_pct, max_ratio_sum, max_markers, max_sizes_per_marker, allow_large_to_small, allow_shortage, global_orders=None):
    if global_orders is None:
        global_orders = orders
        
    sizes = [s for s in ordered_sizes if s in orders and orders[s] > 0]
    
    best_waste = float('inf')
    best_plan = None
    best_markers = None
    
    if allow_large_to_small:
        process_sizes = list(reversed(sizes))
    else:
        process_sizes = sizes
    
    for L1 in range(min_layers, max_layers + 1):
        for L2 in range(L1, max_layers + 1):
            current_waste = 0
            plan_ratios = {}
            possible = True
            inherited_excess = 0 
            
            for size in process_sizes:
                target = orders[size]
                max_allowed = math.floor(global_orders[size] * (1 + max_overage_pct))
                
                if allow_shortage:
                    allowed_short = math.floor(target * max_shortage_pct)
                    base_target = max(1, target - allowed_short) if target > 0 else 0
                else:
                    base_target = target
                
                if allow_large_to_small:
                    net_target = max(0, base_target - inherited_excess)
                    max_prod_allowed = max(0, max_allowed - inherited_excess)
                    
                    if net_target == 0 and max_prod_allowed == 0:
                        plan_ratios[size] = [0, 0]
                        inherited_excess = max(0, inherited_excess - target)
                        continue
                else:
                    net_target = base_target
                    max_prod_allowed = max_allowed
                
                min_waste_for_size = float('inf')
                best_r1, best_r2 = -1, -1
                
                max_r1 = (max_prod_allowed // L1) + 1 if L1 > 0 else 0
                for r1 in range(max_r1 + 1):
                    if r1 > max_ratio_sum:
                        continue
                        
                    rem = net_target - r1 * L1
                    r2 = 0 if rem <= 0 else math.ceil(rem / L2)
                    
                    if r2 > max_ratio_sum:
                        continue
                        
                    produced = r1 * L1 + r2 * L2
                    total_available = produced + (inherited_excess if allow_large_to_small else 0)
                    
                    if base_target <= total_available <= max_allowed:
                        waste = total_available - base_target 
                        if waste < min_waste_for_size:
                            min_waste_for_size = waste
                            best_r1, best_r2 = r1, r2
                            
                if best_r1 == -1:
                    possible = False
                    break
                else:
                    plan_ratios[size] = [best_r1, best_r2]
                    if allow_large_to_small:
                        actual_produced = best_r1 * L1 + best_r2 * L2
                        total_physical = actual_produced + inherited_excess
                        inherited_excess = max(0, total_physical - target)
                    else:
                        current_waste += min_waste_for_size
                    
            if possible:
                if allow_large_to_small:
                    current_waste = inherited_excess
                
                temp_markers = []
                layers_list = [L1, L2]
                
                for i, L in enumerate(layers_list):
                    rem_counts = {size: plan_ratios[size][i] for size in sizes if plan_ratios[size][i] > 0}
                    bins = []
                    active_sizes = sorted([s for s in rem_counts.keys()], key=lambda s: ordered_sizes.index(s))

                    while any(c > 0 for c in rem_counts.values()):
                        current_bin = {'layers': L, 'ratios': {}, 'sum': 0}
                        toggle = True 
                        
                        while True:
                            valid_sizes = []
                            for s in active_sizes:
                                if rem_counts[s] > 0:
                                    is_sum_ok = (current_bin['sum'] + 1 <= max_ratio_sum)
                                    if is_sum_ok:
                                        if s in current_bin['ratios'] or len(current_bin['ratios']) < max_sizes_per_marker:
                                            valid_sizes.append(s)
                            
                            if not valid_sizes:
                                break 
                                
                            chosen_size = valid_sizes[-1] if toggle else valid_sizes[0]
                                
                            current_bin['ratios'][chosen_size] = current_bin['ratios'].get(chosen_size, 0) + 1
                            current_bin['sum'] += 1
                            rem_counts[chosen_size] -= 1
                            
                            toggle = not toggle 
                            
                        if current_bin['sum'] > 0:
                            bins.append(current_bin)
                        else:
                            break 
                            
                    temp_markers.extend(bins)
                
                if len(temp_markers) <= max_markers:
                    if current_waste < best_waste:
                        best_waste = current_waste
                        best_plan = {'L1': L1, 'L2': L2, 'ratios': plan_ratios}
                        best_markers = temp_markers

    return sizes, best_markers

def generate_html_table(sizes, initial_orders, markers, style_no="", color="", cut_type="", layout_dir="", special_process="", overage_pct=0, shortage_pct=0, allow_large_to_small=False, idx_str=""):
    date_str = datetime.now().strftime("%Y年%m月%d日")
    
    sizes_js = [str(s) for s in sizes]
    initial_orders_js = {str(s): initial_orders[s] for s in sizes}
    
    table_html = '<table style="width:100%; text-align:center; border-collapse: collapse; font-family: sans-serif; font-size: 16px;">'
    
    header_parts = []
    if style_no.strip(): header_parts.append(f'🏷️ 款号：<span style="color:#c00;">{style_no.strip()}</span>')
    if color.strip(): header_parts.append(f'🎨 颜色：<span style="color:#0066cc;">{color.strip()}</span>')
    if cut_type.strip(): header_parts.append(f'✂️ 裁片：{cut_type.strip()}')
    header_parts.append(f'↕️ 排版：<span style="border-bottom: 2px solid #000;">{layout_dir}</span>')
    
    display_special = special_process.strip() if special_process.strip() else "常规"
    if allow_large_to_small:
        if display_special == "常规": display_special = "大改小抵扣"
        else: display_special += " (大改小抵扣)"
    header_parts.append(f'✨ 工艺：<span style="color:#e65c00;">{display_special}</span>')

    header_content = " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(header_parts)

    table_html += f'<tr><td colspan="{len(sizes) + 2}" contenteditable="true" style="text-align:left; font-size:16px; font-weight:bold; padding:12px 10px; border-bottom: 2px solid #333; background-color: #fff3cd; cursor: text; line-height: 1.6;">'
    table_html += header_content
    table_html += f'<span style="float:right; font-size:15px; font-weight:normal; color:#555;">📅 日期：{date_str}</span>'
    table_html += '</td></tr>'

    table_html += '<tr style="border-bottom: 2px solid #ccc; background-color: #f8f9fa;">'
    for s in sizes: table_html += f'<th style="padding: 10px;">{s}</th>'
    table_html += '<th style="padding: 10px;">层数</th><th style="padding: 10px;">配比和</th></tr>'

    current_remains = [initial_orders[s] for s in sizes]
    table_html += '<tr>'
    for r in current_remains: table_html += f'<td style="padding: 8px;">{r}</td>'
    table_html += '<td></td><td></td></tr>'

    has_global_overage = False
    has_global_shortage = False
    auto_note_text = ""

    for marker_idx, marker in enumerate(markers):
        is_last_row = (marker_idx == len(markers) - 1)
        is_priority = marker.get('is_priority', False)
        is_tail = marker.get('is_tail', False) 
        
        row_class = "marker-data-row is-tail-row" if is_tail else "marker-data-row"
        
        if is_tail:
            bg_color = "#fff0f5" 
            badge = f'<br><span style="font-size:11px; color:#c00055; font-weight:bold;">🔥清尾加层<br>(同第{marker.get("source_idx", 1)}版)</span>'
            sum_bg = "#ffe4e1"
        elif is_priority:
            bg_color = "#fff2f2"
            badge = '<br><span style="font-size:11px; color:#cc0000; font-weight:normal;">⚡优先</span>'
            sum_bg = "#ffe6e6"
        else:
            bg_color = "#fdfdfd"
            badge = ''
            sum_bg = "#f0f8ff"
        
        table_html += f'<tr class="{row_class}" style="font-weight: bold; background-color: {bg_color};">'
        for s in sizes:
            r = marker['ratios'].get(s, 0)
            text_r = str(r) if r > 0 else ""
            table_html += f'<td contenteditable="true" class="ratio-cell" data-size="{s}" style="color: red; padding: 8px; cursor: text;">{text_r}</td>'
        
        if is_tail:
            table_html += f'<td contenteditable="true" class="layer-cell" style="color: #c00055; font-weight:bold; background-color: #ffebf0; padding: 8px; cursor: text;" title="双击输入师傅实际拉的层数">{marker["layers"]}</td>'
        else:
            table_html += f'<td contenteditable="true" class="layer-cell" style="color: #003399; padding: 8px; cursor: text;">{marker["layers"]}</td>'
            
        sum_val = marker['sum']
        text_sum = str(sum_val) if sum_val != "" else ""
        table_html += f'<td class="sum-cell" style="color: #003399; padding: 8px; background-color: {sum_bg};"><span class="sum-number">{text_sum}</span>{badge}</td></tr>'

        table_html += '<tr class="marker-remain-row" style="border-bottom: 1px solid #eee;">'
        
        display_remains = list(current_remains)
        for i, s in enumerate(sizes):
            display_remains[i] -= marker['ratios'].get(s, 0) * marker['layers']
            
        current_remains = list(display_remains)

        for i, s in enumerate(sizes):
            remain_val = display_remains[i]
            max_allowed_extra = math.floor(initial_orders[s] * (overage_pct / 100.0))
            max_allowed_short = math.floor(initial_orders[s] * (shortage_pct / 100.0))
            
            if is_last_row:
                if remain_val < 0:
                    display_text = str(remain_val)
                    text_color = "#cc0000" if abs(remain_val) > max_allowed_extra else "#e65c00" 
                    font_weight = "bold"
                elif remain_val > 0:
                    display_text = str(remain_val)
                    text_color = "#003399" if remain_val > max_allowed_short else "#0066cc" 
                    font_weight = "bold"
                else:
                    display_text = "0"
                    text_color = "#28a745" 
                    font_weight = "bold"
            else:
                display_text = str(remain_val)
                text_color = "#000"
                font_weight = "normal"
                
            table_html += f'<td class="remain-cell" data-size="{s}" style="padding: 8px; background-color: #fafafa; color: {text_color}; font-weight: {font_weight};">{display_text}</td>'
        table_html += '<td></td><td></td></tr>'
        
    substitutions_map = {s: [] for s in sizes}
    final_display_remains = list(current_remains)
    
    if allow_large_to_small:
        for i in range(len(sizes) - 1, 0, -1):
            if final_display_remains[i] < 0:
                excess = abs(final_display_remains[i])
                for j in range(i - 1, -1, -1):
                    if final_display_remains[j] > 0:
                        fill = min(excess, final_display_remains[j])
                        final_display_remains[j] -= fill
                        final_display_remains[i] += fill
                        excess -= fill
                        
                        substitutions_map[sizes[i]].append(f"↘改{sizes[j]}码({fill})")
                        auto_note_text += f"{sizes[i]}码改{sizes[j]}码({fill}件)；"
                        
                    if excess == 0:
                        break
                        
    table_html += '<tr id="final-overcut-row" style="background-color: #fff7e6; border-top: 2px solid #666; border-bottom: 2px solid #666;">'
    for i, s in enumerate(sizes):
        raw_val = current_remains[i] 
        net_val = final_display_remains[i] 
        max_allowed_extra = math.floor(initial_orders[s] * (overage_pct / 100.0))
        max_allowed_short = math.floor(initial_orders[s] * (shortage_pct / 100.0))
        
        cell_html = ""
        
        if raw_val < 0:
            extra = abs(raw_val)
            txt_color = "#cc0000" if extra > max_allowed_extra else "#e65c00"
            warn = f"<br><span style='font-size:12px;color:#cc0000; font-weight:normal;'>(超溢装{overage_pct}%)</span>" if extra > max_allowed_extra else ""
            cell_html += f"<div style='font-size:16px; font-weight:bold; color:{txt_color};'>增裁{extra}{warn}</div>"
            if extra > max_allowed_extra:
                has_global_overage = True
        
        elif net_val > 0:
            short = net_val
            txt_color = "#003399" if short > max_allowed_short else "#0066cc"
            warn = f"<br><span style='font-size:12px;color:#003399; font-weight:normal;'>(超短缺{shortage_pct}%)</span>" if short > max_allowed_short else ""
            cell_html += f"<div style='font-size:16px; font-weight:bold; color:{txt_color};'>少裁{short}{warn}</div>"
            if short > max_allowed_short:
                has_global_shortage = True
                
        for msg in substitutions_map[s]:
            cell_html += f"<div style='font-size:13px; font-weight:bold; color:#0066cc; margin-top:6px;'>{msg}</div>"
            
        table_html += f'<td class="final-overcut-cell" data-size="{s}" style="padding: 12px 8px; vertical-align: top;">{cell_html}</td>'
            
    table_html += '<td colspan="2" style="padding: 12px 8px; color: #555; font-size: 15px; vertical-align: middle; font-weight: bold; text-align: left;">👈 实际增/减裁汇总</td></tr>'
    
    table_html += '</table>'

    display_style_overage = "block" if has_global_overage else "none"
    table_html += f'<div id="overage-warning-{idx_str}" style="display: {display_style_overage}; color: #cc0000; font-weight: bold; margin-top: 15px; padding: 10px; background-color: #ffe6e6; border: 1px solid #ffcccc; border-radius: 4px; text-align: center;">⚠️ 警告：当前排版方案中，部分尺码（深红色）的增裁件数已超出设定的 {overage_pct}% 溢装率上限！</div>'
    
    display_style_shortage = "block" if has_global_shortage else "none"
    table_html += f'<div id="shortage-warning-{idx_str}" style="display: {display_style_shortage}; color: #003399; font-weight: bold; margin-top: 10px; padding: 10px; background-color: #e6f0ff; border: 1px solid #b3d1ff; border-radius: 4px; text-align: center;">⚠️ 警告：当前排版方案中，部分尺码（深蓝色）的少裁件数已超出设定的 {shortage_pct}% 短装率下限！</div>'

    # 🌟 修复：完整拼接全部文件名信息
    filename_parts = []
    if style_no.strip(): filename_parts.append(style_no.strip())
    else: filename_parts.append("大货排料单")
    if color.strip(): filename_parts.append(color.strip())
    if cut_type.strip(): filename_parts.append(cut_type.strip())
    if special_process.strip(): filename_parts.append(special_process.strip())
    filename_parts.append(date_str)
    
    raw_filename = "_".join(filename_parts)
    safe_filename = re.sub(r'[\\/*?:"<>|#]', "", raw_filename)
    filename = safe_filename + ".png"

    full_wrapper = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
        <style>
            .dl-btn {{ background-color: #0066cc; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-size: 14px; font-weight: bold; margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); transition: 0.3s; }}
            .dl-btn:hover {{ background-color: #004c99; }}
            .hint-box {{ background-color: #eef6fc; color: #004085; padding: 12px 16px; border-radius: 4px; margin-bottom: 15px; font-family: sans-serif; font-size: 14px; border: 1px solid #b8daff; border-left: 4px solid #0066cc; }}
            #capture-area {{ background-color: white; padding: 15px; border-radius: 5px; }}
            td[contenteditable="true"]:hover {{ background-color: #e6f7ff !important; outline: 2px dashed #1890ff; border-radius: 2px; }}
            .remark-input:hover {{ background-color: #f8f9fa; }}
            .remark-input:focus {{ background-color: #fff; border-bottom: 1px dashed #0066cc; }}
            .remark-input:empty:before {{ content: attr(placeholder); color: #aaa; pointer-events: none; display: block; }}
        </style>
    </head>
    <body style="margin: 0; padding: 0;">
        <button class="dl-btn" onclick="takeShot()">📸 保存为高清图片 (文件名: {filename})</button>
        
        <div class="hint-box">
            🖱️ <b>功能提示：</b>双击红/蓝数字即可微调。<br>带有 <b style="color:#c00;">⚡优先</b> 或 <b style="color:#c00055;">🔥清尾</b> 标记的版请车间重点关注；修改层数后，底部结余会自动重算联动！
        </div>

        <div id="capture-area">
            {table_html}
            
            <div style="margin-top: 20px; text-align: left; font-size: 16px; padding: 0 5px; display: flex; align-items: flex-end;">
                <b style="color: #333; white-space: nowrap;">📝 备注：</b>
                <span id="auto-note" style="color: #0066cc; font-weight: bold;">{auto_note_text}</span>
                <div contenteditable="true" class="remark-input" style="flex-grow: 1; border-bottom: 1px solid #aaa; outline: none; padding: 0 5px; color: #333; cursor: text;" placeholder="(点击此处可继续补充手动备注...)"></div>
            </div>
        </div>
        
        <script>
            const sizes = {json.dumps(sizes_js)};
            const initialOrders = {json.dumps(initial_orders_js)};
            const overagePct = {overage_pct};
            const shortagePct = {shortage_pct};
            const allowLargeToSmall = {str(allow_large_to_small).lower()};

            function recalculate() {{
                let currentRemains = JSON.parse(JSON.stringify(initialOrders));
                const dataRows = document.querySelectorAll('.marker-data-row');
                const remainRows = document.querySelectorAll('.marker-remain-row');
                
                let hasGlobalOverage = false; 
                let hasGlobalShortage = false; 

                dataRows.forEach((row, index) => {{
                    let isLastRow = (index === dataRows.length - 1);
                    
                    let ratioSum = 0;
                    let layerText = row.querySelector('.layer-cell').innerText.trim();
                    let layers = parseInt(layerText) || 0;

                    sizes.forEach(size => {{
                        let ratioCell = row.querySelector(`.ratio-cell[data-size="` + size + `"]`);
                        let ratioText = ratioCell.innerText.trim();
                        let ratio = parseInt(ratioText) || 0;
                        ratioSum += ratio;
                        currentRemains[size] -= (ratio * layers);
                    }});

                    let sumNumEl = row.querySelector('.sum-number');
                    if (sumNumEl) {{
                        sumNumEl.innerText = ratioSum > 0 ? ratioSum : "";
                    }}

                    let remainRow = remainRows[index];
                    let displayRemains = JSON.parse(JSON.stringify(currentRemains));
                    
                    sizes.forEach(size => {{
                        let remainCell = remainRow.querySelector(`.remain-cell[data-size="` + size + `"]`);
                        let rVal = displayRemains[size];
                        let maxAllowedExtra = Math.floor(initialOrders[size] * (overagePct / 100.0));
                        let maxAllowedShort = Math.floor(initialOrders[size] * (shortagePct / 100.0));
                        
                        remainCell.innerText = rVal; 
                        
                        if (isLastRow) {{
                            if (rVal < 0) {{
                                remainCell.style.color = (Math.abs(rVal) > maxAllowedExtra) ? "#cc0000" : "#e65c00";
                            }} else if (rVal > 0) {{
                                remainCell.style.color = (rVal > maxAllowedShort) ? "#003399" : "#0066cc"; 
                            }} else {{
                                remainCell.style.color = "#28a745"; 
                            }}
                            remainCell.style.fontWeight = "bold";
                        }} else {{
                            remainCell.style.color = "#000";
                            remainCell.style.fontWeight = "normal";
                        }}
                    }});
                }});
                
                let finalRemains = JSON.parse(JSON.stringify(currentRemains));
                let subMap = {{}};
                let autoNoteArr = [];
                sizes.forEach(s => subMap[s] = []);
                
                if (allowLargeToSmall) {{
                    for (let i = sizes.length - 1; i > 0; i--) {{
                        let sLarge = sizes[i];
                        if (finalRemains[sLarge] < 0) {{
                            let excess = Math.abs(finalRemains[sLarge]);
                            for (let j = i - 1; j >= 0; j--) {{
                                let sSmall = sizes[j];
                                if (finalRemains[sSmall] > 0) {{
                                    let fill = Math.min(excess, finalRemains[sSmall]);
                                    finalRemains[sSmall] -= fill;
                                    finalRemains[sLarge] += fill;
                                    excess -= fill;
                                    
                                    subMap[sLarge].push("↘改" + sSmall + "码(" + fill + ")");
                                    autoNoteArr.push(sLarge + "码改" + sSmall + "码(" + fill + "件)");
                                }}
                                if (excess === 0) break;
                            }}
                        }}
                    }}
                    
                    let noteEl = document.getElementById("auto-note");
                    if(noteEl) {{
                        noteEl.innerText = autoNoteArr.length > 0 ? (autoNoteArr.join("；") + "  ") : "";
                    }}
                }}

                sizes.forEach(size => {{
                    let finalCell = document.querySelector(`.final-overcut-cell[data-size="` + size + `"]`);
                    let rawVal = currentRemains[size];
                    let netVal = finalRemains[size];
                    let maxAllowedExtra = Math.floor(initialOrders[size] * (overagePct / 100.0));
                    let maxAllowedShort = Math.floor(initialOrders[size] * (shortagePct / 100.0));
                    
                    let cellHtml = "";
                    
                    if (rawVal < 0) {{
                        let extra = Math.abs(rawVal);
                        let txtColor = (extra > maxAllowedExtra) ? "#cc0000" : "#e65c00";
                        let warn = (extra > maxAllowedExtra) ? `<br><span style='font-size:12px;color:#cc0000; font-weight:normal;'>(超溢装${{overagePct}}%)</span>` : "";
                        cellHtml += `<div style='font-size:16px; font-weight:bold; color:${{txtColor}};'>增裁${{extra}}${{warn}}</div>`;
                        if (extra > maxAllowedExtra) hasGlobalOverage = true;
                        
                    }} else if (netVal > 0) {{ 
                        let short = netVal;
                        let txtColor = (short > maxAllowedShort) ? "#003399" : "#0066cc";
                        let warn = (short > maxAllowedShort) ? `<br><span style='font-size:12px;color:#003399; font-weight:normal;'>(超短缺${{shortagePct}}%)</span>` : "";
                        cellHtml += `<div style='font-size:16px; font-weight:bold; color:${{txtColor}};'>少裁${{short}}${{warn}}</div>`;
                        if (short > maxAllowedShort) hasGlobalShortage = true;
                    }}
                    
                    subMap[size].forEach(msg => {{
                        cellHtml += `<div style='font-size:13px; font-weight:bold; color:#0066cc; margin-top:6px;'>${{msg}}</div>`;
                    }});
                    
                    finalCell.innerHTML = cellHtml;
                }});

                let warningBoxOv = document.getElementById('overage-warning-{idx_str}');
                if (warningBoxOv) warningBoxOv.style.display = hasGlobalOverage ? 'block' : 'none';
                
                let warningBoxSh = document.getElementById('shortage-warning-{idx_str}');
                if (warningBoxSh) warningBoxSh.style.display = hasGlobalShortage ? 'block' : 'none';
            }}

            document.querySelectorAll('.ratio-cell, .layer-cell').forEach(cell => {{
                cell.addEventListener('input', recalculate);
            }});

            function takeShot() {{
                const el = document.getElementById('capture-area');
                html2canvas(el, {{ scale: 2, backgroundColor: "#ffffff" }}).then(canvas => {{
                    let link = document.createElement('a');
                    link.download = '{filename}';
                    link.href = canvas.toDataURL("image/png");
                    link.click();
                }});
            }}
        </script>
    </body>
    </html>
    """
    return full_wrapper

# ================= 网页 UI 设计 =================
st.set_page_config(page_title="蓉成服饰排料系统", layout="wide")

with st.sidebar.expander("📖 蓉成服饰排料系统 · 帮助指南", expanded=False):
    st.markdown("""
**1️⃣ 核心排料逻辑：为什么是“大码套小码”？**
为了追求极致的面料利用率，系统在计算排版时，默认采用了 **“大码套小码 (首尾穿插套排)”** 的智能逻辑。系统会优先抓取一个最大码配一个最小码，将它们穿插组合。这样大片与小片互补，不仅能让排料图极其紧凑，还能保证每拉一床布，产出的尺码分布更加均匀。

**2️⃣ 灵活控层：如何控制拉布层数与画样长度？**
* **面料太厚？** 当【最高层数】被限制得很低（如30层）时，系统会自动 **增加单版配比和** （把版画长一点）来凑够件数。
* **裁床太短？** 你可以设置【配比和上限】（如限制一版最多画7件）。此时系统会自动 **增加拉布层数** 。
* 💡 **秘诀**：手动微调表格时，直接双击蓝色的“层数”或红色的“配比”，底部结余会自动重算。

**3️⃣ “大改小”功能：借件抵扣的妙用与禁忌**
开启「大改小」后，大码多裁的废布会被直接利用填补小码的缺口，底部会生成蓝字 `↘改XX码`。
* ⚠️ **核心警告（极度重要）** ：“大改小”功能 **仅适用于常规可自由改刀的对称裁片** ！如果当前款式属于：**1.不对称花型 / 2.条格面料（对条对格） / 3.极度不规则裁片**，请 **务必关闭** 此功能！

**4️⃣ 优先急单：既要赶进度，又要省面料**
如果车间急需某些尺码先上线，请勾选侧边栏的【优先急单】。系统 **不会** 为了急单去单独拉1层、2层布，而是会在全局最优的厚层大版中，直接把 **刚好包含你急需尺码的大货版** 抽调并置顶，带有 `⚡优先` 标记的版请优先安排拉布！

**5️⃣ 面料不足模式（允许短装）：来料不够怎么排？**
当遇到面料来料不足，或瑕疵太多导致无法凑齐完整订单时，请使用此功能。
* **等比例平衡缩减**：系统不再“宁超勿缺”，而是会在你允许的短缺范围内，**将所有尺码等比例缩减** （尽可能少排件数）以最大化节省面料。底部汇总行会用蓝色标出少裁的数量。
* **死守底线**：系统绝对遵守“不断码”红线。即便短装率设得很高，任何有订单的尺码都 **至少会产出 1 件** 。
* **终极省布组合**：如果同时开启【大改小】和【面料不足】，系统会利用大码余量补小码，结合整体缩减，把有限的面料抠出最大价值！

**6️⃣ 面料清尾建议：布多了怎么顺手用掉？**
实际车间里，为了一点尾料重新画版极其浪费。勾选该面料参数里的【面料清尾】，选择你想多要的尺码，系统会自动从算好的大货版中，挑出 **最合适的一版原版画样** 复制到表格最下方。师傅无需新画麦架，直接用原版多拉几层即可！
""")
    
st.sidebar.markdown("---")
num_cuts = st.sidebar.number_input("⚙️ 需要计算的面料/裁片种类数：", min_value=1, max_value=5, value=1, step=1, help="例如大身、袖子两种面料需分别控层，这里选 2。")

st.sidebar.markdown("---")
st.sidebar.subheader("⏱️ 优先急单设置 (选填)")
enable_priority = st.sidebar.checkbox("✨ 启用优先急单 (置顶急需尺码)")
priority_orders = {}

with st.sidebar.expander("📌 笛莎合同短溢装标准参考", expanded=True):
    st.markdown("""
    **(按订单总件数划分)**
    * **300-500件**：溢装 ≤ 10% | 短缺 ≤ 8%
    * **501-1000件**：溢装 ≤ 5% | 短缺 ≤ 5%
    * **1001-3000件**：溢装 ≤ 5% | 短缺 ≤ 2.5%
    * **3001-5000件**：溢装 ≤ 3% | 短缺 ≤ 1.5%
    * **5001-10000件**：溢装 ≤ 1.5% | 短缺 ≤ 0.8%
    * **10000件以上**：溢装 ≤ 1% | 短缺 ≤ 0.4%
    
    ⚠️ **核心红线**：
    1. 任何情况的短缺**均不得断码**！
    2. 超出溢装比例的货品**系统不予结算**，全部费用乙方承担。
    """)

st.title("✂️ 蓉成服饰智能排料系统 (多面料专属版)")
st.markdown("一次录入全局订单需求，分别为不同的裁片独立计算、独立排版。")

st.subheader("📝 步骤 1：全局款式与尺码信息")

col_style, col_color, col_layout, col_special = st.columns(4)
with col_style:
    style_no = st.text_input("👗 款号 (选填)：", placeholder="RC-001")
with col_color:
    color = st.text_input("🎨 颜色 (选填)：", placeholder="藏青色")
with col_layout:
    layout_dir = st.selectbox("↕️ 排列方式：", options=["任意", "同码同向", "件份同向", "同一方向"], index=1)
with col_special:
    special_process = st.text_input("✨ 特殊工艺 (选填)：", placeholder="如: 加衬/对条/手拉")

size_input = st.text_input(
    "👉 请输入这批货的所有尺码名称（用空格隔开）：", 
    value="90 100 110 120 130 140"
)

raw_sizes = re.split(r'[,，\s、\-]+', size_input.strip())
sizes_list = []
for s in raw_sizes:
    if s and s not in sizes_list:
        sizes_list.append(s)

st.subheader("📦 步骤 2：录入各尺码订单件数")
orders = {}

if sizes_list:
    cols = st.columns(min(len(sizes_list), 6))
    for i, size in enumerate(sizes_list):
        with cols[i % 6]:
            val = st.number_input(f"【 {size} 】码件数", min_value=0, value=0, step=10, key=f"size_{size}")
            if val > 0:
                orders[size] = val
else:
    st.warning("请在上方输入至少一个尺码！")

if enable_priority:
    st.sidebar.info("💡 提示：系统会将包含你急需尺码的大货版直接置顶。")
    pri_sizes = st.sidebar.multiselect("👉 选择急需先裁的尺码：", options=[s for s in sizes_list if orders.get(s, 0) > 0])
    if pri_sizes:
        for size in pri_sizes:
            max_v = orders.get(size, 0)
            p_val = st.sidebar.number_input(f"【 {size} 】件数", min_value=0, max_value=max_v, value=min(max_v, 50), step=10, key=f"pri_{size}")
            if p_val > 0:
                priority_orders[size] = p_val

st.write("---")

st.subheader(f"✂️ 步骤 3：各面料独立排版与计算 (共 {int(num_cuts)} 种)")
st.info("💡 提示：在此处分别为不同面料设定厚度限制，并**独立点击计算按钮**，各版计算结果互不干扰！")

tabs = st.tabs([f"裁片 {i+1}" for i in range(int(num_cuts))])

for i, tab in enumerate(tabs):
    with tab:
        # 🌟 修复：默认值不再含有空格
        default_cut_name = f"裁片{i+1}"
        cut_name = st.text_input(f"🏷️ 此面料/裁片名称：", value=default_cut_name, key=f"c_name_{i}")
        
        st.markdown("##### ⚙️ 基础限高参数")
        c1, c2, c3, c4 = st.columns(4)
        with c1: c_min_layers = st.number_input("最低层数", min_value=1, value=1, key=f"c_minL_{i}")
        with c2: c_max_layers = st.number_input("最高层数", min_value=0, value=0, key=f"c_maxL_{i}") 
        with c3: c_ov_pct = st.number_input("溢装率 (%)", min_value=0, value=5, key=f"c_ov_{i}")
        with c4: c_sh_pct = st.number_input("允许短装率 (%)", min_value=0, value=0, key=f"c_sh_{i}")
        
        st.markdown("##### 📏 画样版长限制")
        c5, c6, c7 = st.columns(3)
        with c5: c_rs = st.number_input("配比和上限", min_value=0, value=0, key=f"c_rs_{i}")
        with c6: c_mm = st.number_input("总版数上限", min_value=0, value=0, key=f"c_mm_{i}")
        with c7: c_spm = st.number_input("单版最多尺码数", min_value=0, value=0, key=f"c_spm_{i}")
        
        st.markdown("##### 🧠 高级智能规则")
        c8, c9 = st.columns(2)
        with c8:
            c_l2s = st.checkbox(f"✨ 允许「大改小」平账", value=False, key=f"c_l2s_{i}")
        with c9:
            c_sh = st.checkbox(f"✂️ 启用「面料不足模式」(优先少裁)", value=False, key=f"c_sh_mode_{i}")
            
        st.markdown("##### 🔥 此面料清尾计划")
        c_tail = st.checkbox(f"生成「原版加层清尾」提示", value=False, key=f"c_tail_{i}")
        c_tail_sizes = []
        if c_tail:
            c_tail_sizes = st.multiselect("👉 选择需清尾出件的尺码：", options=sizes_list, key=f"c_ts_{i}")
            
        st.write("")
        
        if st.button(f"🚀 单独计算【{cut_name}】排版", type="primary", use_container_width=True, key=f"btn_{i}"):
            if not orders:
                st.session_state[f'res_err_{i}'] = "❌ 请至少在【步骤2】填写一个尺码的订单需求！"
                st.session_state[f'res_html_{i}'] = None
            elif c_max_layers <= 0:
                st.session_state[f'res_err_{i}'] = f"❌ 【{cut_name}】的【最高允许层数】当前为 0，请手动设置一个有效的限制高度！"
                st.session_state[f'res_html_{i}'] = None
            elif c_rs <= 0 or c_mm <= 0 or c_spm <= 0:
                st.session_state[f'res_err_{i}'] = f"❌ 【{cut_name}】的【画样版长限制】（配比和、总版数、单版尺码数）当前为 0，请手动设置实际参数！"
                st.session_state[f'res_html_{i}'] = None
            else:
                with st.spinner(f"电脑正在为您计算【{cut_name}】的最佳排版，请稍候..."):
                    valid_sizes, markers = find_best_plan(
                        orders, sizes_list, c_min_layers, c_max_layers, 
                        c_ov_pct/100.0, c_sh_pct/100.0, 
                        c_rs, c_mm, c_spm, 
                        c_l2s, c_sh
                    )
                    
                    if markers is not None:
                        if enable_priority and priority_orders:
                            priority_markers = []
                            normal_markers = markers.copy()
                            current_yield = {s: 0 for s in priority_orders}
                            
                            while normal_markers:
                                all_met = True
                                for s, target in priority_orders.items():
                                    if current_yield[s] < target:
                                        all_met = False
                                        break
                                if all_met:
                                    break
                                    
                                best_idx = -1
                                best_score = -1
                                
                                for idx_m, m in enumerate(normal_markers):
                                    score = 0
                                    for s, target in priority_orders.items():
                                        needed = max(0, target - current_yield[s])
                                        provided = m['ratios'].get(s, 0) * m['layers']
                                        score += min(needed, provided)
                                        
                                    if score > best_score:
                                        best_score = score
                                        best_idx = idx_m
                                        
                                if best_score == 0:
                                    break 
                                    
                                chosen = normal_markers.pop(best_idx)
                                chosen['is_priority'] = True
                                priority_markers.append(chosen)
                                
                                for s in priority_orders:
                                    current_yield[s] += chosen['ratios'].get(s, 0) * chosen['layers']
                                    
                            for m in normal_markers:
                                m['is_priority'] = False
                                
                            markers = priority_markers + normal_markers
                        else:
                            for m in markers:
                                m['is_priority'] = False
                                
                        if c_tail and c_tail_sizes:
                            best_idx = -1
                            best_score = -1
                            best_sum = float('inf')
                            
                            for idx_m, m in enumerate(markers):
                                target_count = sum(m['ratios'].get(s, 0) for s in c_tail_sizes)
                                if target_count == 0: continue
                                
                                score = target_count / m['sum']
                                if score > best_score or (score == best_score and m['sum'] < best_sum):
                                    best_score = score
                                    best_idx = idx_m
                                    best_sum = m['sum']
                            
                            if best_idx != -1:
                                tail_marker = {
                                    'layers': 0, 
                                    'ratios': markers[best_idx]['ratios'].copy(),
                                    'sum': markers[best_idx]['sum'],
                                    'is_tail': True,
                                    'source_idx': best_idx + 1 
                                }
                                markers.append(tail_marker)
                            else:
                                st.warning(f"⚠️ {cut_name} 提示：算出的画样中没有包含您指定的清尾尺码。")
                                
                    if markers:
                        total_produced = sum(m['sum'] * m['layers'] for m in markers if not m.get('is_tail', False))
                        msg = f"✅ 【{cut_name}】排版完毕！共使用了 **{len([m for m in markers if not m.get('is_tail')])}** 个大货版。 产出 **{total_produced}** 件。"
                        
                        html_c = generate_html_table(
                            valid_sizes, orders, markers, style_no, color, cut_name, layout_dir, special_process, 
                            c_ov_pct, c_sh_pct, c_l2s, idx_str=str(i)
                        )
                        st.session_state[f'res_err_{i}'] = None
                        st.session_state[f'res_msg_{i}'] = msg
                        st.session_state[f'res_html_{i}'] = html_c
                    else:
                        st.session_state[f'res_err_{i}'] = f"❌ 【{cut_name}】在当前的严苛限制下，未找到不超标的方案。请尝试放宽对应的限制条件（如总版数上限）。"
                        st.session_state[f'res_msg_{i}'] = None
                        st.session_state[f'res_html_{i}'] = None

        if st.session_state.get(f'res_err_{i}'):
            st.error(st.session_state[f'res_err_{i}'])
        if st.session_state.get(f'res_msg_{i}'):
            st.success(st.session_state[f'res_msg_{i}'])
            st.subheader(f"📊 【{cut_name}】阶梯式扣减排料单")
            components.html(st.session_state[f'res_html_{i}'], height=850, scrolling=True)
