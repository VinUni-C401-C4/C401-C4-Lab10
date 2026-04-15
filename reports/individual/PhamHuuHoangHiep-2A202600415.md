# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Phạm Hữu Hoàng Hiệp - 2A202600415
**Vai trò:** **Ingestion Owner** — Sprint 1  
**run_id tham chiếu:** `sprint1`  
**Ngày nộp:** 2026-04-15

---

> Tất cả số liệu trích từ `artifacts/logs/run_sprint1.log` và `artifacts/manifests/manifest_sprint1.json`.

---

## 1. Tôi phụ trách phần nào?

**File / module chính:**

- `etl_pipeline.py` — toàn bộ entry point: thiết lập raw path, `PipelineLogger`, gọi các stage, ghi manifest.
- `docs/data_contract.md` — điền source map ≥ 2 nguồn, schema, quarantine policy, freshness SLA.
- `contracts/data_contract.yaml` — điền `owner_team`, `contact`, `freshness.sla_hours`, `canonical_sources`, `policy_versioning`.

**Kết nối với thành viên khác:**

- Output của Stage 1 → 2 (`raw_records`, `cleaned_records`) là **đầu vào** của Cleaning/Quality Owner (Sprint 1–3).
- `cleaned_csv` trong manifest là **đầu vào** của Embed Owner (Sprint 2–3).
- `manifest_<run_id>.json` là **đầu vào** của Monitoring/Docs Owner khi chạy `freshness` sub-command (Sprint 4).

**Bằng chứng:**

- Commit `etl_pipeline.py` (refactored: thêm `PipelineLogger`, `_ensure_dirs`, `_safe_run_id`, `quarantine_reasons`, rich CLI help).
- `manifest_sprint1.json` tồn tại tại `artifacts/manifests/` với đủ 4 trường bắt buộc.

---

## 2. Một quyết định kỹ thuật

**Quyết định: thiết kế log key=value và `quarantine_reasons` breakdown trong manifest.**

Baseline chỉ log 4 trường cơ bản. Tôi quyết định thêm breakdown lý do quarantine theo từng `reason` vào cả log và manifest:

```
quarantine_reason[duplicate_chunk_text]=1
quarantine_reason[missing_effective_date]=1
quarantine_reason[stale_hr_policy_effective_date]=1
quarantine_reason[unknown_doc_id]=1
```

Lý do: khi `quarantine_records` tăng đột biến, operator cần biết *vì sao* (schema drift? version conflict? duplicate?) mà không cần mở file CSV. Format `key[subkey]=value` dễ grep và dễ parse bằng script (regex `quarantine_reason\[(\w+)\]=(\d+)`). Đây là quyết định quan sát được về **observability boundary** — nguyên tắc cốt lõi của bài lab.

---

## 3. Một lỗi / anomaly đã xử lý

**Anomaly: `freshness_check=FAIL` mặc dù pipeline chạy thành công.**

Triệu chứng: `PIPELINE_OK` nhưng exit code = 1 (do freshness FAIL):

```
freshness_check=FAIL {"latest_exported_at": "2026-04-10T08:00:00",
  "age_hours": 116.806, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
```

Phát hiện: Trường `latest_exported_at` trong manifest lấy từ `exported_at` của CSV mẫu là `2026-04-10T08:00:00` — gần 5 ngày trước thời điểm chạy (2026-04-15). SLA 24 giờ bị vượt.

Fix: Đây là hành vi **đúng** — pipeline nên cảnh báo dữ liệu cũ. Tôi ghi rõ trong `docs/data_contract.md` mục Freshness SLA: *"CSV mẫu có exported_at cũ — freshness sẽ FAIL khi chạy sau ngày 11/04/2026. Hành vi đúng; ghi trong runbook."* Ngoài ra, `etl_pipeline.py` vẫn exit 0 (PIPELINE_OK) — freshness FAIL chỉ là warning metric, không dừng pipeline (đúng với SLA policy của lab).

---

## 4. Bằng chứng trước / sau

**Trích log `run_sprint1.log` — trước và sau clean (run_id=sprint1):**

```
# TRƯỚC CLEAN (ingest):
raw_records=10

# SAU CLEAN:
cleaned_records=6
quarantine_records=4
quarantine_reason[duplicate_chunk_text]=1
quarantine_reason[missing_effective_date]=1
quarantine_reason[stale_hr_policy_effective_date]=1
quarantine_reason[unknown_doc_id]=1
```

**Trích manifest `manifest_sprint1.json`:**

```json
"raw_records": 10,
"cleaned_records": 6,
"quarantine_records": 4
```

10 raw → 6 cleaned: pipeline loại bỏ 40% record bẩn (4/10), đảm bảo chỉ embed dữ liệu hợp lệ. Embed xác nhận: `embed_upsert_count=6`, `embed_collection_total=6`.

---

## 5. Cải tiến tiếp theo

Nếu có thêm 2 giờ, tôi sẽ đọc `policy_versioning.hr_leave_min_effective_date` trực tiếp từ `contracts/data_contract.yaml` bằng `PyYAML` thay vì hard-code chuỗi `"2026-01-01"` trong `cleaning_rules.py`. Điều này đáp ứng tiêu chí **Distinction (d)** trong SCORING — rule versioning không hard-code, dễ cập nhật khi cutoff thay đổi mà không cần sửa code. Đây cũng là pattern production-ready: configuration as code, tránh "magic string" rải rác trong codebase.
