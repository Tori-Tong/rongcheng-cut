import streamlit as st
import streamlit.components.v1 as components
import math
import re
import json
from datetime import datetime

# ================= 核心算法 =================
def find_best_plan(orders, ordered_sizes, min_layers, max_layers, max_overage_pct, max_ratio_sum, max_markers, max_sizes_per_marker, allow_large_to_small):
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
                max_allowed = math.floor(target * (1 + max_overage_pct))
                
                if allow_large_to_small:
                    net_target = max(0, target - inherited_excess)
                    max_prod_allowed = max(0, max_allowed - inherited_excess)
                    
                    if net_target == 0:
                        plan_ratios[size] = [0, 0]
                        inherited_excess = inherited_excess - target
                        continue
                else:
                    net_target = target
                    max_prod_allowed = max_allowed
                
                min_waste_for_size = float('inf')
                best_r1, best_r2 = -1, -1
                
                max_r1 = (max_prod_allowed // L1) + 1 if L1 > 0 else 0
                for r1 in range(max_r1 + 1):
                    if max_ratio_sum > 0 and r1 > max_ratio_sum:
                        continue
                        
                    rem = net_target - r1 * L1
                    r2 = 0 if rem <= 0 else math.ceil(rem / L2)
                    
                    if max_ratio_sum > 0 and r2 > max_ratio_sum:
                        continue
                        
                    produced = r1 * L1 + r2 * L2
                    total_available = produced + (inherited_excess if allow_large_to_small else 0)
                    
                    if target <= total_available <= max_allowed:
                        waste = total_available - target
                        if waste < min_waste_for_size:
                            min_waste_for_size = waste
                            best_r1, best_r2 = r1, r2
                            
                if best_r1 == -1:
                    possible = False
                    break
                else:
                    plan_ratios[size] = [best_r1, best_r2]
                    if allow_large_to_small:
                        inherited_excess = min_waste_for_size
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
                                    is_sum_ok = (max_ratio_sum == 0) or (current_bin['sum'] + 1 <= max_ratio_sum)
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

def generate_html_table(sizes, initial_orders, markers, style_no="", color="", cut_type="", layout_dir="", special_process="", overage_pct=0, allow_large_to_small=False):
    date_str = datetime.now().strftime("%Y年%m月%d日")
    
    sizes_js = [str(s) for s in sizes]
    initial_orders_js = {str(s): initial_orders[s] for s in sizes}
    
    table_html = '<table style="width:100%; text-align:center; border-collapse: collapse; font-family: sans-serif; font-size: 16px;">'
    
    header_parts = []
    if style_no.strip():
        header_parts.append(f'🏷️ 款号：<span style="color:#c00;">{style_no.strip()}</span>')
    if color.strip():
        header_parts.append(f'🎨 颜色：<span style="color:#0066cc;">{color.strip()}</span>')
    if cut_type.strip():
        header_parts.append(f'✂️ 裁片：{cut_type.strip()}')
        
    header_parts.append(f'↕️ 排版：<span style="border-bottom: 2px solid #000;">{layout_dir}</span>')
    
    display_special = special_process.strip() if special_process.strip() else "常规"
    if allow_large_to_small:
        if display_special == "常规":
            display_special = "大改小抵扣"
        else:
            display_special += " (大改小抵扣)"
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
    auto_note_text = ""

    for marker_idx, marker in enumerate(markers):
        is_last_row = (marker_idx == len(markers) - 1)
        is_priority = marker.get('is_priority', False)
        
        bg_color = "#fff2f2" if is_priority else "#fdfdfd"
        
        table_html += f'<tr class="marker-data-row" style="font-weight: bold; background-color: {bg_color};">'
        for s in sizes:
            r = marker['ratios'].get(s, 0)
            text_r = str(r) if r > 0 else ""
            table_html += f'<td contenteditable="true" class="ratio-cell" data-size="{s}" style="color: red; padding: 8px; cursor: text;">{text_r}</td>'
        
        table_html += f'<td contenteditable="true" class="layer-cell" style="color: #003399; padding: 8px; cursor: text;">{marker["layers"]}</td>'
        
        sum_val = marker['sum']
        text_sum = str(sum_val) if sum_val != "" else ""
        badge = '<br><span style="font-size:11px; color:#cc0000; font-weight:normal;">⚡优先</span>' if is_priority else ''
        sum_bg = "#ffe6e6" if is_priority else "#f0f8ff"
        table_html += f'<td class="sum-cell" style="color: #003399; padding: 8px; background-color: {sum_bg};">{text_sum}{badge}</td></tr>'

        table_html += '<tr class="marker-remain-row" style="border-bottom: 1px solid #eee;">'
        
        display_remains = list(current_remains)
        for i, s in enumerate(sizes):
            display_remains[i] -= marker['ratios'].get(s, 0) * marker['layers']
            
        current_remains = list(display_remains)

        for i, s in enumerate(sizes):
            remain_val = display_remains[i]
            max_allowed_extra = math.floor(initial_orders[s] * (overage_pct / 100.0))
            
            if is_last_row:
                if remain_val < 0:
                    display_text = str(remain_val)
                    text_color = "#cc0000" if abs(remain_val) > max_allowed_extra else "#e65c00" 
                    font_weight = "bold"
                elif remain_val > 0:
                    display_text = str(remain_val)
                    text_color = "#0066cc" 
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
        max_allowed_extra = math.floor(initial_orders[s] * (overage_pct / 100.0))
        
        cell_html = ""
        
        if raw_val < 0:
            extra = abs(raw_val)
            color = "#cc0000" if extra > max_allowed_extra else "#e65c00"
            warn = f"<br><span style='font-size:12px;color:#cc0000; font-weight:normal;'>(超{overage_pct}%)</span>" if extra > max_allowed_extra else ""
            cell_html += f"<div style='font-size:16px; font-weight:bold; color:{color};'>增裁{extra}{warn}</div>"
            if extra > max_allowed_extra:
                has_global_overage = True
                
        for msg in substitutions_map[s]:
            cell_html += f"<div style='font-size:13px; font-weight:bold; color:#0066cc; margin-top:6px;'>{msg}</div>"
            
        table_html += f'<td class="final-overcut-cell" data-size="{s}" style="padding: 12px 8px; vertical-align: top;">{cell_html}</td>'
            
    table_html += '<td colspan="2" style="padding: 12px 8px; color: #555; font-size: 15px; vertical-align: middle; font-weight: bold; text-align: left;">👈 实际增裁汇总</td></tr>'
    
    table_html += '</table>'

    display_style_warning = "block" if has_global_overage else "none"
    table_html += f'<div id="overage-warning" style="display: {display_style_warning}; color: #cc0000; font-weight: bold; margin-top: 15px; padding: 10px; background-color: #ffe6e6; border: 1px solid #ffcccc; border-radius: 4px; text-align: center;">⚠️ 警告：当前排版方案中，部分尺码（深红色）的增裁件数已超出设定的 {overage_pct}% 溢装率上限！</div>'

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
            🖱️ <b>功能提示：</b>双击红/蓝数字即可微调。<br>带有 <b style="color:#c00;">⚡优先</b> 标记的版会被置顶先裁；开启大改小后会自动在底部生成改码明细！
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
            const allowLargeToSmall = {str(allow_large_to_small).lower()};

            function recalculate() {{
                let currentRemains = JSON.parse(JSON.stringify(initialOrders));
                const dataRows = document.querySelectorAll('.marker-data-row');
                const remainRows = document.querySelectorAll('.marker-remain-row');
                
                let hasGlobalOverage = false; 

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

                    row.querySelector('.sum-cell').childNodes[0].nodeValue = ratioSum > 0 ? ratioSum : "";

                    let remainRow = remainRows[index];
                    let displayRemains = JSON.parse(JSON.stringify(currentRemains));
                    
                    sizes.forEach(size => {{
                        let remainCell = remainRow.querySelector(`.remain-cell[data-size="` + size + `"]`);
                        let rVal = displayRemains[size];
                        let maxAllowedExtra = Math.floor(initialOrders[size] * (overagePct / 100.0));
                        
                        remainCell.innerText = rVal; 
                        
                        if (isLastRow) {{
                            if (rVal < 0) {{
                                remainCell.style.color = (Math.abs(rVal) > maxAllowedExtra) ? "#cc0000" : "#e65c00";
                            }} else if (rVal > 0) {{
                                remainCell.style.color = "#0066cc"; 
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
                    let maxAllowedExtra = Math.floor(initialOrders[size] * (overagePct / 100.0));
                    
                    let cellHtml = "";
                    
                    if (rawVal < 0) {{
                        let extra = Math.abs(rawVal);
                        let color = (extra > maxAllowedExtra) ? "#cc0000" : "#e65c00";
                        let warn = (extra > maxAllowedExtra) ? `<br><span style='font-size:12px;color:#cc0000; font-weight:normal;'>(超${{overagePct}}%)</span>` : "";
                        cellHtml += `<div style='font-size:16px; font-weight:bold; color:${{color}};'>增裁${{extra}}${{warn}}</div>`;
                        if (extra > maxAllowedExtra) hasGlobalOverage = true;
                    }}
                    
                    subMap[size].forEach(msg => {{
                        cellHtml += `<div style='font-size:13px; font-weight:bold; color:#0066cc; margin-top:6px;'>${{msg}}</div>`;
                    }});
                    
                    finalCell.innerHTML = cellHtml;
                }});

                let warningBox = document.getElementById('overage-warning');
                if (warningBox) {{
                    warningBox.style.display = hasGlobalOverage ? 'block' : 'none';
                }}
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

st.title("✂️ 蓉成服饰智能排料系统")
st.markdown("输入大货订单需求与裁床限制，一键生成最优阶梯拉布方案。")

# 侧边栏：参数设置
st.sidebar.header("⚙️ 裁床限制参数")

col1, col2 = st.sidebar.columns(2)
with col1:
    min_layers = st.number_input("最低层数", min_value=1, value=1)
with col2:
    max_layers = st.number_input("最高层数", min_value=0, value=0) 

display_overage_pct = st.sidebar.number_input("溢装率 (%)", min_value=0, value=5, step=1)
max_overage_pct = display_overage_pct / 100.0 

max_ratio_sum = st.sidebar.number_input("配比和上限 (0代表不限制)", min_value=0, value=0)
max_markers = st.sidebar.number_input("总版数上限", min_value=0, value=0)
max_sizes_per_marker = st.sidebar.number_input("单版最多尺码数", min_value=0, value=0)

st.sidebar.markdown("---")
allow_large_to_small = st.sidebar.checkbox(
    "✨ 开启「大改小」允许", 
    value=False, 
    help="勾选后，排版时右侧大尺码多余的件数会自动向左填补小尺码的缺口。注意：仅适用于可自由裁减的常规裁片！"
)

st.sidebar.markdown("---")
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

# 主页面：订单输入
st.subheader("📝 步骤 1：生产工艺与尺码信息")

col_style, col_color, col_cut, col_layout, col_special = st.columns(5)
with col_style:
    style_no = st.text_input("👗 款号 (选填)：", placeholder="RC-001")
with col_color:
    color = st.text_input("🎨 颜色 (选填)：", placeholder="藏青色")
with col_cut:
    cut_type = st.text_input("✂️ 裁片 (选填)：", placeholder="大身")
with col_layout:
    layout_dir = st.selectbox("↕️ 排列方式：", options=["任意", "同码同向", "件份同向", "同一方向"], index=1)
with col_special:
    special_process = st.text_input("✨ 特殊 (选填)：", placeholder="如: 加衬/对条/手拉")

size_input = st.text_input(
    "👉 请输入这批货的所有尺码名称（用空格隔开）：", 
    value="90 100 110 120 130 140"
)

raw_sizes = re.split(r'[,，\s、\-]+', size_input.strip())
sizes_list = []
for s in raw_sizes:
    if s and s not in sizes_list:
        sizes_list.append(s)

st.subheader("📦 步骤 2：输入各尺码订单件数")
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

st.write("---")

# 🌟 步骤 3：优先急单提取
st.subheader("⏱️ 步骤 3：优先急单设置 (选填)")
enable_priority = st.checkbox("✨ 启用优先急单 (系统将在全局最优排版中，优先置顶急需的尺码)")
priority_orders = {}

if enable_priority:
    st.info("💡 提示：为了保证面料利用率最大化，系统不会产生1层的碎版，而是会将**包含了你急需尺码的大货排版直接提前**！")
    pri_sizes = st.multiselect("👉 选择急需先裁的尺码：", options=[s for s in sizes_list if orders.get(s, 0) > 0])
    if pri_sizes:
        cols_pri = st.columns(min(len(pri_sizes), 6))
        for i, size in enumerate(pri_sizes):
            with cols_pri[i % 6]:
                max_v = orders.get(size, 0)
                p_val = st.number_input(f"【 {size} 】急需件数", min_value=0, max_value=max_v, value=min(max_v, 50), step=10, key=f"pri_{size}")
                if p_val > 0:
                    priority_orders[size] = p_val

st.write("---")

total_order_qty = sum(orders.values())
if total_order_qty > 0:
    st.info(f"💡 当前已录入的订单总需求为： **{total_order_qty}** 件")
else:
    st.info("💡 当前已录入的订单总需求为： **0** 件")

# 计算按钮与结果展示
if st.button("🚀 开始计算排料方案", type="primary", use_container_width=True):
    if not orders:
        st.error("❌ 请至少填写一个尺码的件数！")
    elif max_layers <= 0:
        st.error("❌ 左侧的【最高允许层数】不能为 0，请先设置！")
    elif min_layers > max_layers:
        st.error("❌ 【最低允许层数】不能大于【最高允许层数】，请检查输入！")
    elif max_markers <= 0:
        st.error("❌ 左侧的【总版数上限】不能为 0，请先设置！")
    elif max_sizes_per_marker <= 0:
        st.error("❌ 左侧的【单版最多尺码数】不能为 0，请先设置！")
    else:
        with st.spinner("电脑正在疯狂计算全局最优组合，请稍候..."):
            
            # 🌟 永远先算全局最优，绝不牺牲面料
            valid_sizes, markers = find_best_plan(
                orders, sizes_list, min_layers, max_layers, max_overage_pct, max_ratio_sum, max_markers, max_sizes_per_marker, allow_large_to_small
            )
            
            if markers:
                if enable_priority and priority_orders:
                    # 🌟 智能分拣算法：把包含急需件数的好版，直接抽调到最前面！
                    priority_markers = []
                    normal_markers = markers.copy()
                    current_yield = {s: 0 for s in priority_orders}
                    
                    while normal_markers:
                        # 检查急单是否已经全部满足
                        all_met = True
                        for s, target in priority_orders.items():
                            if current_yield[s] < target:
                                all_met = False
                                break
                        if all_met:
                            break
                            
                        # 在剩下的版里，挑出对急单贡献最大的那一个版
                        best_idx = -1
                        best_score = -1
                        
                        for idx, m in enumerate(normal_markers):
                            score = 0
                            for s, target in priority_orders.items():
                                needed = max(0, target - current_yield[s])
                                provided = m['ratios'].get(s, 0) * m['layers']
                                score += min(needed, provided)
                                
                            if score > best_score:
                                best_score = score
                                best_idx = idx
                                
                        if best_score == 0:
                            break # 剩下的版里都没有我们要的急单尺码了
                            
                        # 把这个最优的版抽出来，放进优先队列
                        chosen = normal_markers.pop(best_idx)
                        chosen['is_priority'] = True
                        priority_markers.append(chosen)
                        
                        for s in priority_orders:
                            current_yield[s] += chosen['ratios'].get(s, 0) * chosen['layers']
                            
                    for m in normal_markers:
                        m['is_priority'] = False
                        
                    # 重新拼合队伍：急单排前面，常规跟在后面
                    markers = priority_markers + normal_markers
                else:
                    for m in markers:
                        m['is_priority'] = False
            
        if markers:
            total_produced = 0
            for m in markers:
                total_produced += m['sum'] * m['layers']
                
            st.success(f"✅ 成功找到完美方案！共使用了 **{len(markers)}** 个版。 订单需求 **{total_order_qty}** 件，实际排版产出 **{total_produced}** 件。")
            
            title_text = f"📊 阶梯式扣减排料单"
            st.subheader(title_text)
            
            html_content = generate_html_table(valid_sizes, orders, markers, style_no, color, cut_type, layout_dir, special_process, display_overage_pct, allow_large_to_small)
            components.html(html_content, height=850, scrolling=True)
            
        else:
            st.error("❌ 在当前的严苛限制下，未找到不超标的方案。")
            st.info("💡 建议：尝试在左侧边栏放宽【总版数上限】、【配比和上限】或【单版最多尺码数】后重试。")
