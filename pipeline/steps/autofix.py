"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict

import yaml

from ..common import ERROR, parse_yolo_line

REMOVE_IMAGE_CODES = {
    "DUP_IMAGE_EXACT", "DUP_IMAGE_PHASH", "LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"
}
DROP_LINE_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}


def fix(ds, issues, cfg):
    err_issues = [i for i in issues if i.severity == ERROR]
    fixes = []

    # 1. remove_image
    removed_stems = set()
    for i in err_issues:
        if i.code in REMOVE_IMAGE_CODES or i.code.startswith("DUP_IMAGE_"):
            stem = i.image
            if stem not in removed_stems:
                removed_stems.add(stem)
                img_path = ds.image_path(stem)
                if img_path and img_path.exists():
                    img_path.unlink()
                lbl_path = ds.label_path(stem)
                if lbl_path.exists():
                    lbl_path.unlink()
                fixes.append({
                    "image": stem,
                    "line": "",
                    "action": "remove_image",
                    "before": f"lỗi {i.code}",
                    "after": "(đã xoá)",
                })

    # 2. rename_classes
    has_bad_class_name = any(i.code == "BAD_CLASS_NAME" for i in err_issues)
    if has_bad_class_name and ds.yaml_path.exists():
        raw_yaml = ds.yaml_path.read_text(encoding="utf-8")
        ydata = yaml.safe_load(raw_yaml) or {}
        before_names = ydata.get("names", {})
        ydata["names"] = list(cfg.get("classes", []))
        ds.yaml_path.write_text(yaml.safe_dump(ydata, allow_unicode=True, sort_keys=False), encoding="utf-8")
        fixes.append({
            "image": "data.yaml",
            "line": "",
            "action": "rename_classes",
            "before": str(before_names),
            "after": str(cfg.get("classes", [])),
        })

    # 3. needs_label
    missing_stems = set()
    for i in err_issues:
        if i.code == "MISSING_LABEL_FILE":
            stem = i.image
            if stem not in removed_stems and stem not in missing_stems:
                missing_stems.add(stem)
                fixes.append({
                    "image": stem,
                    "line": "",
                    "action": "needs_label",
                    "before": "(không có file)",
                    "after": "chuyển người gán",
                })

    # 4. Chỉnh sửa file nhãn
    line_issues_by_stem = defaultdict(list)
    for i in err_issues:
        if i.image in removed_stems:
            continue
        if i.line is not None and (i.code in DROP_LINE_CODES or i.code == "BOX_OUT_OF_IMAGE"):
            line_issues_by_stem[i.image].append(i)

    for stem, st_issues in line_issues_by_stem.items():
        lbl_path = ds.label_path(stem)
        if not lbl_path.exists():
            continue
        raw_lines = lbl_path.read_text(encoding="utf-8", errors="replace").splitlines()

        by_line = defaultdict(list)
        for iss in st_issues:
            by_line[iss.line].append(iss)

        new_lines = []
        file_fixes = []

        for idx, line_text in enumerate(raw_lines, 1):
            if idx not in by_line:
                if line_text.strip():
                    new_lines.append(line_text)
                continue

            cur_issues = by_line[idx]
            codes = {iss.code for iss in cur_issues}

            # Xóa dòng nếu có lỗi drop_line
            if codes & DROP_LINE_CODES:
                file_fixes.append({
                    "image": stem,
                    "line": idx,
                    "action": "drop_line",
                    "before": line_text,
                    "after": "",
                })
                continue

            # Cắt box nếu có lỗi BOX_OUT_OF_IMAGE
            if "BOX_OUT_OF_IMAGE" in codes:
                try:
                    c, cx, cy, w, h = parse_yolo_line(line_text)
                    x1 = cx - w / 2.0
                    y1 = cy - h / 2.0
                    x2 = cx + w / 2.0
                    y2 = cy + h / 2.0
                    cx1 = max(0.0, x1)
                    cy1 = max(0.0, y1)
                    cx2 = min(1.0, x2)
                    cy2 = min(1.0, y2)
                    new_w = cx2 - cx1
                    new_h = cy2 - cy1
                    if new_w <= 0.0 or new_h <= 0.0:
                        file_fixes.append({
                            "image": stem,
                            "line": idx,
                            "action": "drop_line",
                            "before": line_text,
                            "after": "",
                        })
                    else:
                        new_cx = (cx1 + cx2) / 2.0
                        new_cy = (cy1 + cy2) / 2.0
                        clipped_str = f"{c} {round(new_cx, 6):.6g} {round(new_cy, 6):.6g} {round(new_w, 6):.6g} {round(new_h, 6):.6g}"
                        new_lines.append(clipped_str)
                        file_fixes.append({
                            "image": stem,
                            "line": idx,
                            "action": "clip_box",
                            "before": line_text,
                            "after": clipped_str,
                        })
                except Exception:
                    file_fixes.append({
                        "image": stem,
                        "line": idx,
                        "action": "drop_line",
                        "before": line_text,
                        "after": "",
                    })

        lbl_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
        fixes.extend(file_fixes)

    return fixes
