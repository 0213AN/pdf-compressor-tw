from pydoc import doc
import webbrowser
import fitz
from PIL import Image
import io
import os
import re
import sys
from pathlib import Path

#用來儲存每張圖片的最新指令，這樣在dry run預覽階段就能同時看到新舊指令的效果
current_img_setting = {} 

#全域參數預設值
quality = 75
width = 1080
dpi = 300
pdf_path = None
output_path = None

export_options = {
    "outline": True,      #大綱
    "annotation": True,   #註解
    "metadata": True      #詮釋資料 (分離資料儲存與資料取用)
}

def show_help():
    help_text = r"""
    --------------------------------------------------
    PDF壓縮工具 - 指令手冊 (v1.0)
    --------------------------------------------------
    [第一步：載入檔案]
    input [路徑]          載入 PDF 檔案 (支援帶引號路徑)
    範例: input C:\Users\使用者名稱\Documents\作業.pdf

    [第二步：壓縮圖片]
    格式: [頁碼]-[圖序]:[指令] (多張圖用逗號隔開)
    範例: 1-1:q50, 2-1:w1080, 3-1:cP

    指令說明:
    q[1-95]  : 設定 JPEG 品質 (越低檔案越小)
    w[像素]  : 設定圖片寬度 (高度等比例縮放)
    c[模式]  : 色彩模式 (P: 縮減顏色, RGB: 全彩, L: 灰階)
            *支援多重指令，例如: 3-2:cRGBq30

    [第三步：儲存結果]
    save                  執行最終壓縮並儲存檔案
    output [路徑]         修改儲存路徑 (預設為原檔名_compressed)

    [系統與進階指令]
    analyze               重新分析原始 PDF
    set quality:[數值]    更改全局預設品質 (預設 75)
    set width:[數值]      更改預設縮圖寬度 (預設 1080)
    del [項目]            切換開關，項目有: outline(大綱), annotation(註解), metadata(詮釋資料)
    exit                  結束程式
    help                  顯示此說明書
    --------------------------------------------------
    """
    url= "https://github.com/0213AN/pdf-compressor-tw/blob/main/README_zh-TW.md"
    print(help_text)
    print("詳細說明請參考 GitHub README")
    print(f"網址: {url}")
    confirm = input("是否直接為您開啟中文說明網頁？(y/n): ").strip().lower()
    if confirm == 'y':
        webbrowser.open(url)
    print("--------------------------------------------------")


# 設定全域參數的函式，處理 set quality, set width, set dpi 指令
def set_config(choice):
    global quality, width, dpi
    try:
        # 分割指令，例如從 "quality:70" 得到 ["quality", "70"]
        key, val = choice.split(":")
        val = int(val.strip()) # 轉成整數並去掉空格
        
        if key == "set quality":
            quality = val
            print(f"\n ✪ quality已設定為: {quality}")
        elif key == "set width":
            width = val
            print(f"\n ✪ width已設定為: {width}")
        elif key == "set dpi":
            dpi = val
            print(f"\n ✪ dpi已設定為: {dpi}")
            
    except Exception as e:
        print(f"✖ 設定失敗（範例 quality:70）。錯誤資訊: {e}")

# 刪除資料的函式，更改export_options的值
def delete_data(choice):
    option = choice[4:].strip().lower()
    if option in export_options:
        export_options[option] = not export_options[option]
    
    status = "刪除" if export_options[option] else "不刪除"
    print(f"✪ {status} {option} ✪  ")


#更新路徑的函式，處理 input 和 output 指令
def update_path(choice):
    global pdf_path, output_path   

    parts = choice.split(maxsplit=1)
    if len(parts) < 2:
        print("✖ 錯誤：請提供路徑 (例如: input C:\\test.pdf)")
        return None
    
    raw_path = parts[1].strip().strip('"') # 移除前後空白與可能的引號
    p = Path(raw_path)
    
    if p.suffix.lower() != ".pdf":
        print("提醒：路徑似乎少了副檔名 (.pdf) 或格式不正確")

    if parts[0].lower() == "input":
        if not p.exists():
            print(f"警告：找不到輸入檔案 {p}")
        pdf_path = str(p.resolve()) # 轉成絕對路徑字串
        print(f"✪ 輸入檔案路徑已更新為: {pdf_path}")
        
        if not output_path:
            output_path = str(p.with_name(f"{p.stem}_compressed.pdf").resolve())
            print(f"已自動預設輸出路徑: {output_path}")
        
    elif parts[0].lower() == "output":
        output_path = str(p.resolve()) 
        print(f"✪ 輸出檔案路徑已更新為: {output_path}")

# analyze PDF 的一環，根據圖片特性自動選擇壓縮方式並模擬省下的體積 。high impact ranking 就是根據這個來排序的
def predict_savings(target_img):
    pil_img = Image.open(io.BytesIO(target_img["image_bytes"]))
    temp_buffer = io.BytesIO()
    
    # 寬度縮放 (width為全域參數)
    if target_img["dpi"] > dpi or target_img["width"] > width:
        if target_img["width"] > width:
            ratio = width / target_img["width"]
            new_h = int(target_img["height"] * ratio)
            # 使用 LANCZOS 維持品質
            pil_img = pil_img.resize((width, new_h), Image.LANCZOS)
        
        # 縮放後轉 RGB 並儲存
        if pil_img.mode in ("RGBA", "P"):
            pil_img = pil_img.convert("RGB")
        pil_img.save(temp_buffer, format="JPEG", quality=quality)
    
    # 品質壓縮(quality 為全域參數)
    else:
        if pil_img.mode in ("RGBA", "P"):
            pil_img = pil_img.convert("RGB")
        pil_img.save(temp_buffer, format="JPEG", quality=quality)
    
    new_kb = len(temp_buffer.getvalue()) / 1024
    return max(0, target_img["size_kb"] - new_kb)

# ============階段一  整份PDF分析：列出每張圖片的特性，並排序　給出優先壓縮建議=============
def analyze_pdf(pdf_path):
    if not os.path.exists(pdf_path):
        print(f"✖ 找不到檔案: {pdf_path}")
        return None
    
    doc = fitz.open(pdf_path)
    total_file_size = os.path.getsize(pdf_path) / 1024  #getsize拿到的是byte
    img_data_total = 0
    img_list = []
    
    for page_index in range(len(doc)):
        page = doc[page_index]
        image_info_list = page.get_image_info(xrefs=True)
        
        for idx, img_info in enumerate(image_info_list):
            xref = img_info['xref']
            if xref == 0: continue
            
            base_img = doc.extract_image(xref)
            image_bytes = base_img["image"]
            img_size_kb = len(image_bytes) / 1024
            img_data_total += img_size_kb
            
            # 計算 DPI
            bbox = img_info['bbox']
            display_width_pt = max(bbox[2] - bbox[0], 1)
            display_height_pt = max(bbox[3] - bbox[1], 1)
            
            pixel_width = img_info['width']
            pixel_height = img_info['height']
            
            dpi_w = pixel_width / (display_width_pt / 72)
            dpi_h = pixel_height / (display_height_pt / 72)
            avg_dpi = (dpi_w + dpi_h) / 2
            
            #性價比efficiency，與之相對的是inefficient(這麼寫是方便之後的ranking list)
            efficiency = avg_dpi / img_size_kb if img_size_kb > 0 else 0
            
            #顏色分析，顏色數量少於256的建議轉PNG-8。但若圖片本身是P就不轉
            pil_img = Image.open(io.BytesIO(image_bytes))
            colors = pil_img.getcolors(maxcolors=256)
            img_type = "P" if colors else "RGB" 
            
            if pil_img.mode == img_type:
                img_type= "none"
                
            if pil_img.mode == "RGBA" and img_type == "RGB":
                img_type= "none"
                
            # append 之內容
            img_list.append({
                "id": f"{page_index + 1}-{idx + 1}",
                "page": page_index + 1,  
                "xref": xref,
                "size_kb": img_size_kb,
                "width": pixel_width,
                "height": pixel_height,
                "dpi": avg_dpi,
                "efficiency": efficiency,
                "type": img_type,
                "image_bytes": image_bytes
            })
            
    others_size = total_file_size - img_data_total

    # 輸出總報表
    print("\n")
    print("=====Summary of your PDF=====")
    print(f"原始 PDF大小：{total_file_size/1024:.2f} MB")
    print(f"圖片總體積 : {img_data_total/1024:.2f} MB")
    print(f"其他資訊總體積：　{others_size/1024:.2f} MB")
    print("=====Each IMG=====")

    current_page = -1
    for img in img_list:
        if img["page"] != current_page:
            current_page = img["page"]
            page_imgs = [i for i in img_list if i["page"] == current_page]
            print("\n")  
            print(f"Page {current_page}  has {len(page_imgs)} images")
                    
        # 列出每頁的各個圖片資訊
        row1 = (f"{img['id']}   xref:{img['xref']}     Size: {img['size_kb']:.2f}KB     "
                f"width: {img['width']}     height: {img['height']}     dpi {int(img['dpi'])}")
        print(row1)
        
        row2 = (f"       efficiency: {int(img['efficiency'])}       "
                f"ColorsSuggestion: {img['type']}")
        print(row2)
        
    # 1. 根據 efficiency 排序 (從小到大，數值小的代表該圖片的性價比越差)
    sorted_imgs = sorted(img_list, key=lambda x: x["efficiency"])

    # 2. 計算前 20% 的數量 (至少 1 張)，ranking是全體圖片排行，targets是前20%的圖片清單
    inefficient_ranking = max(1, int(len(sorted_imgs) * 0.2))
    low_efficiency_targets = sorted_imgs[:inefficient_ranking]
    print("\n")
    print("===== inefficiency ranking =====")
    print(f"根據分析，以下 {inefficient_ranking} 張圖片佔用空間大， DPI 過高，建議優先壓縮：")

    for target in low_efficiency_targets:
    # 根據 DPI 給出具體指令建議，如果高於全域參數 dpi 就建議縮圖，否則建議降低品質
        if target["dpi"] > dpi:
            advice = f"☛ 建議下指令 {target['id']}:w1080 (目前 DPI {int(target['dpi'])} 太高)"
        else:
            advice = f"☛ 建議下指令 {target['id']}:q75 (降低品質)"
            
        print(f"→ 圖片 {target['id']}: 原體積: {target['size_kb']:.1f} KB | 效率: {target['efficiency']:.1f} | 建議: {advice}")
    
    print("-" * 35)

    #預期節省空間排名-high_impact，排序依據是「預期節省空間」，方法是全體圖片根據根據其特性模擬壓縮==>排名節省的體積
    for img in img_list:
        img["expected_save"] = predict_savings(img)
        
    # 按照預期節省空間從大到小排序 (reverse=True)
    sorted_imgs = sorted(img_list, key=lambda x: x["expected_save"], reverse=True)
    target_count = max(1, int(len(sorted_imgs) * 0.2))
    high_impact = sorted_imgs[:target_count]
    
    print("\n===== high impact ranking =====")
    total_possible_saved = 0

    for target in high_impact:
        total_possible_saved += target["expected_save"]
    
    # 給出不同建議
        if target["dpi"] > dpi or target["width"] > 1200:
            cmd_hint = f"{target['id']}:w1080"
            reason = f"建議縮圖"
        else:
            cmd_hint = f"{target['id']}:q75"
            reason = f"降低品質"
        
        print(f"→ 圖片 {target['id']}: 可省 {target['expected_save']:.1f} KB | 建議: {cmd_hint} ({reason})")
        
    print(f"\n▶︎ 預估：若處理以上圖片，PDF 體積可從 {total_file_size/1024:.2f}MB 降至 {(total_file_size - total_possible_saved)/1024:.2f}MB")
    print("-" * 50)
    
    #img_list是全體圖片清單，裡面包含每張圖片的特性和預期節省空間；total_file_size是整份PDF的原始大小
    return img_list, total_file_size

## ==========階段2，根據使用者輸入進行dry run預覽====================
def dry_run_compression(user_choice, img_list):
    
    print("\n===== 檔案壓縮結果預覽 =======")
    total_saved_kb = 0
    trial_settings = current_img_setting.copy()    #叫做trial_settings是因為這個函式的目的是模擬預覽，複製一份current_img_setting，等下會和新來的指令一起做測試
    new_added = {}  #新來的指令先存這裡。不加入current_img_setting是因為還不知道他會不會讓檔案有效縮小。
    
    # 將每個指令一一分開，例如1-1:q70, 2-1:w1080
    commands = user_choice.split(",")

    for cmd in commands:
        cmd = cmd.strip()
        if ":" not in cmd: continue
        img_id, action = cmd.split(":")
        trial_settings[img_id] = action  #把新來的指令併入舊指令清單，因此trial_settings就是我們要模擬的所有指令的清單
        new_added[img_id] = action        #新指令自成一個清單
        
    for img_id, action in trial_settings.items():
        target= next((img for img in img_list if img['id'] == img_id), None)

        if target:
            original_kb = target["size_kb"]
            pil_img = Image.open(io.BytesIO(target["image_bytes"]))
            temp_buffer = io.BytesIO()
            
            #檢查action指令裡的q,w,c
            q_match = re.search(r'q(\d+)', action)
            w_match = re.search(r'w(\d+)', action)
            c_match = re.search(r'c([a-zA-Z]+)', action)
            
            chosen_quality = None
            is_transparent = (pil_img.mode == "RGBA")
            
            # 品質壓縮-quality
            if q_match:
                chosen_quality = int(q_match.group(1))
            
            # 寬度縮放-width
            if w_match:
                chosen_width = int(w_match.group(1))
                ratio = chosen_width / target["width"]
                new_h = int(target["height"] * ratio)
                pil_img = pil_img.resize((chosen_width, new_h), Image.LANCZOS)
            
            # 顏色模式轉換-
            chosen_color = None
            if c_match:
                chosen_color= c_match.group(1).upper()
                if chosen_color == "L":
                    pil_img = pil_img.convert("L")
                elif chosen_color == "P":
                    pil_img = pil_img.convert("P", palette=Image.ADAPTIVE, colors=256)
                elif chosen_color == "RGB":
                    pil_img = pil_img.convert("RGB")
                    
            #這裡專門處理要給temp buffer 的quality是多少，優先順序是：指令裡的q > current setting裡的q > 全域quality
            if chosen_quality is None:
                history_q = re.search(r'q(\d+)', current_img_setting.get(img_id, ""))
                if history_q:
                    chosen_quality = int(history_q.group(1))
                else:
                    chosen_quality = quality 

            #這裡專門處理要給temp buffer 的color是多少，優先順序是：指令裡的c > current setting裡的c
            if chosen_color is None:
                history_c = re.search(r'c([a-zA-Z]+)', current_img_setting.get(img_id, ""))
                if history_c:
                    chosen_color = history_c.group(1).upper()
            
            if chosen_color == "P":
                pil_img.save(temp_buffer, format="PNG")
                print(f"➠ 圖片 {img_id}: 轉換為 P 模式，存為 PNG (PNG-8)")
            
            elif is_transparent and chosen_color is None:
                print(f"⚠︎ 圖片 {img_id} 是透明圖(RGBA)，建議不要以 JPEG 儲存。請下 :cP 指令，轉為PNG-8。 \n") 
                # 轉 RGB 存成 JPEG 作為預覽
                if pil_img.mode in ("RGBA", "P"):
                    pil_img = pil_img.convert("RGB")
                    pil_img.save(temp_buffer, format="JPEG", quality=chosen_quality)
                    
            #JPEG只支援RGB和L，如果是其他模式就先轉RGB再存JPEG(如果原始圖片是RGB，顏色太多而轉成PNG-8，這裡還要再轉回來才能存進PDF。但這過程中是有減少圖片體積的，所以還是有意義的)
            else: 
                if pil_img.mode in ("RGBA", "P"):
                    pil_img = pil_img.convert("RGB")
                pil_img.save(temp_buffer, format="JPEG", quality=chosen_quality)
    
            new_kb = len(temp_buffer.getvalue()) / 1024
            saved = original_kb - new_kb
            if saved < 0:
                print(f"✖︎ 圖片 {img_id} 的指令 {action} 壓縮後反而變大了，不加入清單。\n")
            
            #如果新指令能幫我們省空間，就加入current_img_setting
            else:
                current_img_setting[img_id] = action 
                print(f"✔︎ 圖片 {img_id} 的指令 {action} 預計節省 {saved:.1f} KB，加入壓縮清單。")
                print(f"          從 {original_kb:.1f}KB -> {new_kb:.1f}KB \n")
                total_saved_kb += saved
                
            # DPI 警告(如果DPI太低可能會影響品質))
            new_dpi = (target["dpi"] * (chosen_width / target["width"])) if action.startswith("w") else target["dpi"]
            if new_dpi < 100:
                print(f"⚠︎ 警告: {img_id} 壓縮後 DPI 僅 {int(new_dpi)}，可能影響閱讀品質。 \n")
                
    return total_saved_kb

#階段三，根據current_img_setting裡的指令真正修改PDF內的圖片並存檔，只有這裡能看到.savePDF的內容，其他地方都是模擬預覽
def savePDF(export_options, current_img_setting):
    global pdf_path, output_path   
    doc = fitz.open(pdf_path)
    xref_to_id = {}
    
    #這裡把圖片的xref對應到img_id(x-y的字串型態)，因為在階段二(dry run)使用的img_id是"1-1"這種的
    # 第一層迴圈：只建對照表
    for page_index in range(len(doc)):
        page = doc[page_index]
        for idx, img_info in enumerate(page.get_image_info(xrefs=True)):
            xref = img_info['xref']
            if xref == 0: continue
            xref_to_id[xref] = f"{page_index + 1}-{idx + 1}"

    # 第二層迴圈：用對照表處理圖片
    for page_index in range(len(doc)):
        page = doc[page_index]
        for img_info in page.get_image_info(xrefs=True):
            xref = img_info['xref']
            if xref == 0: continue

            img_id = xref_to_id.get(xref)
            action = current_img_setting.get(img_id, "")
            if not action:
                continue
            
            # 1. 提取圖片
            base_img = doc.extract_image(xref)
            image_bytes = base_img["image"]
            pil_img = Image.open(io.BytesIO(image_bytes))

            # 2. 根據指令進行處理(QWC)
            q_match = re.search(r'q(\d+)', action)
            w_match = re.search(r'w(\d+)', action)
            c_match = re.search(r'c([a-zA-Z]+)', action)
            
            is_transparent = (pil_img.mode == "RGBA")
                    
            # 品質壓縮-quality
            chosen_quality = int(q_match.group(1)) if q_match else quality
                    
            # 寬度縮放-width
            if w_match:
                chosen_width = int(w_match.group(1))
                ratio = chosen_width / pil_img.width
                new_h = int(pil_img.height * ratio)
                pil_img = pil_img.resize((chosen_width, new_h), Image.LANCZOS)
                    
            # 顏色模式轉換-color
            chosen_color = None
            if c_match:
                chosen_color = c_match.group(1).upper()
                if chosen_color == "L":
                    pil_img = pil_img.convert("L")
                elif chosen_color == "RGB":
                    pil_img = pil_img.convert("RGB")

            # RGBA to RDB
            if is_transparent and pil_img.mode == "RGBA":
                white_bg = Image.new("RGB", pil_img.size, (255, 255, 255))
                white_bg.paste(pil_img, mask=pil_img.split()[3])
                pil_img = white_bg

            # 確保進 JPEG 前是 RGB 或 L
            if pil_img.mode not in ("RGB", "L"):
                pil_img = pil_img.convert("RGB")

            img_byte_arr = io.BytesIO()
            pil_img.save(img_byte_arr, format="JPEG", quality=chosen_quality)
            new_image_bytes = img_byte_arr.getvalue()
            page.replace_image(xref, stream=new_image_bytes)


        # 處理export options，決定要不要刪除大綱、註解、詮釋資料
    if export_options.get("annotation", True):
        for page in doc:
            for annot in page.annots():
                page.delete_annot(annot)

    save_args = {
        "garbage": 4,
        "deflate": True,
        "clean": True,
    }

    try:
        doc.save(output_path, **save_args)
        final_size = os.path.getsize(output_path) / 1024
        print(f"✪ 存檔成功，最終大小: {final_size/1024:.2f} MB，儲存路徑: {output_path}")
    except Exception as e:
        print(f"✖︎ 存檔失敗: {e}")
    finally:
        doc.close()

#主程式
def main():
    global pdf_path, output_path  
    
    show_help()
    if pdf_path is None:
        print("目前還沒有輸入檔案，請先使用指令：input 檔案路徑> 來載入 PDF 檔案。")
        print("範例輸入:   input C:\\Users\\使用者名稱\\Documents\\作業.pdf")
        while pdf_path is None:
            choice = input("\n請輸入路徑指令：").strip()
            if choice.startswith("input"):
                update_path(choice)
            elif choice == "exit":
                exit()
            else:
                print("✖︎ 請先用 input 指令指定檔案路徑")

    # 確認有路徑之後才設定 output_path
    if output_path is None:
        p = Path(pdf_path)
        output_path = str(p.with_name(f"{p.stem}_compressed.pdf").resolve())
        print(f"未指定輸出路徑，預設為: {output_path}")
            
    print(f"\n目前處理的檔案是: {pdf_path}")
    print(f"目前輸出檔案位置: {output_path}") 
    imgs, total_f = analyze_pdf(pdf_path)

    while True:         
        choice = input("\n請輸入指令，若想壓縮第一頁的第一張圖片並設定品質=70%、第二頁的一張圖片的寬度設為1080px，請輸入【1-1:q70, 2-1:w1080】 ").strip()

        if choice == "help":
            show_help()

        elif choice.startswith("set quality:") or choice.startswith("set width:")or choice.startswith("set dpi:"):
            set_config(choice)
            
        elif choice == "analyze":
                imgs, total_f= analyze_pdf(pdf_path)
                
        elif choice == "save":
            savePDF(export_options, current_img_setting)
                        
        elif choice == "exit":
            print("✈︎ 結束程式 ✈︎")
            exit()
            
        elif choice.startswith("del"):
            delete_data(choice)
            
        elif choice.startswith("input") or choice.startswith("output"):
            update_path(choice)
            
        elif ":" in choice:
            saved_kb = dry_run_compression(choice, imgs)
            final_estimate = (total_f - saved_kb) / 1024
            
            print(f"---------------------------------\n✪ 預計壓縮後總檔案大小: {total_f/1024:.2f}MB {'==>'} {final_estimate:.2f}MB")
            
            if final_estimate <= 4.0:
                print("✔︎ 檔案符合教育部 4MB 限制！")
                
            else:
                print("✖︎ 檔案超過 4MB，建議繼續壓縮其他圖片。")
    
        else:
            print(f"✖︎ 無法識別指令: {choice}")

    
if __name__ == "__main__":
    main()
