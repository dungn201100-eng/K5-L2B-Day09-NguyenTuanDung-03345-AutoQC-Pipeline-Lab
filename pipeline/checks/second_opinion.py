"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")
    if preds is None:
        preds = {}

    so_cfg = cfg.get("second_opinion", {})
    conf_thresh = so_cfg.get("conf", 0.25)
    min_area_px = so_cfg.get("min_area_px", 600)
    fp_conf = so_cfg.get("fp_conf", 0.1)
    iou_missing = so_cfg.get("iou_missing", 0.3)
    iou_match = so_cfg.get("iou_match", 0.5)
    iou_loose = so_cfg.get("iou_loose", 0.5)

    issues = []

    for img_path in ds.image_files():
        stem = img_path.stem

        # Bỏ qua ảnh không có trong preds hoặc không có file nhãn
        if stem not in preds:
            continue
        raw_lines = ds.read_label_lines(stem)
        if raw_lines is None:
            continue

        raw_preds = preds.get(stem, [])

        im_size = ds.image_size(stem)
        if im_size:
            w_px, h_px = im_size
        else:
            w_px, h_px = 1, 1

        # Lọc danh sách dự đoán P
        filtered_preds = []
        for p in raw_preds:
            p_cls, p_conf, p_cx, p_cy, p_w, p_h = p
            area_px = (p_w * w_px) * (p_h * h_px)
            if p_conf >= conf_thresh and area_px >= min_area_px:
                filtered_preds.append(p)

        # Đọc các dòng nhãn hợp lệ (giữ số dòng gốc)
        valid_label_lines = []
        for line_num, text in raw_lines:
            try:
                c, cx, cy, w, h = parse_yolo_line(text)
                if 0 <= c < len(ds.classes):
                    valid_label_lines.append((line_num, c, (cx, cy, w, h)))
            except ValueError:
                continue

        # 1. Đánh giá từng dự đoán trong filtered_preds
        for p in filtered_preds:
            p_cls, p_conf, p_cx, p_cy, p_w, p_h = p
            p_box = (p_cx, p_cy, p_w, p_h)

            cands = []
            for _, l_cls, l_box in valid_label_lines:
                iou = iou_xywh(p_box, l_box)
                if iou >= iou_missing:
                    cands.append((l_cls, l_box, iou))

            if not cands:
                issues.append(Issue(
                    "second_opinion", WARN, "POSSIBLE_MISSING", stem,
                    f"model dự đoán {ds.classes[p_cls]} (conf={p_conf:.2f}) nhưng nhãn thiếu",
                    extra={"conf": p_conf}
                ))
            else:
                same_class_cands = [c for c in cands if c[0] == p_cls]
                if same_class_cands:
                    best_same_iou = max(c[2] for c in same_class_cands)
                    if best_same_iou < iou_loose:
                        issues.append(Issue(
                            "second_opinion", WARN, "POSSIBLE_LOOSE_BOX", stem,
                            f"box nhãn lỏng/lệch so với model (IoU={best_same_iou:.2f} < {iou_loose})",
                            extra={"conf": p_conf, "iou": best_same_iou}
                        ))
                else:
                    best_diff_iou = max(c[2] for c in cands)
                    if best_diff_iou >= iou_match:
                        issues.append(Issue(
                            "second_opinion", WARN, "POSSIBLE_WRONG_CLASS", stem,
                            f"model dự đoán {ds.classes[p_cls]} (conf={p_conf:.2f}), nhãn gán lớp khác (IoU={best_diff_iou:.2f})",
                            extra={"conf": p_conf, "iou": best_diff_iou}
                        ))

        # 2. Đánh giá POSSIBLE_FALSE_POS cho các dòng nhãn
        fp_preds = [p for p in raw_preds if p[1] >= fp_conf]
        for line_num, l_cls, l_box in valid_label_lines:
            has_matching_pred = False
            for p in fp_preds:
                p_box = (p[2], p[3], p[4], p[5])
                if iou_xywh(l_box, p_box) >= iou_missing:
                    has_matching_pred = True
                    break
            if not has_matching_pred:
                issues.append(Issue(
                    "second_opinion", WARN, "POSSIBLE_FALSE_POS", stem,
                    f"dòng {line_num}: box nhãn không khớp dự đoán nào của model (conf >= {fp_conf})",
                    line=line_num
                ))

    return issues
