import streamlit as st
import streamlit.components.v1 as components
import math
import re
import json
from datetime import datetime

# ================= 核心算法 =================
def find_best_plan(orders, ordered_sizes, min_layers, max_layers, max_overage_pct, max_ratio_sum, max_markers, max_sizes_per_marker):
    sizes = [s for s in ordered_sizes if s in orders and orders[s] > 0]
    
    best_waste = float('inf')
    best_plan = None
    best_markers = None
    
    for L1 in range(min_layers, max_layers + 1):
        for L2 in range(L1, max_layers + 1):
            current_waste = 0
            plan_ratios = {}
            possible = True
            
            for size in sizes:
                target = orders[size]
                max_allowed = math.floor(target * (1 + max_overage_pct))
                
                min_waste_for_size = float('inf')
                best_r1, best_r2 = -1, -1
                
                max_r1 = (max_allowed // L1) + 1
                for r1 in range(max_r1 + 1):
                    if max_ratio_sum > 0 and r1 > max_ratio_sum:
                        continue
                        
                    rem = target - r1 * L1
                    r2 = 0 if rem <= 0 else math.ceil(rem / L2)
                    
                    if max_ratio_sum > 0 and r2 > max_ratio_sum:
                        continue
                        
                    produced = r1 * L1 + r2 * L2
                    if target <= produced <= max_allowed:
                        waste = produced - target
                        if waste < min_waste_for_size:
                            min_waste_for_size = waste
                            best_r1, best_r2 = r1, r2
                            
                if best_r1 == -1:
                    possible = False
                    break
                else:
                    plan_ratios[size] = [best_r1, best_r2]
                    current_waste += min_waste_for_size
                    
            if possible:
                temp_markers = []
                layers_list = [L1, L2]
                
                for i, L in enumerate(layers_list):
                    items = []
                    for size in sizes:
                        r = plan_ratios[size][i]
                        if r > 0:
                            items.append({'size': size, 'count': r})
                            
                    items.sort(key=lambda x: x['count'], reverse=True)
                    bins = []
                    for item in items:
                        placed = False
                        for b in bins:
                            current_sizes_in_bin = len(b['ratios'])
                            is_new_size = item['size'] not in b['ratios']
                            
                            is_sum_ok = (max_ratio_sum == 0) or (b['sum'] + item['count'] <= max_ratio_sum)
                            
                            if is_sum_ok:
                                if not is_new_size or current_sizes_in_bin < max_sizes_per_marker:
                                    b['ratios'][item['size']] = b['ratios'].get(item['size'], 0) + item['count']
                                    b['sum'] += item['count']
                                    placed = True
                                    break
                        if not placed:
                            bins.append({'layers': L, 'ratios': {item['size']: item['count']}, 'sum': item['count']})
                    temp_markers.extend(bins)
                
                if len(temp_markers) <= max_markers:
                    if current_waste < best_waste:
                        best_waste = current_waste
                        best_plan = {'L1': L1, 'L2': L2, 'ratios': plan_ratios}
                        best_markers = temp_markers

    return sizes, best_markers

# 🌟 修改点 1：函数接收当前设置的溢装率 (overage_pct)
def generate_html_table(sizes, initial_orders, markers, style_no="", color="", cut_type="", layout_dir="", special_process="", overage_pct=0):
    date_str = datetime.now().strftime("%Y年%m月%d日")
    
    sizes_js = [str(s) for s in sizes]
    initial_orders_js = {str(s): initial_orders[s] for s in sizes}
    
    table_html = '<table style="width:100%; text-align:center; border-collapse: collapse; font-family: sans-serif; font-size: 16px;">'
    
    display_style = style_no if style_no else "未填"
    display_color = color if color else "未填"
    display_cut = cut_type if cut_type else "未填"
    display_special = special_process if special_process else "常规"

    table_html += f'<tr><td colspan="{len(sizes) + 2}" contenteditable="true" style="text-align:left; font-size:16px; font-weight:bold; padding:12px 10px; border-bottom: 2px solid #333; background-color: #fff3cd; cursor: text; line-height: 1.6;">'
    table_html += f'🏷️ 款号：<span style="color:#c00;">{display_style}</span> &nbsp;&nbsp;|&nbsp;&nbsp; '
    table_html += f'🎨 颜色：<span style="color:#0066cc;">{display_color}</span> &nbsp;&nbsp;|&nbsp;&nbsp; '
    table_html += f'✂️ 裁片：{display_cut} &nbsp;&nbsp;|&nbsp;&nbsp; '
    table_html += f'↕️ 排版：<span style="border-bottom: 2px solid #000;">{layout_dir}</span> &nbsp;&nbsp;|&nbsp;&nbsp; '
    table_html += f'✨ 工艺：<span style="color:#e65c00;">{display_special}</span>'
    table_html += f'<span style="float:right; font-size:15px; font-weight:normal; color:#555;">📅 日期：{date_str}</span>'
    table_html += '</td></tr>'

    table_html += '<tr style="border-bottom: 2px solid #ccc; background-color: #f8f9fa;">'
    for s in sizes: table_html += f'<th style="padding: 10px;">{s}</th>'
    table_html += '<th style="padding: 10px;">层数</th><th style="padding: 10px;">配比和</th></tr>'

    current_remains = [initial_orders[s] for s in sizes]
    table_html += '<tr>'
    for r in current_remains: table_html += f'<td style="padding: 8px;">{r}</td>'
    table_html += '<td></td><td></td></tr>'

    for marker in markers:
        table_html += '<tr class="marker-data-row" style="font-weight: bold; background-color: #fdfdfd;">'
        for s in sizes:
            r = marker['ratios'].get(s, 0)
            text_r = str(r) if r > 0 else ""
            table_html += f'<td contenteditable="true" class="ratio-cell" data-size="{s}" style="color: red; padding: 8px; cursor: text;">{text_r}</td>'
        
        table_html += f'<td contenteditable="true" class="layer-cell" style="color: #003399; padding: 8px; cursor: text;">{marker["layers"]}</td>'
        table_html += f'<td class="sum-cell" style="color: #003399; padding: 8px; background-color: #f0f8ff;">{marker["sum"]}</td></tr>'

        table_html += '<tr class="marker-remain-row" style="border-bottom: 1px solid #eee;">'
        for i, s in enumerate(sizes):
            current_remains[i] -= marker['ratios'].get(s, 0) * marker['layers']
            remain_val = current_remains[i]
            
            # 🌟 修改点 2：Python 初始渲染表格时增加超标判断
            max_allowed_extra = math.floor(initial_orders[s] * (overage_pct / 100.0))
            
            if remain_val < 0:
                extra = abs(remain_val)
                if extra > max_allowed_extra:
                    # 超过设定的溢装率，显示深红色并带警告
                    display_text = f"增裁{extra} (超{overage_pct}%)"
                    text_color = "#cc0000" 
                else:
                    # 正常范围内的增裁
                    display_text = f"增裁{extra}"
                    text_color = "#e65c00" 
                font_weight = "bold"
            elif remain_val == 0:
                display_text = "0"
                text_color = "#28a745" 
                font_weight = "bold"
            else:
                display_text = str(remain_val)
                text_color = "#000"
                font_weight = "normal"
                
            table_html += f'<td class="remain-cell" data-size="{s}" style="padding: 8px; background-color: #fafafa; color: {text_color}; font-weight: {font_weight};">{display_text}</td>'
        table_html += '<td></td><td></td></tr>'
        
    table_html += '</table>'

    filename_parts = []
    if style_no.strip(): filename_parts.append(style_no.strip())
    else: filename_parts.append("大货排料单")
    if color.strip(): filename_parts.append(color.strip())
    if cut_type.strip(): filename_parts.append(cut_type.strip())
    if special_process.strip(): filename_parts.append(special_process.strip())
    filename_parts.append(date_str)
    
    filename = "_".join(filename_parts) + ".png"

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
        </style>
    </head>
    <body style="margin: 0; padding: 0;">
        <button class="dl-btn" onclick="takeShot()">📸 保存为高清图片 (文件名: {filename})</button>
        
        <div class="hint-box">
            🖱️ <b>提示：</b>这是一个“活”表格！请直接点击修改红色的【配比】或蓝色的【层数】，旁边所有的配比和与下方的件数<b>会自动联动重新计算</b>！调整满意后点击保存图片即可。
        </div>

        <div id="capture-area">
            {table_html}
        </div>
        <script>
            const sizes = {json.dumps(sizes_js)};
            const initialOrders = {json.dumps(initial_orders_js)};
            
            // 🌟 修改点 3：将 Python 中的溢装率传给 JS 引擎
            const overagePct = {overage_pct};

            function recalculate() {{
                let currentRemains = JSON.parse(JSON.stringify(initialOrders));
                const dataRows = document.querySelectorAll('.marker-data-row');
                const remainRows = document.querySelectorAll('.marker-remain-row');

                dataRows.forEach((row, index) => {{
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

                    row.querySelector('.sum-cell').innerText = ratioSum;

                    let remainRow = remainRows[index];
                    sizes.forEach(size => {{
                        let remainCell = remainRow.querySelector(`.remain-cell[data-size="` + size + `"]`);
                        let rVal = currentRemains[size];
                        
                        // 🌟 修改点 4：JavaScript 实时计算时的超标判断
                        let maxAllowedExtra = Math.floor(initialOrders[size] * (overagePct / 100.0));
                        
                        if (rVal < 0) {{
                            let extra = Math.abs(rVal);
                            if (extra > maxAllowedExtra) {{
                                remainCell.innerText = "增裁" + extra + " (超" + overagePct + "%)";
                                remainCell.style.color = "#cc0000"; // 深红色警告
                                remainCell.style.fontWeight = "bold";
                            }} else {{
                                remainCell.innerText = "增裁" + extra;
                                remainCell.style.color = "#e65c00"; // 正常橙色
                                remainCell.style.fontWeight = "bold";
                            }}
                        }} else if (rVal === 0) {{
                            remainCell.innerText = "0";
                            remainCell.style.color = "#28a745";
                            remainCell.style.fontWeight = "bold";
                        }} else {{
                            remainCell.innerText = rVal;
                            remainCell.style.color = "#000";
                            remainCell.style.fontWeight = "normal";
                        }}
                    }});
                }});
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
        with st.spinner("电脑正在疯狂计算最佳组合，请稍候..."):
            valid_sizes, markers = find_best_plan(
                orders, sizes_list, min_layers, max_layers, max_overage_pct, max_ratio_sum, max_markers, max_sizes_per_marker
            )
            
        if markers:
            total_produced = 0
            for m in markers:
                total_produced += m['sum'] * m['layers']
                
            st.success(f"✅ 成功找到完美方案！共使用了 **{len(markers)}** 个版。 订单需求 **{total_order_qty}** 件，实际排版产出 **{total_produced}** 件。")
            
            title_text = f"📊 阶梯式扣减排料单"
            st.subheader(title_text)
            
            # 🌟 修改点 5：将 display_overage_pct (比如 5) 作为参数传给 HTML 表格生成器
            html_content = generate_html_table(valid_sizes, orders, markers, style_no, color, cut_type, layout_dir, special_process, display_overage_pct)
            components.html(html_content, height=800, scrolling=True)
            
        else:
            st.error("❌ 在当前的严苛限制下，未找到不超标的方案。")
            st.info("💡 建议：尝试在左侧边栏放宽【总版数上限】、【配比和上限】或【单版最多尺码数】后重试。")
