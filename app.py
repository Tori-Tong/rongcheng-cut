import streamlit as st
import streamlit.components.v1 as components
import math
import re
import json
import html
import pandas as pd
from datetime import datetime

# ================= 核心算法 =================
def find_best_plan(orders, ordered_sizes, min_layers, max_layers, max_overage_pct, max_shortage_pct, max_ratio_sum, max_markers, max_sizes_per_marker, allow_large_to_small, allow_shortage, strategy_mode="高低版优先", thin_long_mode="标准", global_orders=None):
    import math
    from itertools import combinations, product
    
    if global_orders is None:
        global_orders = orders
        
    sizes = [s for s in ordered_sizes if s in orders and orders[s] > 0]
    
    targets = {s: orders[s] for s in sizes}
    max_allowed = {s: math.floor(global_orders[s] * (1 + max_overage_pct)) for s in sizes}
    
    # ✅ 不断码：只要该尺码有订单，即便启用短装，也至少保留 1 件的硬底线
    if allow_shortage:
        min_required = {
            s: max(1, math.floor(global_orders[s] * (1 - max_shortage_pct)))
            for s in sizes
        }
    else:
        min_required = targets.copy()

    strategy_profiles = {
        "高低版优先": {
            "bed_fill_weight": 1.18,
            "reuse_weight": 0.95,
            "ratio_penalty_weight": 0.88,
            "dominant_penalty_weight": 0.90,
            "balance_penalty_weight": 0.18,
            "long_thin_weight": 1.0,
            "marker_count_weight": 1.0,
            "candidate_sum_reward": 860,
            "candidate_gap_penalty": 900,
        },
        "稳妥均衡": {
            "bed_fill_weight": 0.90,
            "reuse_weight": 1.0,
            "ratio_penalty_weight": 1.18,
            "dominant_penalty_weight": 1.22,
            "balance_penalty_weight": 1.00,
            "long_thin_weight": 1.18,
            "marker_count_weight": 1.0,
            "candidate_sum_reward": 620,
            "candidate_gap_penalty": 1150,
        },
    }
    strategy_cfg = strategy_profiles.get(strategy_mode, strategy_profiles["高低版优先"])
    
    def ratio_signature(ratios):
        return tuple(sorted((s, r) for s, r in ratios.items() if r > 0))
    
    def get_real_markers(markers):
        return [m for m in markers if not m.get('is_tail', False)]

    def normalize_marker_order(markers):
        real_markers = [m.copy() for m in get_real_markers(markers)]
        real_markers.sort(key=lambda m: (-int(m.get('layers', 0)), -int(m.get('sum', 0)), -len([v for v in m.get('ratios', {}).values() if v > 0])))
        return real_markers
    
    # ✅ 现在把“配比和”当作整床近似长度目标：总配比和越接近 max_ratio_sum 越好
    def get_used_bed_sum(markers):
        return sum(m['sum'] for m in get_real_markers(markers))
    
    def check_validity(test_rem):
        if allow_large_to_small:
            test_rem = test_rem.copy()
            for i in range(len(sizes) - 1, 0, -1):
                s_large = sizes[i]
                if test_rem[s_large] < 0:
                    excess = abs(test_rem[s_large])
                    for j in range(i - 1, -1, -1):
                        s_small = sizes[j]
                        if test_rem[s_small] > 0:
                            fill = min(excess, test_rem[s_small])
                            test_rem[s_small] -= fill
                            test_rem[s_large] += fill
                            excess -= fill
                        if excess == 0:
                            break
        for s in sizes:
            allowed_short = targets[s] - min_required[s]
            if test_rem[s] > allowed_short:
                return False
        return True
    
    def calc_pattern_reuse_bonus(markers):
        real_markers = get_real_markers(markers)
        if not real_markers:
            return 0
        pattern_counts = {}
        for marker in real_markers:
            sig = ratio_signature(marker['ratios'])
            pattern_counts[sig] = pattern_counts.get(sig, 0) + 1
        # 保留“能复用老版更好”的偏好，但不再压过整床长度优先
        return sum((count - 1) * 2600 for count in pattern_counts.values() if count > 1)
    
    def calc_bed_fill_score(markers):
        used_sum = get_used_bed_sum(markers)
        gap = abs(max_ratio_sum - used_sum)
        score = used_sum * 5600 - gap * 17000
        if gap == 0:
            score += 36000
        elif gap <= 1:
            score += 18000
        elif gap <= 2:
            score += 8000
        if used_sum > max_ratio_sum:
            score -= (used_sum - max_ratio_sum) * 9000
        return score * strategy_cfg["bed_fill_weight"]

    def calc_ratio_concentration_penalty(ratios):
        vals = [r for r in ratios.values() if r > 0]
        if len(vals) <= 1:
            return 0

        r_sum = sum(vals)
        if r_sum <= 0:
            return 0

        k = len(vals)
        shares = [v / r_sum for v in vals]
        hhi = sum(p * p for p in shares)
        ideal_hhi = 1.0 / k

        imbalance = max(0.0, hhi - ideal_hhi)
        spread = max(vals) - min(vals)
        dominant = max(vals)

        penalty = imbalance * (r_sum ** 2) * 950
        penalty += max(0, spread - 2) * 500

        if r_sum >= max(6, math.ceil(max_ratio_sum * 0.5)):
            dominant_limit = max(3, math.ceil(r_sum * 0.48))
            if dominant > dominant_limit:
                penalty += (dominant - dominant_limit) * 2600

        if k >= 3 and r_sum >= max(8, math.ceil(max_ratio_sum * 0.65)) and dominant >= math.ceil(r_sum * 0.5):
            penalty += 6000

        return penalty

    def calc_dominant_marker_penalty(markers):
        real_markers = get_real_markers(markers)
        if len(real_markers) <= 1:
            return 0

        sums = sorted([m['sum'] for m in real_markers], reverse=True)
        total = sum(sums)
        if total <= 0:
            return 0

        dominant_share = sums[0] / total
        penalty = 0

        if dominant_share > 0.62:
            penalty += (dominant_share - 0.62) * 80000

        if sums[0] >= max_ratio_sum and (total - sums[0]) < max(3, math.ceil(max_ratio_sum * 0.25)):
            penalty += 15000

        return penalty

    def calc_marker_balance_penalty(markers):
        real_markers = get_real_markers(markers)
        if len(real_markers) <= 1:
            return 0
        sums = [m['sum'] for m in real_markers if m['sum'] > 0]
        if len(sums) <= 1:
            return 0
        spread = max(sums) - min(sums)
        avg = sum(sums) / len(sums)
        variance = sum((x - avg) ** 2 for x in sums) / len(sums)
        return spread * 1800 + variance * 900

    def calc_marker_structure_penalty(markers):
        real_markers = normalize_marker_order(markers)
        if len(real_markers) <= 1:
            return 0

        penalty = 0
        first = real_markers[0]
        first_layers = int(first.get('layers', 0))
        first_sum = int(first.get('sum', 0))
        max_layers = max(int(m.get('layers', 0)) for m in real_markers)
        max_sum = max(int(m.get('sum', 0)) for m in real_markers)

        # 第一版默认应当是最厚、也通常应当最长。
        if first_layers < max_layers:
            penalty += (max_layers - first_layers) * 1400
        if first_sum < max_sum:
            penalty += (max_sum - first_sum) * 2200

        if len(real_markers) >= 2:
            second = real_markers[1]
            second_layers = int(second.get('layers', 0))
            second_sum = int(second.get('sum', 0))
            if first_layers < second_layers * 1.12:
                penalty += int((second_layers * 1.12 - first_layers) * 1600)
            if first_sum < second_sum:
                penalty += (second_sum - first_sum) * 3200

        prev_layers = None
        prev_sum = None
        for idx, m in enumerate(real_markers):
            cur_layers = int(m.get('layers', 0))
            cur_sum = int(m.get('sum', 0))
            active = len([v for v in m.get('ratios', {}).values() if v > 0])
            density = cur_layers / max(cur_sum, 1)

            if idx == 0:
                if active <= 1 and len(real_markers) >= 2:
                    penalty += 14000
                if cur_sum >= max(6, math.ceil(max_ratio_sum * 0.45)) and density < 7.0:
                    penalty += int((7.0 - density) * 9000)
            elif idx == len(real_markers) - 1:
                # 最后一版允许扫尾，但尽量别拆成单一码小碎版。
                if active == 1:
                    penalty += 18000 + max(0, 5 - cur_sum) * 2200
                elif active == 2 and cur_sum <= 2:
                    penalty += 7000
                if cur_layers <= max(min_layers + 2, int(first_layers * 0.33)):
                    penalty += 4000
            else:
                if active == 1:
                    penalty += 9000
                if cur_sum >= max(6, math.ceil(max_ratio_sum * 0.4)) and density < 5.8:
                    penalty += int((5.8 - density) * 4500)

            if prev_layers is not None:
                # 正常应当从前往后逐步变薄、逐步变短。
                if cur_layers > prev_layers:
                    penalty += (cur_layers - prev_layers) * 2200
                if cur_sum > prev_sum + 1:
                    penalty += (cur_sum - prev_sum) * 2600
                if cur_layers < prev_layers * 0.45 and idx < len(real_markers) - 1:
                    penalty += int((prev_layers * 0.45 - cur_layers) * 700)

            prev_layers = cur_layers
            prev_sum = cur_sum

        return penalty

    def calc_long_thin_penalty(marker):
        r_sum = int(marker.get('sum', 0))
        layers = int(marker.get('layers', 0))
        if r_sum <= 0:
            return 0
        density = layers / max(r_sum, 1)
        penalty = 0

        # 长版不能太薄：越长、越薄，扣分越重。
        if r_sum >= 6 and density < 7.5:
            penalty += int((7.5 - density) * 5000)
        if r_sum >= 8 and density < 6.0:
            penalty += int((6.0 - density) * 8000)
        if r_sum >= 10 and density < 4.8:
            penalty += int((4.8 - density) * 12000)
        if r_sum >= max(12, math.ceil(max_ratio_sum * 0.75)) and density < 4.0:
            penalty += int((4.0 - density) * 16000)

        return penalty

    def calc_singleton_tail_penalty(markers):
        real_markers = normalize_marker_order(markers)
        if not real_markers:
            return 0

        penalty = 0
        tail = real_markers[-1]
        first = real_markers[0]
        active_sizes = [s for s, v in tail.get('ratios', {}).items() if v > 0]
        tail_sum = int(tail.get('sum', 0))
        tail_layers = int(tail.get('layers', 0))
        first_layers = int(first.get('layers', 0))

        if len(active_sizes) == 1:
            penalty += 22000
            if tail_sum <= 3:
                penalty += 12000
            elif tail_sum <= 5:
                penalty += 6000
            if tail_layers <= max(min_layers + 3, 18):
                penalty += 9000
            if tail_layers <= max(min_layers + 1, int(first_layers * 0.35)):
                penalty += 7000
        elif len(active_sizes) == 2 and tail_sum <= 2:
            penalty += 8000

        if len(real_markers) >= 2:
            prev = real_markers[-2]
            prev_active = [s for s, v in prev.get('ratios', {}).items() if v > 0]
            prev_layers = int(prev.get('layers', 0))
            if len(active_sizes) == 1 and len(prev_active) <= 2:
                penalty += 9000
            if tail_layers < prev_layers * 0.35:
                penalty += int((prev_layers * 0.35 - tail_layers) * 900)

        return penalty

    def calc_plan_score(markers, produced):
        real_markers = get_real_markers(markers)
        waste = sum(max(0, produced[s] - targets[s]) for s in sizes)
        thick_bonus = sum((m['layers'] ** 1.35) * 35 for m in real_markers)
        reuse_bonus = calc_pattern_reuse_bonus(real_markers) * strategy_cfg["reuse_weight"]
        bed_fill_score = calc_bed_fill_score(real_markers)
        ratio_concentration_penalty = sum(calc_ratio_concentration_penalty(m['ratios']) for m in real_markers) * strategy_cfg["ratio_penalty_weight"]
        dominant_marker_penalty = calc_dominant_marker_penalty(real_markers) * strategy_cfg["dominant_penalty_weight"]
        marker_balance_penalty = calc_marker_balance_penalty(real_markers) * strategy_cfg["balance_penalty_weight"]
        marker_structure_penalty = calc_marker_structure_penalty(real_markers)
        long_thin_penalty = sum(calc_long_thin_penalty(m) for m in real_markers)
        singleton_tail_penalty = calc_singleton_tail_penalty(real_markers)
        thin_layer_penalty = 0
        for m in real_markers:
            if m['layers'] < 4:
                thin_layer_penalty += 12000
            elif m['layers'] < 8:
                thin_layer_penalty += 5000
        marker_count_penalty = max(0, len(real_markers) - 1) * 1200 * strategy_cfg["marker_count_weight"]
        return (
            1000000
            - (waste * 95)
            + thick_bonus
            + reuse_bonus
            + bed_fill_score
            - ratio_concentration_penalty
            - dominant_marker_penalty
            - marker_balance_penalty
            - marker_structure_penalty
            - long_thin_penalty
            - singleton_tail_penalty
            - thin_layer_penalty
            - marker_count_penalty
        )
    
    def build_candidate(state, layers, ratios, base_score=0, reuse_bonus=0, source_layers=None):
        clean_ratios = {s: r for s, r in ratios.items() if r > 0}
        if not clean_ratios:
            return None
        if len(clean_ratios) > max_sizes_per_marker:
            return None
        
        used_bed_sum = get_used_bed_sum(state['markers'])
        
        r_sum = sum(clean_ratios.values())
        # ✅ 单个版本身不能离谱拉得过长；整床总长度则作为优先目标去逼近
        if r_sum <= 0 or r_sum > max_ratio_sum:
            return None
        
        removed_total = 0
        waste_total = 0
        exact_hits = 0
        
        for s, r in clean_ratios.items():
            prod = r * layers
            if state['produced'][s] + prod > max_allowed[s]:
                return None
            removed_total += min(state['rem'][s], prod)
            waste_total += max(0, prod - state['rem'][s])
            if prod == state['rem'][s]:
                exact_hits += 1
        
        after_used_sum = used_bed_sum + r_sum
        target_gap_after = abs(max_ratio_sum - after_used_sum)
        
        score = base_score
        score += removed_total * 12
        score -= waste_total * 85
        score += layers * 10
        score += r_sum * strategy_cfg['candidate_sum_reward']
        score += exact_hits * 1600
        score += reuse_bonus
        score -= calc_long_thin_penalty({'layers': layers, 'sum': r_sum, 'ratios': clean_ratios})
        
        if waste_total == 0:
            score += 900
        if target_gap_after == 0:
            score += 24000
        elif target_gap_after <= 1:
            score += 10000
        elif target_gap_after <= 2:
            score += 4500
        else:
            score -= target_gap_after * strategy_cfg['candidate_gap_penalty']
        if after_used_sum > max_ratio_sum:
            score -= (after_used_sum - max_ratio_sum) * 5000
        
        if source_layers is not None:
            source_gap = abs(layers - source_layers)
            score -= source_gap * 80
            if source_gap == 0:
                score += 1200
        
        return {
            'layers': layers,
            'ratios': clean_ratios,
            'sum': r_sum,
            'score': score,
        }
    
    BEAM_WIDTH = 260
    BRANCHES_PER_STATE = 48
    
    initial_state = {
        'markers': [],
        'rem': {s: targets[s] for s in sizes},
        'produced': {s: 0 for s in sizes}
    }
    beam = [initial_state]
    
    best_valid_plan = None
    best_valid_score = -float('inf')
    
    for step in range(max_markers):
        new_beam = []
        
        for state in beam:
            if check_validity(state['rem']):
                score = calc_plan_score(state['markers'], state['produced'])
                if score > best_valid_score:
                    best_valid_score = score
                    best_valid_plan = state['markers']
            
            active_sizes = [s for s in sizes if state['rem'][s] > 0]
            if 0 < len(active_sizes) <= max_sizes_per_marker:
                finisher_candidates = []
                for L in range(max_layers, min_layers - 1, -1):
                    f_ratios = {}
                    f_valid = True
                    for s in active_sizes:
                        r = math.ceil(state['rem'][s] / L)
                        if r == 0:
                            r = 1
                        prod = r * L
                        if state['produced'][s] + prod > max_allowed[s]:
                            f_valid = False
                            break
                        f_ratios[s] = r
                    
                    if f_valid:
                        cand = build_candidate(state, L, f_ratios, base_score=1800)
                        if cand is not None:
                            finisher_candidates.append(cand)
                
                finisher_candidates.sort(key=lambda x: x['score'], reverse=True)
                for cand in finisher_candidates[:8]:
                    new_rem = state['rem'].copy()
                    new_produced = state['produced'].copy()
                    for s, r in cand['ratios'].items():
                        new_rem[s] -= r * cand['layers']
                        new_produced[s] += r * cand['layers']
                    
                    new_state = {
                        'markers': state['markers'] + [{
                            'layers': cand['layers'],
                            'ratios': cand['ratios'],
                            'sum': cand['sum']
                        }],
                        'rem': new_rem,
                        'produced': new_produced
                    }
                    if check_validity(new_state['rem']):
                        f_score = calc_plan_score(new_state['markers'], new_state['produced'])
                        if f_score > best_valid_score:
                            best_valid_score = f_score
                            best_valid_plan = new_state['markers']
                    new_beam.append(new_state)
            
            candidates = []
            seen_candidate_keys = set()
            
            def add_candidate(cand):
                if cand is None:
                    return
                key = (cand['layers'], ratio_signature(cand['ratios']))
                if key in seen_candidate_keys:
                    return
                seen_candidate_keys.add(key)
                candidates.append(cand)
            
            # 先尝试复用已有版型
            reusable_patterns = {}
            for marker in state['markers']:
                sig = ratio_signature(marker['ratios'])
                if sig not in reusable_patterns:
                    reusable_patterns[sig] = {
                        'ratios': marker['ratios'].copy(),
                        'layers_list': []
                    }
                reusable_patterns[sig]['layers_list'].append(marker['layers'])
            
            for info in reusable_patterns.values():
                base_layers = max(info['layers_list'])
                candidate_layers = {base_layers}
                for delta in (-2, -1, 1, 2):
                    candidate_layers.add(base_layers + delta)
                
                for L in sorted(candidate_layers, reverse=True):
                    if not (min_layers <= L <= max_layers):
                        continue
                    cand = build_candidate(
                        state,
                        L,
                        info['ratios'],
                        base_score=2800,
                        reuse_bonus=3200,
                        source_layers=base_layers
                    )
                    add_candidate(cand)
            
            # 再生成全新组合：高层优先，且优先把“整床长度”塞满
            for L in range(max_layers, min_layers - 1, -1):
                size_options = []
                for s in sizes:
                    if state['rem'][s] <= 0:
                        continue
                    
                    r_floor = state['rem'][s] // L
                    r_ceil = math.ceil(state['rem'][s] / L)
                    
                    valid_rs = []
                    candidate_rs = {r_floor, r_ceil, r_ceil + 1, 1, 2, 3}
                    if max_ratio_sum >= 12:
                        candidate_rs.add(4)
                    for r in candidate_rs:
                        if r < 1:
                            continue
                        prod = r * L
                        if state['produced'][s] + prod <= max_allowed[s]:
                            waste_r = max(0, prod - state['rem'][s])
                            removed_r = min(state['rem'][s], prod)
                            score_r = removed_r * 10 - waste_r * 55
                            if prod >= state['rem'][s]:
                                score_r += 1800
                            if prod == state['rem'][s]:
                                score_r += 4200
                            if r in (1, 2, 3):
                                score_r += 280
                            valid_rs.append({'size': s, 'r': r, 'score': score_r})
                    
                    if valid_rs:
                        valid_rs.sort(key=lambda x: x['score'], reverse=True)
                        size_options.append(valid_rs[:2])
                
                if not size_options:
                    continue
                
                for k in range(1, min(len(size_options), max_sizes_per_marker) + 1):
                    for combo_groups in combinations(size_options, k):
                        for combo in product(*combo_groups):
                            ratios = {x['size']: x['r'] for x in combo}
                            cand = build_candidate(
                                state,
                                L,
                                ratios,
                                base_score=sum(x['score'] for x in combo),
                                reuse_bonus=0
                            )
                            add_candidate(cand)
            
            candidates.sort(key=lambda x: x['score'], reverse=True)
            
            for cand in candidates[:BRANCHES_PER_STATE]:
                new_rem = state['rem'].copy()
                new_produced = state['produced'].copy()
                for s, r in cand['ratios'].items():
                    new_rem[s] -= r * cand['layers']
                    new_produced[s] += r * cand['layers']
                
                new_state = {
                    'markers': state['markers'] + [{
                        'layers': cand['layers'],
                        'ratios': cand['ratios'],
                        'sum': cand['sum']
                    }],
                    'rem': new_rem,
                    'produced': new_produced
                }
                new_beam.append(new_state)
                
        unique_states = {}
        for st in new_beam:
            sig = tuple(sorted((m['layers'], ratio_signature(m['ratios'])) for m in st['markers']))
            
            waste = sum(max(0, st['produced'][s] - targets[s]) for s in sizes)
            removed = sum(min(targets[s], st['produced'][s]) for s in sizes)
            thick_bonus = sum((m['layers'] ** 1.35) * 35 for m in st['markers'])
            completed = sum(1 for s in sizes if st['produced'][s] >= targets[s])
            bed_fill_score = calc_bed_fill_score(st['markers'])
            reuse_bonus = calc_pattern_reuse_bonus(st['markers']) * strategy_cfg['reuse_weight']
            long_thin_penalty = sum(calc_long_thin_penalty(m) for m in st['markers'])
            singleton_tail_penalty = calc_singleton_tail_penalty(st['markers'])
            
            orphan_penalty = 0
            for s in sizes:
                rem_val = targets[s] - st['produced'][s]
                if 0 < rem_val < 5:
                    orphan_penalty += 60000
                elif 5 <= rem_val < 10:
                    orphan_penalty += 24000
            
            thin_layer_penalty = 0
            for m in st['markers']:
                if m['layers'] < 4:
                    thin_layer_penalty += 12000
                elif m['layers'] < 8:
                    thin_layer_penalty += 5000
            
            ratio_concentration_penalty = sum(calc_ratio_concentration_penalty(m['ratios']) for m in st['markers']) * strategy_cfg['ratio_penalty_weight']
            dominant_marker_penalty = calc_dominant_marker_penalty(st['markers']) * strategy_cfg['dominant_penalty_weight']
            marker_balance_penalty = calc_marker_balance_penalty(st['markers']) * strategy_cfg['balance_penalty_weight']
            marker_structure_penalty = calc_marker_structure_penalty(st['markers'])

            st_score = (
                removed * 95
                - waste * 700
                + thick_bonus
                + completed * 18000
                + reuse_bonus
                + bed_fill_score
                - ratio_concentration_penalty
                - dominant_marker_penalty
                - marker_balance_penalty
                - marker_structure_penalty
                - long_thin_penalty
                - singleton_tail_penalty
                - orphan_penalty
                - thin_layer_penalty
            )
            
            if sig not in unique_states or st_score > unique_states[sig]['_score']:
                st['_score'] = st_score
                unique_states[sig] = st
                
        sorted_states = sorted(unique_states.values(), key=lambda x: x['_score'], reverse=True)
        beam = sorted_states[:BEAM_WIDTH]
        
    for state in beam:
        if check_validity(state['rem']):
            score = calc_plan_score(state['markers'], state['produced'])
            if score > best_valid_score:
                best_valid_score = score
                best_valid_plan = state['markers']

    if best_valid_plan is None:
        return sizes, None

    best_valid_plan = normalize_marker_order(best_valid_plan)
    return sizes, best_valid_plan

def generate_html_table(sizes, initial_orders, markers, style_no="", color="", cut_type="", layout_dir="", special_process="", overage_pct=0, shortage_pct=0, allow_large_to_small=False, idx_str="", manual_note_text="", explicit_mappings=None, display_mappings=None):
    date_str = datetime.now().strftime("%Y年%m月%d日")
    
    sizes_js = [str(s) for s in sizes]
    initial_orders_js = {str(s): initial_orders[s] for s in sizes}
    
    table_html = '<table style="width:100%; text-align:center; border-collapse: collapse; font-family: sans-serif; font-size: 16px;">'
    
    header_parts = []
    if style_no.strip(): header_parts.append(f'🏷️ 款号：<span style="color:#c00;">{style_no.strip()}</span>')
    if color.strip(): header_parts.append(f'🎨 颜色：<span style="color:#0066cc;">{color.strip()}</span>')
    if cut_type.strip(): header_parts.append(f'✂️ 裁片：{cut_type.strip()}</span>')
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
        if display_mappings is not None:
            for item in display_mappings:
                substitutions_map[item['from_size']].append(f"↘改{item['to_size']}码({item['qty']})")
            auto_note_text = '；'.join([f"{x['from_size']}码改{x['to_size']}码({x['qty']}件)" for x in display_mappings])
        elif explicit_mappings is not None:
            produced_map = {s: int(initial_orders[s] - current_remains[idx]) for idx, s in enumerate(sizes)}
            raw_over, raw_short, final_over, final_short, applied, fill_notes, warnings = apply_explicit_mappings(initial_orders, produced_map, sizes, explicit_mappings)
            final_display_remains = []
            for s in sizes:
                if final_short.get(s, 0) > 0:
                    final_display_remains.append(final_short[s])
                elif final_over.get(s, 0) > 0:
                    final_display_remains.append(-final_over[s])
                else:
                    final_display_remains.append(0)
            for item in applied:
                substitutions_map[item['from_size']].append(f"↘改{item['to_size']}码({item['qty']})")
            auto_note_text = '；'.join([f"{x['from_size']}码改{x['to_size']}码({x['qty']}件)" for x in applied])
        else:
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
                        
    auto_note_clean = (auto_note_text or '').strip().rstrip('；;')
    manual_note_clean = (manual_note_text or '').strip()
    if auto_note_clean:
        display_note_html = f'<span style="color:#0066cc;font-weight:bold;">{html.escape(auto_note_clean).replace(chr(10), "<br>")}</span>'
        if manual_note_clean:
            display_note_html += f'<span style="color:#999;font-weight:normal;"> {html.escape(manual_note_clean).replace(chr(10), "<br>")}</span>'
        else:
            display_note_html += '<span style="color:#999;font-weight:normal;">（点击此处可继续补充手动备注…）</span>'
    elif manual_note_clean:
        display_note_html = f'<span style="color:#999;font-weight:normal;">{html.escape(manual_note_clean).replace(chr(10), "<br>")}</span>'
    else:
        display_note_html = '<span style="color:#999;font-weight:normal;">（点击此处可继续补充手动备注…）</span>'

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
                <span id="auto-note" style="color: #0066cc; font-weight: bold;">{auto_note_clean}</span>
                <div contenteditable="true" class="remark-input" style="flex-grow: 1; border-bottom: 1px solid #aaa; outline: none; padding: 0 5px; color: #333; cursor: text; margin-left: 8px;" placeholder="(点击此处可继续补充手动备注...)">{manual_note_clean}</div>
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

# ================= 辅助工具 =================
def safe_eval_expr(expr):
    try:
        expr = str(expr).strip()
        if not expr:
            return 0
        if re.match(r'^[\d\+\-\*\/\(\)]+$', expr):
            return max(0, int(eval(expr, {"__builtins__": None}, {})))
        return 0
    except Exception:
        return 0


def parse_pasted_orders(raw_text):
    lines = [line.strip() for line in str(raw_text).splitlines() if line.strip()]
    if not lines:
        return [], {}, ''

    tokenized = []
    for line in lines:
        tokens = [tok.strip() for tok in re.split(r'[\t,，;； ]+', line) if tok.strip()]
        if tokens:
            tokenized.append(tokens)

    def looks_like_qty(tok):
        return bool(re.match(r'^[\d\+\-\*\/\(\)]+$', tok))

    # 方案1：两行横向粘贴（第一行尺码，第二行数量）
    if len(tokenized) >= 2:
        sizes_row, qty_row = tokenized[0], tokenized[1]
        if len(sizes_row) == len(qty_row) and len(sizes_row) > 0 and sum(1 for x in qty_row if looks_like_qty(x)) >= max(1, len(qty_row) - 1):
            sizes = []
            orders = {}
            for s, q in zip(sizes_row, qty_row):
                if s not in sizes:
                    sizes.append(s)
                qv = safe_eval_expr(q)
                if qv > 0:
                    orders[s] = qv
            if sizes:
                return sizes, orders, 'two_row'

    # 方案2：两列纵向粘贴（每行一个尺码+件数）
    sizes = []
    orders = {}
    valid_pairs = 0
    for row in tokenized:
        if len(row) >= 2 and looks_like_qty(row[-1]):
            size = row[0]
            qty = safe_eval_expr(row[-1])
            if size not in sizes:
                sizes.append(size)
            if qty > 0:
                orders[size] = qty
            valid_pairs += 1
    if valid_pairs > 0 and sizes:
        return sizes, orders, 'two_col'

    return [], {}, ''


def build_marker_editor_df(valid_sizes, markers):
    real_markers = [m for m in markers if not m.get('is_tail', False)]
    rows = []
    for idx, m in enumerate(real_markers, start=1):
        row = {
            '版号': idx,
            '层数': int(m.get('layers', 0)),
            '标记': '⚡优先' if m.get('is_priority') else ''
        }
        for s in valid_sizes:
            row[s] = int(m.get('ratios', {}).get(s, 0))
        row['配比和'] = int(sum(row[s] for s in valid_sizes))
        rows.append(row)
    return pd.DataFrame(rows)


def editor_df_to_markers(df, valid_sizes, base_markers):
    markers = []
    base_real = [m for m in base_markers if not m.get('is_tail', False)]
    for idx, row in df.iterrows():
        ratios = {}
        ratio_sum = 0
        for s in valid_sizes:
            try:
                val = int(row.get(s, 0) or 0)
            except Exception:
                val = 0
            val = max(0, val)
            if val > 0:
                ratios[s] = val
            ratio_sum += val
        try:
            layers = int(row.get('层数', 0) or 0)
        except Exception:
            layers = 0
        layers = max(0, layers)
        base = base_real[idx] if idx < len(base_real) else {}
        if layers > 0 and ratio_sum > 0:
            markers.append({
                'layers': layers,
                'ratios': ratios,
                'sum': ratio_sum,
                'is_priority': base.get('is_priority', False),
            })
    return markers


def default_big_to_small_rules(valid_sizes):
    rules = []
    for i in range(len(valid_sizes) - 1, 0, -1):
        from_size = valid_sizes[i]
        to_sizes = valid_sizes[:i]
        rules.append({'from_size': from_size, 'to_sizes': to_sizes})
    return rules


def apply_custom_big_to_small(orders, produced, ordered_sizes, rules):
    raw_over = {s: max(produced.get(s, 0) - orders.get(s, 0), 0) for s in ordered_sizes}
    raw_short = {s: max(orders.get(s, 0) - produced.get(s, 0), 0) for s in ordered_sizes}
    final_over = raw_over.copy()
    final_short = raw_short.copy()
    applied = []
    fill_notes = {s: [] for s in ordered_sizes}

    for rule in rules:
        from_size = str(rule.get('from_size', '')).strip()
        to_sizes = [str(x).strip() for x in rule.get('to_sizes', []) if str(x).strip()]
        if from_size not in final_over or final_over[from_size] <= 0:
            continue
        available = final_over[from_size]
        for to_size in to_sizes:
            if to_size not in final_short or to_size == from_size:
                continue
            need = final_short[to_size]
            if need <= 0 or available <= 0:
                continue
            fill = min(available, need)
            final_over[from_size] -= fill
            final_short[to_size] -= fill
            available -= fill
            applied.append({'from_size': from_size, 'to_size': to_size, 'qty': fill})
            fill_notes[to_size].append(f'{from_size}→{to_size}({fill})')
            if available <= 0:
                break
    return raw_over, raw_short, final_over, final_short, applied, fill_notes


def parse_big_to_small_note(note_text, valid_sizes):
    mappings = []
    if not str(note_text).strip():
        return mappings, []

    text = str(note_text).replace('；', ';').replace('，', ',').replace('、', ';')
    pattern = re.compile(r'([A-Za-z0-9]+)码?改([A-Za-z0-9]+)码?\((\d+)件?\)')
    invalid_chunks = []
    for chunk in [x.strip() for x in re.split(r'[;\n]+', text) if x.strip()]:
        m = pattern.search(chunk)
        if not m:
            invalid_chunks.append(chunk)
            continue
        from_size, to_size, qty = m.group(1), m.group(2), int(m.group(3))
        if from_size in valid_sizes and to_size in valid_sizes and from_size != to_size and qty > 0:
            mappings.append({'from_size': from_size, 'to_size': to_size, 'qty': qty})
        else:
            invalid_chunks.append(chunk)
    return mappings, invalid_chunks


def apply_explicit_mappings(orders, produced, ordered_sizes, mappings):
    raw_over = {s: max(produced.get(s, 0) - orders.get(s, 0), 0) for s in ordered_sizes}
    raw_short = {s: max(orders.get(s, 0) - produced.get(s, 0), 0) for s in ordered_sizes}
    final_over = raw_over.copy()
    final_short = raw_short.copy()
    applied = []
    fill_notes = {s: [] for s in ordered_sizes}
    warnings = []

    for mp in mappings:
        from_size = mp['from_size']
        to_size = mp['to_size']
        req_qty = int(mp['qty'])
        available = final_over.get(from_size, 0)
        need = final_short.get(to_size, 0)
        actual = min(req_qty, available, need)
        if actual <= 0:
            warnings.append(f"{from_size}改{to_size}({req_qty}件) 未生效：无可用增裁或无对应短装。")
            continue
        if actual < req_qty:
            warnings.append(f"{from_size}改{to_size}({req_qty}件) 已按可用数量折算为 {actual} 件。")
        final_over[from_size] -= actual
        final_short[to_size] -= actual
        applied.append({'from_size': from_size, 'to_size': to_size, 'qty': actual})
        fill_notes[to_size].append(f'{from_size}→{to_size}({actual})')
    return raw_over, raw_short, final_over, final_short, applied, fill_notes, warnings


def build_default_note_text(valid_sizes, orders, markers):
    _df, meta = build_summary_df(valid_sizes, orders, markers, allow_large_to_small=True)
    if not meta.get('applied'):
        return ''
    return '；'.join([f"{x['from_size']}码改{x['to_size']}码({x['qty']}件)" for x in meta['applied']])


def build_summary_df(valid_sizes, orders, markers, allow_large_to_small=False, rules=None, explicit_mappings=None):
    produced = {s: 0 for s in valid_sizes}
    for marker in markers:
        if marker.get('is_tail', False):
            continue
        for s in valid_sizes:
            produced[s] += int(marker.get('ratios', {}).get(s, 0)) * int(marker.get('layers', 0))

    warnings = []
    if allow_large_to_small:
        if explicit_mappings is not None:
            raw_over, raw_short, final_over, final_short, applied, fill_notes, warnings = apply_explicit_mappings(orders, produced, valid_sizes, explicit_mappings)
        else:
            rules = rules or default_big_to_small_rules(valid_sizes)
            raw_over, raw_short, final_over, final_short, applied, fill_notes = apply_custom_big_to_small(orders, produced, valid_sizes, rules)
    else:
        raw_over = {s: max(produced.get(s, 0) - orders.get(s, 0), 0) for s in valid_sizes}
        raw_short = {s: max(orders.get(s, 0) - produced.get(s, 0), 0) for s in valid_sizes}
        final_over = raw_over.copy()
        final_short = raw_short.copy()
        applied = []
        fill_notes = {s: [] for s in valid_sizes}

    rows = []
    for s in valid_sizes:
        rows.append({
            '尺码': s,
            '订单数': int(orders.get(s, 0)),
            '实裁数': int(produced.get(s, 0)),
            '原始增裁': int(raw_over.get(s, 0)),
            '原始短装': int(raw_short.get(s, 0)),
            '大改小抵扣': '；'.join(fill_notes.get(s, [])),
            '最终增裁': int(final_over.get(s, 0)),
            '最终短装': int(final_short.get(s, 0)),
        })
    df = pd.DataFrame(rows)
    meta = {
        'total_produced': sum(produced.values()),
        'total_final_over': sum(final_over.values()),
        'total_final_short': sum(final_short.values()),
        'applied': applied,
        'warnings': warnings,
    }
    return df, meta

def render_manual_edit_section(cut_idx, cut_name, valid_sizes, orders, markers, allow_large_to_small, style_no="", color="", layout_dir="", special_process="", overage_pct=0, shortage_pct=0):
    st.markdown('---')
    st.subheader(f'🛠️ 【{cut_name}】手动修改区')
    st.caption('这里直接改层数、配比；如果开启了大改小，就通过“备注输入框”改，大改小结果会自动联动到下方汇总表。')

    editor_key = f'marker_editor_{cut_idx}'
    sig_key = f'marker_editor_sig_{cut_idx}'
    note_key = f'manual_note_{cut_idx}'
    plan_sig = json.dumps([{
        'layers': int(m.get('layers', 0)),
        'ratios': {s: int(m.get('ratios', {}).get(s, 0)) for s in valid_sizes},
        'is_priority': bool(m.get('is_priority', False)),
    } for m in markers if not m.get('is_tail', False)], ensure_ascii=False, sort_keys=True)
    if editor_key not in st.session_state or st.session_state.get(sig_key) != plan_sig:
        st.session_state[editor_key] = build_marker_editor_df(valid_sizes, markers)
        st.session_state[sig_key] = plan_sig
        if allow_large_to_small:
            st.session_state[note_key] = build_default_note_text(valid_sizes, orders, [m for m in markers if not m.get('is_tail', False)])
        else:
            st.session_state[note_key] = ''

    edited_df = st.data_editor(
        st.session_state[editor_key],
        use_container_width=True,
        num_rows='fixed',
        key=f'editor_widget_{cut_idx}',
        hide_index=True,
        disabled=['版号', '标记', '配比和'],
    )

    if '配比和' not in edited_df.columns:
        edited_df['配比和'] = 0
    numeric_ratio_df = edited_df[valid_sizes].apply(pd.to_numeric, errors='coerce').fillna(0).astype(int)
    edited_df['配比和'] = numeric_ratio_df.sum(axis=1)
    st.session_state[editor_key] = edited_df

    explicit_mappings = None
    invalid_chunks = []
    if allow_large_to_small:
        st.markdown('##### 大改小备注（修改这里，下方汇总自动联动）')
        st.caption('输入格式示例：165码改140码(4件)；160码改140码(1件)；130码改120码(2件)')
        st.text_area('大改小备注', key=note_key, height=90, label_visibility='collapsed')
        explicit_mappings, invalid_chunks = parse_big_to_small_note(st.session_state.get(note_key, ''), valid_sizes)
    else:
        st.info('当前未开启大改小，总开关关闭时这里只做层数和配比重算。')

    edited_markers = editor_df_to_markers(edited_df, valid_sizes, markers)
    summary_df, meta = build_summary_df(
        valid_sizes,
        orders,
        edited_markers,
        allow_large_to_small,
        explicit_mappings=explicit_mappings if allow_large_to_small else None,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric('重算总产出', meta['total_produced'])
    c2.metric('重算最终增裁', meta['total_final_over'])
    c3.metric('重算最终短装', meta['total_final_short'])

    st.markdown('##### 重算后尺码汇总')
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    if allow_large_to_small and st.session_state.get(note_key, '').strip():
        st.markdown(f"**当前备注：** {st.session_state[note_key]}")

    if meta.get('applied'):
        note = '；'.join([f"{x['from_size']}→{x['to_size']}({x['qty']})" for x in meta['applied']])
        st.success(f'大改小实际生效：{note}')

    if invalid_chunks:
        st.warning('以下备注片段未识别，已忽略：' + '；'.join(invalid_chunks))
    if meta.get('warnings'):
        for w in meta['warnings']:
            st.warning(w)

    st.markdown('##### 联动预览（以手动修改区当前内容为准）')
    preview_html = generate_html_table(
        valid_sizes,
        orders,
        edited_markers,
        style_no=style_no,
        color=color,
        cut_type=cut_name,
        layout_dir=layout_dir,
        special_process=special_process,
        overage_pct=overage_pct,
        shortage_pct=shortage_pct,
        allow_large_to_small=allow_large_to_small,
        idx_str=f"manual_{cut_idx}",
        manual_note_text=st.session_state.get(note_key, ''),
        explicit_mappings=explicit_mappings if allow_large_to_small else None,
    )
    components.html(preview_html, height=760, scrolling=True)

st.set_page_config(page_title="蓉成服饰排料系统1.0", layout="wide")

st.markdown("""
<style>
div[data-testid="stTextInput"] input {
    min-height: 2.35rem;
}
div[data-testid="stTextInput"] {
    margin-top: -6px;
    margin-bottom: 4px;
}
</style>
""", unsafe_allow_html=True)


# 轻量界面样式：让参数区更清楚，方便交给车间同事直接使用
st.markdown("""
<style>
.block-container {padding-top: 1.1rem; padding-bottom: 2rem;}
.option-help {
    background: #f7fbff;
    border: 1px solid #d7e9ff;
    border-left: 4px solid #3b82f6;
    border-radius: 8px;
    padding: 10px 12px;
    margin: 4px 0 8px 0;
    font-size: 13px;
    color: #1f3b64;
}
.section-note {
    background: #fffaf0;
    border: 1px solid #f5deb3;
    border-radius: 10px;
    padding: 12px 14px;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

def inline_help(title, body):
    st.markdown(f'<div class="option-help"><b>{title}</b><br>{body}</div>', unsafe_allow_html=True)

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
st.markdown('<div class="section-note"><b>使用建议：</b>系统现在默认按更贴近车间的多版结构骨架去自动出底稿：先主版、再过渡、最后扫尾；自动结果出来后，可在下方直接手动改层数、配比和大改小规则。</div>', unsafe_allow_html=True)

st.subheader("📝 步骤 1：款式信息")

col_style, col_color, col_layout, col_special = st.columns(4)
with col_style:
    style_no = st.text_input("👗 款号 (选填)：", placeholder="RC-001")
with col_color:
    color = st.text_input("🎨 颜色 (选填)：", placeholder="藏青色")
with col_layout:
    layout_dir = st.selectbox("↕️ 排列方式：", options=["任意", "同码同向", "件份同向", "同一方向"], index=1)
with col_special:
    special_process = st.text_input("✨ 特殊工艺 (选填)：", placeholder="如: 加衬/对条/手拉")

st.subheader("📦 步骤 2：录入订单")
orders = {}
sizes_list = []

manual_size_input = st.text_input("尺码（空格隔开）", value="")
manual_qty_input = st.text_input("对应件数（支持 1+1 / 2-1，空格隔开）", value="")

for s in re.split(r'[,，\s、\-]+', manual_size_input.strip()):
    if s and s not in sizes_list:
        sizes_list.append(s)

raw_qtys = re.split(r'[,，\s、]+', manual_qty_input.strip()) if sizes_list else []
for idx, size in enumerate(sizes_list):
    if idx < len(raw_qtys) and raw_qtys[idx]:
        val = safe_eval_expr(raw_qtys[idx])
        if val > 0:
            orders[size] = val

if sizes_list:
    mapping_str = " &nbsp;&nbsp;|&nbsp;&nbsp; ".join([f"<span style='font-size:18px; color:#333;'>{s}码: <b style='color:#cc0000; font-size:24px;'>{orders.get(s, 0)}</b></span>" for s in sizes_list])
    st.markdown(f"""
    <div style='background-color: #f0f8ff; padding: 15px 20px; border-radius: 8px; border: 2px solid #b3d4fc; margin-top: 10px; margin-bottom: 15px;'>
        <div style='font-size: 16px; color: #0056b3; margin-bottom: 10px;'><b>🔍 当前录入核对：</b></div>
        <div style='line-height: 2.0;'>{mapping_str}</div>
    </div>
    """, unsafe_allow_html=True)

total_order_qty = sum(orders.values())
if total_order_qty > 0:
    st.info(f"💡 当前全局订单总需求为： **{total_order_qty}** 件")
else:
    st.info("💡 当前全局订单总需求为： **0** 件")

if enable_priority:
    st.sidebar.info("💡 提示：系统会将包含你急需尺码的大货版直接置顶，不额外拆出很薄的小版。")
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
        default_cut_name = f"裁片{i+1}"
        cut_name = st.text_input(f"🏷️ 此面料/裁片名称：", value=default_cut_name, key=f"c_name_{i}")

        st.markdown("##### ⚙️ 排料参数设置")
        c1, c2, c3, c4 = st.columns(4)
        with c1: c_min_layers = st.number_input("最低层数", min_value=1, value=1, key=f"c_minL_{i}")
        with c2: c_max_layers = st.number_input("最高层数", min_value=0, value=0, key=f"c_maxL_{i}")
        with c3: c_ov_pct = st.number_input("溢装率 (%)", min_value=0, value=5, key=f"c_ov_{i}")
        with c4: c_sh_pct = st.number_input("允许短装率 (%)", min_value=0, value=0, key=f"c_sh_{i}")

        c5, c6, c7 = st.columns(3)
        with c5: c_rs = st.number_input("配比和上限", min_value=0, value=0, key=f"c_rs_{i}")
        with c6: c_mm = st.number_input("总版数上限", min_value=0, value=0, key=f"c_mm_{i}")
        with c7: c_spm = st.number_input("单版最多尺码数", min_value=0, value=0, key=f"c_spm_{i}")

        c8, c9, c10 = st.columns(3)
        with c8:
            c_l2s = st.checkbox(f"✨ 允许大改小", value=False, key=f"c_l2s_{i}", help="打开总开关后，可在结果下方按备注规则显示大改小。")
        with c9:
            c_sh = st.checkbox(f"✂️ 启用「面料不足模式」", value=False, key=f"c_sh_mode_{i}", help="来料不足时，在允许短装率范围内尽量保住不断码。")
        with c10:
            c_tail = st.checkbox(f"🔥 启用面料清尾", value=False, key=f"c_tail_{i}")

        c_tail_sizes = []
        if c_tail:
            c_tail_sizes = st.multiselect("👉 选择需清尾出件的尺码：", options=sizes_list, key=f"c_ts_{i}")

        st.caption("系统当前默认按更贴近现场的多版结构骨架自动出底稿；下方保留手动修改区，方便你再修。")
        
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
                        c_l2s, c_sh, '高低版优先', '标准'
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
                        msg = f"✅ 【{cut_name}】排版完毕！共使用了 **{len([m for m in markers if not m.get('is_tail')])}** 个大货版，产出 **{total_produced}** 件。已保留优先急单 / 面料清尾等原有能力，并新增结果后的手动修改区。"
                        
                        html_c = generate_html_table(
                            valid_sizes, orders, markers, style_no, color, cut_name, layout_dir, special_process, 
                            c_ov_pct, c_sh_pct, c_l2s, idx_str=str(i)
                        )
                        st.session_state[f'res_err_{i}'] = None
                        st.session_state[f'res_msg_{i}'] = msg
                        st.session_state[f'res_html_{i}'] = html_c
                        st.session_state[f'res_markers_{i}'] = markers
                        st.session_state[f'res_valid_sizes_{i}'] = valid_sizes
                        st.session_state[f'res_orders_{i}'] = orders.copy()
                        st.session_state[f'res_allow_l2s_{i}'] = c_l2s
                        st.session_state[f'res_cut_name_{i}'] = cut_name
                        st.session_state[f'res_meta_{i}'] = {
                            'style_no': style_no,
                            'color': color,
                            'layout_dir': layout_dir,
                            'special_process': special_process,
                            'overage_pct': c_ov_pct,
                            'shortage_pct': c_sh_pct,
                        }
                    else:
                        st.session_state[f'res_err_{i}'] = f"❌ 【{cut_name}】在当前的严苛限制下，未找到不超标的方案。请尝试放宽对应的限制条件（如总版数上限）。"
                        st.session_state[f'res_msg_{i}'] = None
                        st.session_state[f'res_html_{i}'] = None
                        st.session_state.pop(f'res_markers_{i}', None)
                        st.session_state.pop(f'res_valid_sizes_{i}', None)
                        st.session_state.pop(f'res_orders_{i}', None)

        if st.session_state.get(f'res_err_{i}'):
            st.error(st.session_state[f'res_err_{i}'])
        if st.session_state.get(f'res_msg_{i}'):
            st.success(st.session_state[f'res_msg_{i}'])
            st.subheader(f"📊 【{cut_name}】阶梯式扣减排料单")
            extra_remark_key = f'res_extra_remark_{i}'
            if extra_remark_key not in st.session_state:
                st.session_state[extra_remark_key] = ''

            current_html = generate_html_table(
                st.session_state[f'res_valid_sizes_{i}'],
                st.session_state[f'res_orders_{i}'],
                st.session_state[f'res_markers_{i}'],
                style_no=st.session_state.get(f'res_meta_{i}', {}).get('style_no', ''),
                color=st.session_state.get(f'res_meta_{i}', {}).get('color', ''),
                cut_type=st.session_state.get(f'res_cut_name_{i}', cut_name),
                layout_dir=st.session_state.get(f'res_meta_{i}', {}).get('layout_dir', ''),
                special_process=st.session_state.get(f'res_meta_{i}', {}).get('special_process', ''),
                overage_pct=st.session_state.get(f'res_meta_{i}', {}).get('overage_pct', 0),
                shortage_pct=st.session_state.get(f'res_meta_{i}', {}).get('shortage_pct', 0),
                allow_large_to_small=st.session_state.get(f'res_allow_l2s_{i}', False),
                idx_str=f'result_{i}',
                manual_note_text=st.session_state.get(extra_remark_key, '').strip(),
                display_mappings=None,
            )
            result_height = 360 + len(st.session_state.get(f'res_markers_{i}', [])) * 120
            result_height = max(500, min(700, result_height))
            components.html(current_html, height=result_height, scrolling=False)

