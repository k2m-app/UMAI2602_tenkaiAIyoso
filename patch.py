import sys
import codecs

try:
    with codecs.open("app.py", "r", "utf-8") as f:
        content = f.read()

    # Normalize line endings to help text splitting
    content = content.replace('\r\n', '\n')

    # Modify Matrix Duplication Issue
    content = content.replace(
        'final_output = ai_output + "\\n\\n" + battle_matrix_text',
        'final_output = ai_output'
    )

    replace_str = """            cached_data = load_race_cache(target_race_id, run_mode)
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
                
                # --- [4] 展開予想の表示 (app.py) ---
                st.info(f"📏 条件: **{current_venue} {current_track}{current_dist}m** ({total_horses}頭立て)  \\n" + race_title)
                
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
                            import pandas as pd
                            st.dataframe(pd.DataFrame(df_rows), use_container_width=True, hide_index=True)
                
                if run_mode in ("both", "ai"):
                    st.markdown(f"### 🤖 AI総合評価 ({race_num}R)")
                    st.markdown(final_output)

            else:
                with st.spinner(f"{race_num}R のデータ収集中..."):
"""
    parts = content.split('            with st.spinner(f"{race_num}R のデータ収集中..."):\\n')
    if len(parts) == 2:
        pre_spinner = parts[0]
        post_spinner = parts[1]
        
        inner_parts = post_spinner.split('                html_ai_output = format_dify_md_to_html(final_output)\\n')
        
        if len(inner_parts) == 2:
            inner_block = inner_parts[0]
            rest = inner_parts[1]
            
            indented_inner = "\\n".join(["    " + line for line in inner_block.split("\\n")])
            indented_html_ai = "                    html_ai_output = format_dify_md_to_html(final_output)\\n"
            
            save_block = """
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
"""
            new_content = pre_spinner + replace_str + indented_inner + indented_html_ai + save_block + rest
            
            with codecs.open("app.py", "w", "utf-8") as f:
                f.write(new_content)
            print("Success")
        else:
            print("Could not find html_ai_output block.")
    else:
        print("Could not find spinner block. Found count:", len(parts))

except Exception as e:
    import traceback
    traceback.print_exc()
