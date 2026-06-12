# TASK6.md — Optional Extension Bonus Code Inventory

## Extension Summary

本次 Task 6 extension 新增登入後的「修改個人資料」功能。使用者可在 Gradio UI 中點選 `Edit Profile`，查看並更新自己的 `phone` 與 `date_of_birth`；儲存成功後 Profile panel 會自動收起。

此功能屬於 database-backed UI extension：UI 會呼叫新的 relational query function，將更新寫回 PostgreSQL 的 `user_profiles` table。本功能沒有修改 `skeleton/agent.py`，不透過 LLM tool-calling 執行。

此外，本次 Task 6 也新增了「立即刪除帳號與憑證匿名化邏輯 (Immediate Deletion Logic)」。當使用者決定刪除帳號時，系統會立即銷毀敏感憑證（包含密碼與安全提示問題的雜湊值），並對個人資料（如 user_id、email、姓名、手機、生日）進行匿名化與偽名化處理。此功能同時在 UI 中整合了相關的安全確認機制。

## Files Modified or Added

此表列出本次 Task 6 extension 的所有新增或修改檔案，以及 TA 檢查程式碼時需要定位的 table、constraints、functions。每個 modified file 前段皆有 `# TASK 6 EXTENSION:` marker。

| File | Status | Specific Names | Code Purpose |
|------|--------|----------------|--------------|
| `TASK6.md` | Added | N/A | Task 6 code inventory，列出所有 extension 檔案、function、table、constraint 名稱。 |
| `databases/relational/schema.sql` | Modified | Table: `user_profiles`; Constraints: `chk_email_format`, `chk_phone_format`, `chk_dob_past` | 在資料庫層限制 email、phone、date of birth 的格式與合理性。 |
| `databases/relational/queries.py` | Modified | Function: `update_user_profile()`; Table: `user_profiles`; Columns: `email`, `phone`, `date_of_birth`, `deleted_at` | 新增 database operation，驗證並更新登入使用者自己的 profile 欄位。 |
| `skeleton/ui.py` | Modified | Functions: `open_profile_panel()`, `on_profile_change()`, `save_profile()` | 新增 `Edit Profile` panel、欄位變更偵測、儲存流程與成功後自動收起 panel。 |
| `databases/relational/queries.py` | Modified | Function: `delete_user_account()`; Tables: `user_profiles`, `user_credentials`; Columns: `deleted_at`, `password_hash`, `secret_answer_hash`, `is_active` | 實作帳號刪除的 Transaction，確保敏感憑證匿名化與使用者資料偽名化同步成功。 |
| `skeleton/ui.py` | Modified | Functions: `delete_account()`, `do_delete_account()`; Components: `profile_delete_confirm_chk`, `profile_delete_btn`, `profile_delete_msg`; State: `current_user_state` | 在前端 UI 新增「刪除帳號」功能與安全確認機制。 |

## Code Review Notes

- `update_user_profile()` 使用 `SELECT ... FOR UPDATE` 鎖定目前登入者的 profile row，避免同一使用者同時儲存時互相覆蓋。
- `update_user_profile()` 只更新 `phone` 與 `date_of_birth`，不允許 UI 修改 email、姓名、user_id 或 credential 資料。
- 若送出的 profile 值與資料庫目前值相同，function 回傳 `changed=False`，避免不必要的 `UPDATE`。
- `skeleton/ui.py` 的 profile flow 直接使用 `current_user_state` 中的登入 email，因此只能更新目前登入者自己的資料。
- Document Section 7 的 motivation、schema snippet、example SQL queries 與 testing evidence 已寫在 `Team01_DESIGN_DOC.md`，此檔只作為 Code Task 6 導覽表。
- `delete_user_account()` 中採用資料庫 Transaction (Atomic operation)，確保 `user_profiles` 與 `user_credentials` 的修改必須同時成功或同時失敗。
- 為了保障個資安全，`delete_user_account()` 在標記帳號為已刪除（`deleted_at = NOW()`, `is_active = FALSE`）的同時，強制清空或替換密碼與安全提示解答的 Hash 值，並用隨機 UUID 覆寫 `email`、`full_name` 等具辨識度的欄位（Data Anonymization）。
- `skeleton/ui.py` 中，刪除帳號的操作具備密碼驗證或再次確認的安全機制，防範使用者誤觸。
