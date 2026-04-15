# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Phạm Việt Cường  
**Vai trò:** Embed Owner — Chroma collection, idempotency, eval  
**Ngày nộp:** 2026-04-15  
**Độ dài:** ~520 từ

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- `etl_pipeline.py` (Stage 4 — Embed): khối `_embed_cleaned_csv()` để upsert vector vào Chroma theo `chunk_id`.
- `eval_retrieval.py`: chạy bộ câu hỏi retrieval, xuất CSV để so sánh before/after.
- Artifact tôi trực tiếp kiểm tra: `artifacts/manifests/manifest_sprint3-inject-bad.json`, `artifacts/manifests/manifest_sprint3-after-fix.json`, `artifacts/eval/eval_sprint3_before_inject.csv`, `artifacts/eval/eval_sprint3_after_fix.csv`.

**Kết nối với thành viên khác:**

Tôi nhận đầu vào `cleaned_csv` từ Cleaning/Quality Owner. Sau khi embed xong, tôi trả lại evidence eval cho Docs/Report Owner để viết quality report. Tôi cũng phối hợp với Ingestion Owner để đối chiếu `run_id`, `cleaned_records`, `quarantine_records` trong manifest và log.

**Bằng chứng (commit / comment trong code):**

- Log thực chạy có `embed_upsert_count=7`, `embed_collection_total=7`, `embed_prune_removed=1`.
- Hai run_id dùng trong Sprint 3: `sprint3-inject-bad` và `sprint3-after-fix`.

---

## 2. Một quyết định kỹ thuật (100–150 từ)

Quyết định kỹ thuật quan trọng nhất của tôi là dùng chiến lược idempotent gồm **upsert + prune** thay vì chỉ upsert. Cụ thể trong `etl_pipeline.py`, collection Chroma được upsert theo khóa ổn định `chunk_id`, giúp chạy lại pipeline không nhân bản vector cũ. Sau đó tôi so sánh tập `prev_ids` trong collection với `current_ids` của cleaned batch để xóa phần dư (`embed_prune_removed`).  

Lý do chọn cách này: khi làm Sprint 3 inject corruption, nếu không prune thì vector stale có thể còn tồn tại trong top-k, làm retrieval báo tốt giả hoặc fail khó hiểu. Với cơ chế snapshot publish boundary, collection luôn phản ánh đúng cleaned hiện tại của từng run. Đây là yêu cầu cốt lõi để eval before/after có ý nghĩa và tái lập được khi rerun.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

Anomaly tôi gặp là command Sprint 3 bị dừng giữa chừng do lỗi encoding trên Windows terminal khi log ký tự mũi tên (`→`). Triệu chứng xuất hiện ở run inject: pipeline đã đi qua validate nhưng ném `UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'`.  

Tôi phát hiện lỗi này không đến từ logic embedding mà do stdout encoding (`cp1252`) của shell PowerShell. Cách xử lý: set môi trường `PYTHONIOENCODING=utf-8` trước khi chạy lại chuỗi lệnh pipeline/eval. Sau khi fix môi trường, run hoàn tất đầy đủ: inject-bad pipeline OK, eval before sinh file CSV, run chuẩn after-fix pipeline OK và eval after sinh file CSV. Nhờ đó evidence before/after được tạo ổn định, không cần sửa logic nghiệp vụ.

---

## 4. Bằng chứng trước / sau (80–120 từ)

**run_id trước fix (inject bad):** `sprint3-inject-bad`  
Log: `artifacts/logs/run_sprint3-inject-bad.log` có `expectation[refund_no_stale_14d_window] FAIL ... violations=1` và vẫn embed do `--skip-validate`.  
Eval: `artifacts/eval/eval_sprint3_before_inject.csv` dòng `q_refund_window` có `contains_expected=yes` nhưng `hits_forbidden=yes`.

**run_id sau fix:** `sprint3-after-fix`  
Log: `artifacts/logs/run_sprint3-after-fix.log` có `expectation[refund_no_stale_14d_window] OK ... violations=0`.  
Eval: `artifacts/eval/eval_sprint3_after_fix.csv` dòng `q_refund_window` chuyển thành `hits_forbidden=no` (tốt hơn).  
Merit evidence: dòng `q_leave_version` giữ `contains_expected=yes`, `hits_forbidden=no`, `top1_doc_expected=yes`.

---

## 5. Cải tiến tiếp theo (40–80 từ)

Nếu có thêm 2 giờ, tôi sẽ thêm script gộp 2 file eval thành một file duy nhất có cột `scenario` (`before_inject`/`after_fix`) để nhóm nộp và review nhanh hơn. Đồng thời bổ sung kiểm tra tự động trong CI: fail khi `q_refund_window` có `hits_forbidden=yes`, nhằm chặn regression retrieval trước khi merge vào `main`.
