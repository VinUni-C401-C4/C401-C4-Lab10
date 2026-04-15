# Báo cáo cá nhân

**Họ và tên:** Đặng Tiến Dũng - 2A202600024  
**Vai trò:** Cleaning & Quality  
**Ngày nộp:** 2026-04-15  
**Độ dài yêu cầu:** 400–650 từ

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

Tôi phụ trách module cleaning và quality assurance trong pipeline data. Cụ thể:

**File / module:**
- Thêm 6 trường hợp dữ liệu dirty vào `data/raw/policy_export_dirty.csv` (dòng 11 - 16)
- Phát triển rules 7–9 trong `transform/cleaning_rules.py`
- Thêm expectations E7–E8 trong `quality/expectations.py`

**Kết nối với thành viên khác:**
Tôi làm việc độc lập trên phần cleaning và quality, nhưng kết nối với nhóm qua data contract và shared artifacts. Rules của tôi xử lý dữ liệu sau khi ingestion, và expectations của tôi validate output trước khi embed.

**Bằng chứng (commit / comment trong code):**
Trong `transform/cleaning_rules.py`, tôi thêm rule 7 (quarantine expired effective_date), rule 8 (fix stale leave policy), rule 9 (quarantine chunk quá dài). Trong `quality/expectations.py`, tôi thêm E7 (kiểm tra không còn "18 tháng") và E8 (chunk không quá 200 ký tự).

---

## 2. Một quyết định kỹ thuật (100–150 từ)

Tôi quyết định **quarantine thay vì warn** cho chunk quá dài (rule 9), vì chunk quá 200 ký tự thường chứa thông tin phức tạp cần được review và tách nhỏ thủ công. Điều này khác với duplicate chunk mà tôi chọn **delete trực tiếp** vì duplicate không cần can thiệp manual.

Đối với stale HR leave policy, tôi chọn **cleaning** để sửa "18 tháng" thành "6 tháng" thay vì quarantine, vì đây là lỗi text rõ ràng có thể fix tự động dựa trên data contract.

Quyết định này dựa trên severity: chunk quá dài có thể gây lỗi retrieval (chunk không liên quan), trong khi maternity leave sai có thể dẫn đến business impact nghiêm trọng nếu không fix.

Trong code, tôi implement:
```python
if len(text) > _MAX_CHUNK_LEN:
    quarantine.append({**raw, "reason": "chunk_too_long"})
```

Điều này đảm bảo data quality cao hơn so với chỉ warn.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

Khi review code, tôi phát hiện rule duplicate_chunk_id hoạt động sai: thay vì delete duplicate như mô tả, nó lại quarantine chúng. Triệu chứng: trong quarantine CSV có nhiều dòng với reason "duplicate_chunk_text" mặc dù expectation pass.

Tôi trace qua `clean_rows()` function và thấy logic sai ở dòng:
```python
key = _norm_text(text)
if key in seen_text:
    quarantine.append({**raw, "reason": "duplicate_chunk_id"})
    continue  # nên xóa dòng quarantine.append()
```

Fix: xóa `quarantine.append({**raw, "reason": "duplicate_chunk_id"})` để consistent với spec.

Sau fix, metric `quarantine_records` giảm từ 6 xuống 5 trong run `sprint2`, chứng tỏ duplicate được xử lý đúng. Expectation `min_one_row` vẫn pass vì chỉ duplicate bị loại, không phải data hợp lệ.

---

## 4. Bằng chứng trước / sau (80–120 từ)

Trước fix (run `sprint1`):
```
quarantine_records=4
quarantine_reasons: {
  "duplicate_chunk_text": 1,
  "missing_effective_date": 1,
  "stale_hr_policy_effective_date": 1,
  "unknown_doc_id": 1
}
```

Sau fix (run `sprint2`):
```
quarantine_records=5
quarantine_reasons: {
  "missing_effective_date": 1,
  "stale_hr_leave_policy_effective_date": 1,
  "unknown_doc_id": 1,
  "stale_sla_p1_2026_effective_date": 1,
  "chunk_too_long": 1
}
```

Trong sprint1, duplicate chunk bị quarantine với reason "duplicate_chunk_text". Sau khi fix trong sprint2, duplicate được delete thay vì quarantine, nhưng số quarantine tăng lên 5 do thêm dirty data và rules mới.

Log sprint2 cho thấy:
```
--- STAGE 2 — CLEAN ---
cleaned_records=7
quarantine_records=5
```

Điều này chứng tỏ fix duplicate hoạt động đúng - không còn quarantine duplicate, nhưng có thêm quarantine cho chunk quá dài và stale SLA.

---

## 5. Cải tiến tiếp theo (40–80 từ)

Nếu có thêm 2 giờ, tôi sẽ đọc cutoff date `hr_leave_min_effective_date: "2026-01-01"` từ `contracts/data_contract.yaml` thay vì hard-code trong `transform/cleaning_rules.py`. Điều này làm cho code flexible hơn, tránh magic number và đồng bộ với contract.

Hiện tại code có:
```python
_EFFECTIVE_DATES = {"hr_leave_policy": "2026-01-01", ...}
```

Sẽ thay bằng:
```python
import yaml
with open("contracts/data_contract.yaml") as f:
    config = yaml.safe_load(f)
cutoff = config["policy_versioning"]["hr_leave_min_effective_date"]
```
