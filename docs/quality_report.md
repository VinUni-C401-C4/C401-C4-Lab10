# Quality report — Lab Day 10 (nhóm)

**run_id:** sprint3-inject-bad (before), sprint3-after-fix (after)  
**Ngày:** 2026-04-15

---

## 1. Tóm tắt số liệu

| Chỉ số | Trước | Sau | Ghi chú |
|--------|-------|-----|---------|
| raw_records | 13 | 13 | Cùng một file raw `data/raw/policy_export_dirty.csv` |
| cleaned_records | 7 | 7 | Không đổi số dòng cleaned |
| quarantine_records | 6 | 6 | Không đổi số dòng quarantine |
| Expectation halt? | Có (refund stale 14d) nhưng bypass do `--skip-validate` | Không | Trước: `refund_no_stale_14d_window` FAIL, Sau: OK |

---

## 2. Before / after retrieval (bắt buộc)

**File chứng cứ eval (2 file):**

- `artifacts/eval/eval_sprint3_before_inject.csv`
- `artifacts/eval/eval_sprint3_after_fix.csv`

**Câu hỏi then chốt:** refund window (`q_refund_window`)

**Trước (inject bad: `--no-refund-fix --skip-validate`):**

- `contains_expected=yes`
- `hits_forbidden=yes`  ← retrieval còn dính chunk cũ 14 ngày trong top-k (chất lượng tệ)
- `top1_doc_id=policy_refund_v4`

**Sau (fix lại pipeline chuẩn):**

- `contains_expected=yes`
- `hits_forbidden=no`  ← không còn chunk cũ 14 ngày trong top-k (chất lượng tốt hơn)
- `top1_doc_id=policy_refund_v4`

**Diễn giải ngắn:**

Ở kịch bản inject, hệ thống vẫn retrieve được policy refund đúng ở top-1, nhưng ngữ cảnh top-k chứa cả nội dung cấm (14 ngày), nên rủi ro agent trả lời sai vẫn cao. Sau khi bật lại refund fix và validate bình thường, `hits_forbidden` chuyển từ `yes` xuống `no`, chứng minh retrieval đã sạch hơn theo tiêu chí quality.

**Merit (khuyến nghị):** versioning HR — `q_leave_version` (`contains_expected`, `hits_forbidden`, `top1_doc_expected`)

**Trước:**

- `question_id=q_leave_version`
- `contains_expected=yes`
- `hits_forbidden=no`
- `top1_doc_expected=yes`

**Sau:**

- `question_id=q_leave_version`
- `contains_expected=yes`
- `hits_forbidden=no`
- `top1_doc_expected=yes`

---

## 3. Freshness & monitor

`freshness_check` ở cả 2 run đều là **FAIL** với cùng lý do:

- `latest_exported_at=2026-04-10T08:00:00`
- `sla_hours=24.0`
- age khoảng 120 giờ, vượt SLA

Đây là expected behavior với snapshot data cũ trong lab. Không phải lỗi pipeline code; cần cập nhật timestamp nguồn hoặc nới SLA nếu muốn PASS/WARN trong môi trường demo.

---

## 4. Corruption inject (Sprint 3)

**Cách cố ý làm hỏng dữ liệu:**

- Chạy: `python etl_pipeline.py run --run-id sprint3-inject-bad --no-refund-fix --skip-validate`
- Ý nghĩa:
  - `--no-refund-fix`: không sửa policy refund stale 14 ngày -> 7 ngày
  - `--skip-validate`: dù expectation halt FAIL vẫn tiếp tục embed vào vector DB

**Đoạn log chứng minh inject thành công:**

- `artifacts/logs/run_sprint3-inject-bad.log` có:
  - `apply_refund_window_fix=False`
  - `expectation[refund_no_stale_14d_window] FAIL severity=halt :: violations=1`
  - `WARN: expectation failed but --skip-validate is set → continuing embed`

**Đoạn log chứng minh fix thành công:**

- `artifacts/logs/run_sprint3-after-fix.log` có:
  - `apply_refund_window_fix=True`
  - `expectation[refund_no_stale_14d_window] OK severity=halt :: violations=0`

---

## 5. Hạn chế & việc chưa làm

- Chưa chạy được `grading_run.py` cho `gq_d10_03` vì thiếu file `data/grading_questions.json` trong repo hiện tại.
- Mới chứng minh Merit bằng dòng `q_leave_version` trong file eval retrieval (không phải JSONL grading).
- Chưa đính kèm ảnh screenshot; hiện report dùng log text path làm chứng cứ.
