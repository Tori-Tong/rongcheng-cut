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
                    rem = target - r1 * L1
                    r2 = 0 if rem <= 0 else math.ceil(rem / L2)
                    
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

# 🌟 核心魔法：注入 JavaScript 实时计算引擎
def generate_html_table(sizes, initial_orders, markers, style_no=""):
    date_str = datetime.now().strftime("%Y年%m月%d日")
    
    # 将初始订单数据转为供 JS 使用的格式
    sizes_js = [str(s) for s in sizes]
    initial_orders_js = {str(s): initial_orders[s] for s in sizes}
    
    table_html = '<table style="width:100%; text-align:center; border-collapse: collapse; font-family: sans-serif; font-size: 16px;">'
    
    display_style = style_no if style_no else "未填"
    table_html += f'<tr><td colspan="{len(sizes) + 2}" contenteditable="true" style="text-align:left; font-size:18px; font-weight:bold; padding:10px; border-bottom: 2px solid #333; background-color: #fff3cd; cursor: text;">'
    table_html += f'🏷️ 生产款号：{display_style} <span style="float:right; font-size:16px; font-weight:normal; color:#555;">📅 日期：{date_str}</span>'
    table_html += '</td></tr>'

    table_html += '<tr style="border-bottom: 2px solid #ccc; background-color: #f8f9fa;">'
    for s in sizes: table_html += f'<th style="padding: 10px;">{s}</th>'
    table_html += '<th style="padding: 10px;">层数</th><th style="padding: 10px;">配比和</th></tr>'

    current_remains = [initial_orders[s] for s in sizes]
    table_html += '<tr>'
    for r in current_remains: table_html += f'<td style="padding: 8px;">{r}</td>'
    table_html += '<td></td><td></td></tr>'

    for marker in markers:
        # 🌟 给配比行打上 marker-data-row 标记
        table_html += '<tr class="marker-data-row" style="font-weight: bold; background-color: #fdfdfd;">'
        for s in sizes:
            r = marker['ratios'].get(s, 0)
            text_r = str(r) if r > 0 else ""
            table_html += f'<td contenteditable="true" class="ratio-cell" data-size="{s}" style="color: red; padding: 8px; cursor: text;">{text_r}</td>'
        
        table_html += f'<td contenteditable="true" class="layer-cell" style="color: #003399; padding: 8px; cursor: text;">{marker["layers"]}</td>'
        # 配比和不许编辑，由JS自动算
        table_html += f'<td class="sum-cell" style="color: #003399; padding: 8px; background-color: #f0f8ff;">{marker["sum"]}</td></tr>'

        # 🌟 给剩余件数行打上 marker-remain-row 标记
        table_html += '<tr class="marker-remain-row" style="border-bottom: 1px solid #eee;">'
        for i, s in enumerate(sizes):
            current_remains[i] -= marker['ratios'].get(s, 0) * marker['layers']
            table_html += f'<td class="remain-cell" data-size="{s}" style="padding: 8px; background-color: #fafafa;">{current_remains[i]}</td>'
        table_html += '<td></td><td></td></tr>'
        
    table_html += '</table>'

    safe_style = style_no.strip() if style_no else "大货排料单"
    filename = f"{safe_style}_{date_str}.png"

    full_wrapper = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
        <style>
            .dl-btn {{
                background-color: #0066cc; color: white; border: none;
                padding: 8px 16px; border-radius: 4px; cursor: pointer;
                font-size: 14px; font-weight: bold; margin-bottom: 10px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1); transition: 0.3s;
            }}
            .dl-btn:hover {{ background-color: #004c99; }}
            #capture-area {{
                background-color: white; padding: 15px; border-radius: 5px;
            }}
            td[contenteditable="true"]:hover {{
                background-color: #e6f7ff !important;
                outline: 2px dashed #1890ff;
                border-radius: 2px;
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 0;">
        <button class="dl-btn" onclick="takeShot()">📸 保存为高清图片 (文件名: {filename})</button>
        <div id="capture-area">
            {table_html}
        </div>
        <script>
            // 🌟 接收 Python 传来的初始订单数据
            const sizes = {json.dumps(sizes_js)};
            const initialOrders = {json.dumps(initial_orders_js)};

            // 🌟 核心自动计算逻辑
            function recalculate() {{
                // 每次修改，都从初始订单重新开始往下推算
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
                        
                        // 扣减当前版的产出件数
                        currentRemains[size] -= (ratio * layers);
                    }});

                    // 自动更新右侧的配比和
                    row.querySelector('.sum-cell').innerText = ratioSum;

                    // 自动更新下方的剩余件数
                    let remainRow = remainRows[index];
                    sizes.forEach(size => {{
                        let remainCell = remainRow.querySelector(`.remain-cell[data-size="` + size + `"]`);
                        remainCell.innerText = currentRemains[size];
                    }});
                }});
            }}

            // 🌟 监听所有可编辑单元格的输入动作
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
    min_layers = st.number_input("最低允许层数", min_value=1, value=1)
with col2:
    max_layers = st.number_input("最高允许层数", min_value=0, value=0)

display_overage_pct = st.sidebar.slider("最高允许溢出率 (%)", min_value=0, max_value=200, value=5, step=1, format="%d%%")
max_overage_pct = display_overage_pct / 100.0 

max_ratio_sum = st.sidebar.number_input("配比和上限 (0代表不限制)", min_value=0, max_value=100, value=0)
max_markers = st.sidebar.number_input("总版数上限", min_value=0, max_value=30, value=0)
max_sizes_per_marker = st.sidebar.number_input("单版最多尺码数", min_value=0, max_value=20, value=0)

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
st.subheader("📝 步骤 1：基础信息与尺码")

col_style, col_sizes = st.columns([1, 2])
with col_style:
    style_no = st.text_input("👗 请输入服装款号（选填）：", placeholder="例如：DS-2601")
with col_sizes:
    size_input = st.text_input(
        "👉 请输入这批货的所有尺码名称（空格隔开）：", 
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
            
            html_content = generate_html_table(valid_sizes, orders, markers, style_no)
            components.html(html_content, height=800, scrolling=True)
            
            # 🌟 更新操作提示
            st.info("🖱️ **黑科技提示**：这是一个“活”表格！请直接双击修改红色的【配比】或蓝色的【层数】，旁边所有的配比和与下方的剩余件数**会自动联动重新计算**！调整满意后点击保存图片即可。")
            
        else:
            st.error("❌ 在当前的严苛限制下，未找到不超标的方案。")
            st.info("💡 建议：尝试在左侧边栏放宽【总版数上限】、【配比和上限】或【单版最多尺码数】后重试。")
