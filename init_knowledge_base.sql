-- ====================================================================
-- 知识库模块建表与初始数据 SQL 脚本 (SQLite)
-- 用于其他电脑下载拉取代码后直接导入或更新数据库
-- ====================================================================

-- 1. 创建知识库与常用工具网站表 (三部分: 1.网站名称 2.网址5分段 3.说明)
CREATE TABLE IF NOT EXISTS knowledge_sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url_part1 TEXT DEFAULT '',
    url_part2 TEXT DEFAULT '',
    url_part3 TEXT DEFAULT '',
    url_part4 TEXT DEFAULT '',
    url_part5 TEXT DEFAULT '',
    description TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    created_by VARCHAR(64) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 创建排序与主键联合索引
CREATE INDEX IF NOT EXISTS idx_knowledge_sort ON knowledge_sites(sort_order, id);

-- 3. 注入默认初始常用网站数据 (若同名则忽略)
INSERT INTO knowledge_sites (title, url_part1, url_part2, url_part3, url_part4, url_part5, description, sort_order, created_by)
SELECT '亚马逊-以图搜图', 'https://www.amazon.co.jp/stylesnap', '', '', '', '', '', 1, 'admin'
WHERE NOT EXISTS (SELECT 1 FROM knowledge_sites WHERE title = '亚马逊-以图搜图');

INSERT INTO knowledge_sites (title, url_part1, url_part2, url_part3, url_part4, url_part5, description, sort_order, created_by)
SELECT '亚马逊-用户端', 'https://www.amazon.co.jp/', '', '', '', '', '', 2, 'admin'
WHERE NOT EXISTS (SELECT 1 FROM knowledge_sites WHERE title = '亚马逊-用户端');

INSERT INTO knowledge_sites (title, url_part1, url_part2, url_part3, url_part4, url_part5, description, sort_order, created_by)
SELECT '亚马逊-销量榜', 'https://www.amazon.co.jp/gp/bestsellers', '', '', '', '', '', 3, 'admin'
WHERE NOT EXISTS (SELECT 1 FROM knowledge_sites WHERE title = '亚马逊-销量榜');

INSERT INTO knowledge_sites (title, url_part1, url_part2, url_part3, url_part4, url_part5, description, sort_order, created_by)
SELECT '亚马逊-商标品牌端', 'https://brandregistry.amazon.com.au', '', '', '', '', '', 4, 'admin'
WHERE NOT EXISTS (SELECT 1 FROM knowledge_sites WHERE title = '亚马逊-商标品牌端');

INSERT INTO knowledge_sites (title, url_part1, url_part2, url_part3, url_part4, url_part5, description, sort_order, created_by)
SELECT '亚马逊-通过asin搜', 'https://www.amazon.co.jp/dp/', '{var}', '?th=1', '', '', '', 5, 'admin'
WHERE NOT EXISTS (SELECT 1 FROM knowledge_sites WHERE title = '亚马逊-通过asin搜');

INSERT INTO knowledge_sites (title, url_part1, url_part2, url_part3, url_part4, url_part5, description, sort_order, created_by)
SELECT '海关编码', 'www.hsbianma.com', '', '', '', '', '查看相关抖音介绍：抖音：9.43 :6pm o@D.us kCU:/ 05/02 亚马逊FBM发货实操教程！ # 亚马逊 # 亚马逊运营 # 亚马逊FBM # 跨境电商 # 亚马逊新手开店  https://v.douyin.com/GaSt0cAABZM/ 复制此链接，打开Dou音搜索，直接观看视频！', 6, 'admin'
WHERE NOT EXISTS (SELECT 1 FROM knowledge_sites WHERE title = '海关编码');
