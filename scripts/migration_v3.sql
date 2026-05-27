-- Migration v3: chat_history 新增 feedback 欄位
-- feedback: NULL = 尚未回饋, 1 = 讚, -1 = 踩

ALTER TABLE chat_history ADD feedback TINYINT NULL;
