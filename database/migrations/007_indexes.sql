-- ==========================================
-- Migration 007 : indexes pour library_titles
-- Catégorie + tri par nom (paginated queries)
-- Jointures media_items et proposals
-- ==========================================

-- media_titles : filtre par catégorie + tri par nom
CREATE INDEX IF NOT EXISTS idx_media_titles_category
    ON media_titles(category_id);

CREATE INDEX IF NOT EXISTS idx_media_titles_cat_name
    ON media_titles(category_id, display_name);

-- media_items : jointure depuis media_titles
CREATE INDEX IF NOT EXISTS idx_media_items_title
    ON media_items(title_id);

-- rename_proposals : CTE pending proposals
CREATE INDEX IF NOT EXISTS idx_proposals_status_title
    ON rename_proposals(status, title_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_proposals_status_item
    ON rename_proposals(status, item_id)
    WHERE status = 'pending';
