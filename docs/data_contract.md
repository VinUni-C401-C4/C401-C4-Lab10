# Data Contract — Lab Day 10: KB Chunk Export Pipeline

> **Owner:** Ingestion Owner (Sprint 1)  
> **Đồng bộ với:** `contracts/data_contract.yaml`  
> **Cập nhật:** 2026-04-15

---

## 1. Nguồn dữ liệu (Source Map)

| # | Nguồn | Phương thức ingest | Failure mode chính | Metric / Alert |
|---|-------|-------------------|-------------------|----------------|
| 1 | **policy_export_dirty.csv** — Export thủ công từ hệ thống policy management nội bộ | Load CSV qua `transform/cleaning_rules.py::load_raw_csv()` | Duplicate chunk_text từ lần export trước chưa dedupe; ngày hiệu lực sai định dạng (dd/MM/yyyy thay vì ISO); doc_id legacy không có trong allowlist | `raw_records` vs `cleaned_records` (delta = quarantine); `quarantine_reason[duplicate_chunk_text]` |
| 2 | **data/docs/*.txt** — Tài liệu canonical (policy text gốc, Day 09) | Đọc trực tiếp bởi Day 09 RAG pipeline; không re-ingest trong pipeline này | File bị xóa hoặc rename gây mismatch với `doc_id` trong allowlist | Xác minh file tồn tại mỗi lần cập nhật `ALLOWED_DOC_IDS` trong `cleaning_rules.py` |
| 3 | **API / DB export tương lai** (ngoài phạm vi lab) | Dự kiến: REST API → stream sang `data/raw/` | Timeout, schema drift, mất kết nối | `raw_records=0` → alert; SLA freshness vượt 24 giờ → `freshness_check=FAIL` |

### Failure modes đã biết trong bộ mẫu

| Failure | Dòng trong dirty CSV | Xử lý |
|---------|---------------------|--------|
| Duplicate chunk_text | Rows 2–3 (policy_refund_v4, cùng nội dung) | Quarantine bản thứ 2 (`duplicate_chunk_text`) |
| Stale refund window (14 ngày → đúng là 7 ngày) | Row 4 | Fix text + gắn marker `[cleaned: stale_refund_window]`; nếu `--no-refund-fix` → giữ nguyên, expectation FAIL |
| Thiếu chunk_text (rỗng) | Row 5 | Quarantine (`missing_chunk_text`) |
| HR policy version cũ (effective_date 2025-01-01) | Row 7 | Quarantine (`stale_hr_policy_effective_date`) |
| doc_id không nằm trong allowlist | Row 9 (`legacy_catalog_xyz_zzz`) | Quarantine (`unknown_doc_id`) |
| Ngày định dạng DD/MM/YYYY | Row 10 (it_helpdesk_faq) | Chuẩn hoá → `2026-02-01` |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `chunk_id` | string | ✅ | ID ổn định, sinh từ `sha256(doc_id \| chunk_text \| seq)[:16]` — idempotent qua các lần run |
| `doc_id` | string | ✅ | Khóa logic tài liệu nguồn; phải thuộc `ALLOWED_DOC_IDS` trong `cleaning_rules.py` |
| `chunk_text` | string | ✅ | Nội dung đã cleaned; tối thiểu 8 ký tự (expectation `chunk_min_length_8`) |
| `effective_date` | date (YYYY-MM-DD) | ✅ | Ngày hiệu lực tài liệu, đã chuẩn hoá sang ISO 8601 |
| `exported_at` | datetime (ISO 8601) | ✅ | Timestamp export từ hệ nguồn; dùng để tính freshness SLA |

---

## 3. Quy tắc quarantine vs drop

### Được ghi vào `artifacts/quarantine/quarantine_<run_id>.csv`

| Lý do (`reason`) | Quyết định | Ai approve merge lại |
|-----------------|------------|---------------------|
| `unknown_doc_id` | Quarantine — không embed | Ingestion Owner xác minh với catalog owner |
| `missing_effective_date` | Quarantine — dữ liệu không hoàn chỉnh | Data source team cập nhật export |
| `invalid_effective_date_format` | Quarantine — parser không nhận | Kiểm tra thêm format; thêm rule trong `_normalize_effective_date()` |
| `stale_hr_policy_effective_date` | Quarantine — conflict version HR | HR team confirm phiên bản hiện hành |
| `missing_chunk_text` | Quarantine — chunk rỗng | Xem xét xóa record khỏi nguồn |
| `duplicate_chunk_text` | Quarantine bản thứ 2 | Không cần merge, bản đầu đã trong cleaned |

### Chính sách re-ingest

- Record quarantine **không tự động** được merge lại vào cleaned.  
- Cần chỉnh sửa dữ liệu nguồn hoặc cập nhật rule, sau đó chạy lại pipeline với `run_id` mới.  
- Quarantine CSV được giữ nguyên (append-only trên filesystem) — không xóa artifact cũ.

---

## 4. Phiên bản & Canonical

| Tài liệu | Canonical source | Phiên bản hiện tại | Ghi chú |
|----------|-----------------|---------------------|---------|
| Policy hoàn tiền | `data/docs/policy_refund_v4.txt` | v4 (7 ngày làm việc) | Bất kỳ chunk nào chứa "14 ngày làm việc" đều là stale (bản v3 cũ) |
| SLA P1 | `data/docs/sla_p1_2026.txt` | 2026-02-01 | SLA phản hồi 15 phút, resolution 4 giờ |
| IT Helpdesk FAQ | `data/docs/it_helpdesk_faq.txt` | 2026-02-01 | Lock 5 lần sai; đổi mật khẩu 24 giờ đồng bộ |
| HR Leave Policy | `data/docs/hr_leave_policy.txt` | 2026-02-01 (12 ngày phép) | Bản 2025 (10 ngày) bị quarantine; cutoff: `2026-01-01` |

### Cutoff versioning (tránh hard-code)

Cutoff để loại bỏ HR policy cũ được đọc từ `contracts/data_contract.yaml`:

```yaml
policy_versioning:
  hr_leave_min_effective_date: "2026-01-01"
```

> Bước tiếp theo (Distinction): đọc giá trị này qua env/contract thay vì hard-code trong `cleaning_rules.py`.

---

## 5. Freshness SLA

| Boundary | Đo tại | SLA | Alert |
|----------|--------|-----|-------|
| **Ingest** | `exported_at` trong raw CSV (timestamp hệ nguồn) | 24 giờ | `freshness_check=FAIL` trong log |
| **Publish** | `run_timestamp` trong manifest | 24 giờ | Chạy `python etl_pipeline.py freshness --manifest <path>` |

Cấu hình qua env: `FRESHNESS_SLA_HOURS=24` (xem `.env.example`).

> **Lưu ý về bộ mẫu:** `exported_at=2026-04-10T08:00:00` trong CSV mẫu — freshness sẽ `FAIL` nếu chạy sau ngày 11/04/2026. Đây là hành vi đúng; ghi rõ trong runbook.
