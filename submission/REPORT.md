# Báo cáo Day 09 — Nguyễn Tuấn Dũng, 03345

## 1. Kết luận trước

Pipeline kết luận: **HOLD** (Tỉ lệ ảnh còn cảnh báo 21.67%, tức 44/203 ảnh, vượt ngưỡng Hold 10.00% theo quy định).

* **Dữ liệu vào:** 224 ảnh raw ban đầu $\to$ Cửa vào (Intake) phát hiện và loại bỏ 21 ảnh lỗi nghiêm trọng (2 ảnh hỏng `CORRUPT_IMAGE`, 3 ảnh kích thước nhỏ `BAD_SIZE`, 8 ảnh trùng tuyệt đối `DUP_IMAGE_EXACT`, 3 ảnh gần trùng `DUP_IMAGE_NEAR`, 5 ảnh rò rỉ tập test `LEAK_TEST`) $\to$ Còn 203 ảnh đi vào pipeline.
* **Dữ liệu ra:** 203 ảnh được xuất ra bộ dữ liệu nháp tại `submission/export/clean_v1` (kèm `manifest.json` đầy đủ để truy vết).
* **Lý do chính:** Pipeline đã sửa sạch 100% lỗi bắt buộc (0 ERROR). Tuy nhiên, với ngân sách duyệt người 80 ảnh trong khi hàng đợi có 130 ảnh, vẫn còn 44/203 ảnh chứa cảnh báo nghi vấn (chiếm 21.67% $\ge 10.00\%$). Do đó, dataset ở trạng thái HOLD, chưa được phát hành chính thức cho tới khi có người duyệt bổ sung.

---

## 2. Lỗi và phân việc

Thống kê chi tiết toàn bộ các lỗi từ `02_error_list_v1` (trước khi sửa):

| Mã lỗi | Số lượng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| `BAD_FORMAT` | 3 dòng | Máy | Dòng sai số cột hoặc chứa nan/inf; máy xóa an toàn (`drop_line`) vì không thể parse để train. |
| `BAD_CLASS_ID` | 6 dòng | Máy | ID lớp ngoài phạm vi 0..3 (-1, 4, 7, 93); máy xóa dòng (`drop_line`). |
| `BOX_ZERO` | 4 dòng | Máy | Bounding box có chiều rộng hoặc chiều cao $\le 0$; máy xóa dòng (`drop_line`). |
| `BOX_OUT_OF_IMAGE` | 8 dòng | Máy | Box tràn viền quá sai số cho phép; máy cắt mép về $[0, 1]$ (`clip_box`), nếu nằm hẳn ngoài biên thì `drop_line`. |
| `DUP_BOX` | 7 dòng | Máy | Box cùng lớp trùng với box trước trong cùng ảnh ($IoU > 0.9$); máy xóa box sau (`drop_line`) để tránh thổi phồng trọng số. |
| `DUP_IMAGE_EXACT` | 8 ảnh | Máy | Trùng từng byte với ảnh đã có trong lô; máy xóa ảnh và nhãn (`remove_image`). |
| `DUP_IMAGE_NEAR` | 3 ảnh | Máy | Trùng gần đúng theo pHash ($\le 8$); máy xóa ảnh và nhãn (`remove_image`). |
| `LEAK_TEST` | 5 ảnh | Máy | Trùng lặp với kho dữ liệu test/gold_val; máy xóa (`remove_image`) để tránh data leakage. |
| `CORRUPT_IMAGE` | 2 ảnh | Máy | File ảnh lỗi không đọc được (`UnidentifiedImageError`, `OSError`); máy xóa (`remove_image`). |
| `BAD_SIZE` | 3 ảnh | Máy | Cạnh ngắn $< 250px$, không đạt tiêu chuẩn độ phân giải tối thiểu; máy xóa (`remove_image`). |
| `BAD_CLASS_NAME` | 2 lỗi | Máy | Tên lớp trong `data.yaml` sai chuẩn ('Person', 'Bus'); máy ghi lại chuẩn theo config (`rename_classes`). |
| `MISSING_LABEL_FILE` | 6 ảnh | Người | Ảnh thiếu file nhãn hoàn toàn; máy không thể tự bịa nhãn, ghi nhận `needs_label` và ưu tiên hàng đầu cho người gán. |
| `BOX_TINY` | 6 dòng | Người | Cạnh ngắn box $< 12px$; máy chỉ cảnh báo WARN, người cần xem để phân biệt vật thể xa hay nhiễu. |
| `BOX_HUGE` | 3 dòng | Người | Box chiếm $> 95\%$ ảnh; máy cảnh báo WARN để người kiểm tra xem có gán nhầm toàn bộ khung nền không. |
| `EMPTY_LABEL` | 12 ảnh | Người | File nhãn rỗng; người cần xem là ảnh không chứa đối tượng (ảnh nền) hay người gán bỏ quên. |
| `POSSIBLE_MISSING` | 68 cảnh báo | Người | Model lớn phát hiện vật thể độ tin cậy cao nhưng nhãn thiếu; người kiểm tra để thêm box. |
| `POSSIBLE_WRONG_CLASS` | 18 cảnh báo | Người | Model và nhãn lệch lớp khi IoU cao; người duyệt lại ngữ nghĩa xem đối tượng là gì (xe con hay xe tải, xe bus...). |
| `POSSIBLE_LOOSE_BOX` | 31 cảnh báo | Người | Box nhãn và dự đoán cùng lớp nhưng $IoU < 0.5$; người chỉnh sửa lại biên viền cho khít. |
| `POSSIBLE_FALSE_POS` | 29 cảnh báo | Người | Box nhãn không khớp với bất kỳ dự đoán nào của model lớn; người kiểm tra xem có gán nhầm vật lạ. |
| `CLASS_RARE` | 4 cảnh báo | Người | Cảnh báo cấp dataset (lớp lạ có ít box); sau khi máy xóa các box sai class ID thì lỗi này tự hết. |

**Phân tích hàng đợi duyệt `05_review_queue.csv`:**
* Hàng đợi có tổng cộng 130 ảnh có cảnh báo hoặc đã qua autofix.
* Các ảnh xếp đầu hàng là những ảnh có trọng số tích lũy lớn nhất: `img_0020` (priority 14.528), `img_0185` (10.052) do kết hợp vừa bị xóa dòng lỗi vừa có nghi ngờ thiếu nhãn và sai lớp.
* Ngay sau đó là 6 ảnh bị `MISSING_LABEL_FILE` (`img_0031`, `img_0053`, `img_0126`, `img_0135`, `img_0170`, `img_0219`, priority 10.0) vì đây là các lỗi bắt buộc, máy tuyệt đối không bịa nhãn nên phải đẩy lên đầu để người gán nhãn giải cứu lô ảnh.
* Tiếp theo là các ảnh có lỗi ngữ nghĩa nghiêm trọng (`POSSIBLE_WRONG_CLASS`, `POSSIBLE_MISSING` với conf cao).
* Với ngân sách 80 ảnh, người duyệt mô phỏng đã xem và sửa hết 80 ảnh nguy cơ cao nhất (gồm toàn bộ 6 ảnh thiếu nhãn và hàng chục ca thiếu/nhầm nhãn). Tuy nhiên còn 50 ảnh trong hàng đợi chưa kịp xem, để lại 44 ảnh còn cảnh báo.

---

## 3. Calibration (2 ngưỡng)

| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | 8 | P: 1.00 $\to$ 1.00, R: 0.50 $\to$ 0.67 (NEAR) | Tại ngưỡng 2, Recall chỉ đạt 0.50 (bỏ sót 3/6 ảnh gần trùng). Nâng lên 8 giúp tăng Recall lên 0.67 trong khi giữ nguyên Precision 1.00 tuyệt đối, loại bỏ an toàn các ảnh trùng lặp mà không xóa nhầm ảnh tốt. |
| `second_opinion.conf` | 0.25 | 0.50 | P: 0.50 $\to$ 0.57, R: 1.00 $\to$ 1.00 (MISSING) | Giữ vững 100% Recall cho lỗi thiếu nhãn (`POSSIBLE_MISSING`), đồng thời tăng Precision từ 0.50 lên 0.57, giảm thiểu báo động giả và giảm tải áp lực cho người duyệt. |

**Điểm calibration có thể đánh lừa:**
* Nếu chỉ tối ưu F1 trên tập calibration (39 ảnh) một cách mù quáng, ta sẽ bị cuốn vào việc chọn `duplicates.phash_dist = 16` vì trên tập calib nó cho F1 cao nhất (0.91) và Recall cao nhất (0.83).
* Tuy nhiên, trên tập dữ liệu thật (`raw` 224 ảnh):
  * Tại `phash_dist = 8`: hệ thống bắt 16 ảnh trùng (5 leak, 8 exact, 3 near) — đúng với thực tế các cặp ảnh tương tự.
  * Khi thử nghiệm với `phash_dist = 16`: số lượng ảnh bị coi là trùng tăng vọt lên **26 ảnh** (11 leak, 8 exact, 7 near). Khi mở xem xét thủ công bằng `viz_labels.py`, các cặp ảnh ở khoảng cách pHash từ 10–16 thực chất là các cảnh đường phố khác nhau (góc chụp khác, loại xe khác) nhưng do nền tương tự nên pHash gần nhau. Chọn 16 sẽ khiến pipeline xóa oan 10 ảnh hợp lệ. 
* *Bài học:* Tập calib quá nhỏ (chỉ 39 ảnh) có phân bố khác với tập raw, không thể tin hoàn toàn vào F1 trên calib mà phải đối chiếu thực tế trên dữ liệu thật.

---

## 4. Cửa chặn và điều pipeline KHÔNG bắt được

**(a) Chứng minh Gate hoạt động chuẩn:**
* Thực hiện chạy thử nghiệm ngắt toàn bộ ngân sách người duyệt:
  `python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb`
* Kết quả: Do không có người duyệt (`budget = 0`), 6 ảnh thiếu nhãn (`MISSING_LABEL_FILE`) không được ai gán nhãn.
* Cửa chặn Gate phát hiện còn 6 lỗi bắt buộc và ra kết luận: `REWORK — Còn 6 lỗi bắt buộc (ERROR) chưa được giải quyết`, trả về mã thoát `ExitCode = 20`.
* Thư mục `work/exp_nb` hoàn toàn không được tạo ra (`Test-Path work\exp_nb` trả về `False`). Điều này chứng minh cửa chặn hoạt động độc lập và thực thi nghiêm ngặt: khi còn lỗi bắt buộc, dữ liệu tuyệt đối không bị lọt ra môi trường sản xuất.

**(b) Các điểm mù đã biết của pipeline:**
1. *Box lỏng nhẹ hoặc lệch góc nhỏ ($IoU \ge 0.5$):* Do quy định `iou_loose = 0.5`, các box nhãn vẽ ẩu hoặc lệch nhẹ so với vật thể thật nhưng vẫn đạt IoU $\ge 0.5$ với model lớn thì pipeline coi như đã bao phủ và bỏ qua, không thể cảnh báo.
2. *Lỗi nhầm lẫn giữa các lớp tương đồng mà cả model lớn cũng nhầm:* Ví dụ nhầm giữa `truck` và `bus` hoặc các loại xe bán tải. Nếu cả người gán nhãn và model `yolo26l` cùng nhận định sai, `second_opinion` sẽ thấy đồng thuận và bỏ lọt lỗi.
3. *Ảnh trùng lặp bị biến đổi mạnh:* Nếu ảnh bị cắt cúp mạnh ($>50\%$), đổi góc phối cảnh hoặc xử lý màu phức tạp khiến khoảng cách pHash vượt quá 8, pipeline sẽ không phát hiện được và vẫn để lọt ảnh trùng.

---

## 5. Train: raw vs clean (tùy chọn, chấm riêng)

Chưa chạy (Bài nộp tập trung hoàn thiện pipeline, calibration và các báo cáo tự động hoá cốt lõi; không sử dụng GPU huấn luyện mô hình).

---

## 6. Quyết định và ghi chú AI

**(a) Quyết định cuối cùng:** **HOLD** (Tạm giữ lô dữ liệu).
* *Biện pháp để Release:* Cần mở rộng ngân sách duyệt của chuyên viên kiểm định (tăng ngân sách từ 80 lên 130 ảnh) để duyệt nốt 44 ảnh còn cảnh báo trong `07_error_list_v3`. Sau khi người duyệt xác nhận/sửa xong, tỉ lệ cảnh báo sẽ giảm về $< 10\%$, pipeline sẽ tự động chuyển trạng thái thành **Release**.

**(b) Ghi chú sử dụng AI:**
* *Prompt chính:* Yêu cầu AI áp dụng quy trình TDD, đọc kỹ các ràng buộc trong docstring và test suite để xây dựng 4 module (`label_format`, `gate`, `autofix`, `second_opinion`), chú ý bảo toàn tính bất biến (idempotent), không ghi đè dữ liệu gốc và xử lý các ca biên hình học box.
* *Cách kiểm code AI:* Chạy kiểm thử tự động toàn diện qua `pytest -q` (đạt 79/79 passed), chạy `scripts/check_submission.py --no-train` để đối chiếu từng quy tắc trong rubric và mở xem trực quan file log báo cáo.
* *Một lần AI sai:* Khi kiểm tra tính hợp lệ bằng `check_submission.py`, do hệ điều hành Windows phân tách thư mục bằng dấu gạch chéo ngược (`\`), đường dẫn so sánh bị lệch dẫn tới hiểu nhầm file mã nguồn hệ thống bị vi phạm quy tắc cấm; đã sửa bằng phương thức `.as_posix()` để tương thích đa nền tảng.
